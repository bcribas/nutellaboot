"""Série temporal da telemetria — o que o `status.json` não guarda.

`machines.record_status` sobrescreve o retrato a cada 40 a 59 s. Isso
responde "como está a sala agora", que é o que o painel precisa, e não
responde nada sobre o que aconteceu entre 14h e 16h — que é o que um
relatório de prova precisa. Memória, carga e editores existiam só no
presente.

Aqui cada envio vira UMA LINHA curta por máquina. Poucos números e uma lista,
~60 bytes; a ~50 s são ~100 kB por máquina por dia, e o teto de 2 MiB do
projeto guarda algumas semanas. É de propósito que não seja o status inteiro:
o dict de telemetria é livre (um `parts.d` novo entra sem mudar o servidor),
e gravar tudo faria o arquivo crescer sem teto previsível. Campos que o
agente novo manda (PSI, OOM, ociosidade, relógio) entram no ponto SÓ quando
presentes: a frota é heterogênea, e um agente antigo continua válido.

O corte do teto fica registrado em `samples.meta.json`: é o único jeito de
`truncated` ser honesto. Deduzir o corte do tamanho do arquivo errava por
dias — depois do corte o arquivo fica na metade do teto, abaixo de qualquer
limiar.

Não mexe no cliente: vale para as máquinas que já estão rodando.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import fsdb
from .logcap import append_capped
from .machines import machine_dir

# 2 MiB por máquina, como o journal. `append_capped` descarta a metade MAIS
# ANTIGA quando estoura — e avisa, para o meta registrar o corte.
POR_MAQUINA = 2 * 1024 * 1024

ARQUIVO = "samples.jsonl"
META = "samples.meta.json"
_PREFIXO = '{"t":'


def _num(v, casas: int = 0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, casas) if casas else int(f)


def _t_da_linha(linha: str) -> int | None:
    """O `t` sem json.loads: toda linha gravada aqui começa com {"t":N, (o
    dict é montado com "t" primeiro e separators sem espaço). Linha que não
    segue o padrão devolve None e cai no parse completo."""
    if not linha.startswith(_PREFIXO):
        return None
    fim = linha.find(",", len(_PREFIXO))
    if fim < 0:
        fim = linha.find("}", len(_PREFIXO))
    try:
        return int(linha[len(_PREFIXO) : fim])
    except ValueError:
        return None


def _primeiro_t(p: Path) -> int:
    """O `t` da primeira linha íntegra — lê só o começo do arquivo."""
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for linha in fh:
                t = _t_da_linha(linha)
                if t is None and linha.startswith("{"):
                    try:
                        t = int(json.loads(linha).get("t") or 0)
                    except ValueError:
                        t = None
                if t:
                    return t
    except OSError:
        pass
    return 0


def _registra_corte(d: Path) -> None:
    meta = fsdb.read_json(d / META, {}) or {}
    fsdb.write_json(
        d / META,
        {
            "cuts": int(meta.get("cuts") or 0) + 1,
            # o primeiro ponto que sobreviveu ao corte: antes dele não há dado
            "first_t": _primeiro_t(d / ARQUIVO),
            "cut_at": int(time.time()),
        },
    )


def corte(image_id: str, mac: str) -> dict | None:
    return fsdb.read_json(machine_dir(image_id, mac) / META)


def truncado(image_id: str, mac: str, since: float = 0) -> bool:
    """Verdadeiro só quando o teto cortou DE FATO e o corte alcança a janela
    pedida (since=0 é "desde sempre", logo qualquer corte conta)."""
    meta = corte(image_id, mac)
    return bool(meta and meta.get("cuts", 0) > 0 and since < meta.get("first_t", 0))


def record(image_id: str, mac: str, status: dict) -> None:
    """Extrai da telemetria o que dá para colocar num gráfico."""
    if not isinstance(status, dict):
        return
    rec = status.get("sysresources") or {}
    ops = status.get("operations") or {}
    carga = rec.get("loadavg") or []

    linha = {"t": int(time.time())}
    mem = _num(rec.get("mem_pct"))
    if mem is not None:
        linha["mem"] = mem
    if isinstance(carga, list) and carga:
        ld = _num(carga[0], 2)
        if ld is not None:
            linha["ld"] = ld
    sw = _num(rec.get("swap_used_mb"))
    if sw is not None:
        linha["sw"] = sw
    # disco do /home: o que enche durante a prova. Histórico barato (um int
    # por amostra) para o relatório de período poder responder "quando encheu"
    hd = _num((status.get("sysdisk") or {}).get("home_pct"))
    if hd is not None:
        linha["hd"] = hd
    editores = ops.get("editors")
    if isinstance(editores, list):
        linha["ed"] = [str(e)[:24] for e in editores[:8]]
    fw = ops.get("firewall")
    if fw is not None:
        linha["fw"] = 1 if fw else 0
    if ops.get("screen_lock"):
        linha["lk"] = 1
    # pressão (PSI), OOM e ociosidade: só o agente novo manda
    for chave, origem, casas in (
        ("psi_mem", "psi_mem", 1),
        ("psi_cpu", "psi_cpu", 1),
        ("psi_io", "psi_io", 1),
        ("oom", "oom_kills", 0),
        ("idle", "idle_s", 0),
    ):
        v = _num(rec.get(origem), casas)
        if v is not None:
            linha[chave] = v
    # minutos acumulados de editor e desde quando: por subtração entre dois
    # pontos sai o uso do PERÍODO, que é o que um relatório de prova quer
    tempos = ops.get("editors_time")
    if isinstance(tempos, dict):
        edm = _num(tempos.get("total"))
        if edm is not None:
            linha["edm"] = edm
    eds = _num(ops.get("editors_time_since"))
    if eds:
        linha["eds"] = eds
    # relógio do agente: uma máquina com hora errada desloca a série inteira
    t_agent = _num(status.get("t_agent"))
    if t_agent:
        linha["skew"] = linha["t"] - t_agent

    d = machine_dir(image_id, mac)
    if append_capped(
        d / ARQUIVO,
        json.dumps(linha, ensure_ascii=False, separators=(",", ":")) + "\n",
        cap=POR_MAQUINA,
    ):
        _registra_corte(d)


def series(image_id: str, mac: str, since: float = 0, until: float = 0) -> list[dict]:
    """As amostras do intervalo, em ordem. Lê linha a linha e corta pelo `t`
    do prefixo antes de fazer json.loads — 2 MiB por máquina vezes N máquinas
    num worker só (invariante 2) não podem virar parse inteiro a cada
    pedido. Linha corrompida é pulada: o truncamento pela metade pode cortar
    a primeira ao meio."""
    p = machine_dir(image_id, mac) / ARQUIVO
    if not p.is_file():
        return []
    out = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for linha in fh:
            if not linha.startswith("{"):
                continue
            t = _t_da_linha(linha)
            if t is not None and ((since and t < since) or (until and t > until)):
                continue
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            if t is None:
                t = d.get("t") or 0
                if (since and t < since) or (until and t > until):
                    continue
            out.append(d)
    return out


def primeira_amostra(image_id: str, mac: str) -> float:
    """Quando começa o que sobrou em disco."""
    return float(_primeiro_t(machine_dir(image_id, mac) / ARQUIVO))


def reamostrar(pontos: list, limite: int) -> list:
    """Passo uniforme que SEMPRE inclui o primeiro e o último ponto — o passo
    inteiro antigo (`int(i*passo)`) nunca alcançava o fim da janela."""
    n = len(pontos)
    if n <= limite:
        return pontos
    if limite == 1:
        return [pontos[-1]]
    return [pontos[round(i * (n - 1) / (limite - 1))] for i in range(limite)]


def intervalo_mediano(pontos: list) -> int | None:
    dts = sorted(
        b["t"] - a["t"]
        for a, b in zip(pontos, pontos[1:])
        if isinstance(a.get("t"), int) and isinstance(b.get("t"), int)
    )
    return int(dts[len(dts) // 2]) if dts else None


def janela(image_id: str, mac: str, since: float = 0, until: float = 0, limit: int = 400) -> dict:
    """O payload de uma máquina — o mesmo na rota individual e no lote. Os
    metadados dizem o que foi feito: sem `resampled`/`interval_s` ninguém
    distingue cadência do agente de passo do reamostrador."""
    nativos = series(image_id, mac, since, until)
    pontos = reamostrar(nativos, limit)
    return {
        "mac": mac,
        "points": pontos,
        "native_points": len(nativos),
        "resampled": len(pontos) < len(nativos),
        "interval_s": intervalo_mediano(nativos),
        # inteiros, como o `t` dos pontos: a query aceita fração, o eco não
        "since": int(since),
        "until": int(until),
        "truncated": truncado(image_id, mac, since),
    }


def machine_key(image_id: str, mac: str) -> str:
    return f"{image_id}/{mac}"


def limpar(image_id: str, mac: str) -> None:
    d = machine_dir(image_id, mac)
    if (d / ARQUIVO).is_file():
        fsdb.write_text(d / ARQUIVO, "")
    (d / META).unlink(missing_ok=True)
