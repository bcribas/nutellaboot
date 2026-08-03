"""Série temporal da telemetria — o que o `status.json` não guarda.

`machines.record_status` sobrescreve o retrato a cada ~45 s. Isso responde
"como está a sala agora", que é o que o painel precisa, e não responde nada
sobre o que aconteceu entre 14h e 16h — que é o que um relatório de prova
precisa. Memória, carga e editores existiam só no presente.

Aqui cada envio vira UMA LINHA curta por máquina. Quatro números e uma lista,
~60 bytes; a 45 s são 60 kB por máquina por dia, e o teto de 2 MiB do projeto
guarda cerca de um mês. É de propósito que não seja o status inteiro: o dict de
telemetria é livre (um `parts.d` novo entra sem mudar o servidor), e gravar
tudo faria o arquivo crescer sem teto previsível.

Não mexe no cliente: vale para as máquinas que já estão rodando.
"""

from __future__ import annotations

import json
import time

from .. import fsdb
from .logcap import append_capped
from .machines import machine_dir

# 2 MiB por máquina, como o journal. `append_capped` descarta a metade MAIS
# ANTIGA quando estoura — o relatório avisa quando o intervalo pedido começa
# antes do que sobrou.
POR_MAQUINA = 2 * 1024 * 1024

ARQUIVO = "samples.jsonl"


def _num(v, casas: int = 0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, casas) if casas else int(f)


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
    editores = ops.get("editors")
    if isinstance(editores, list):
        linha["ed"] = [str(e)[:24] for e in editores[:8]]
    fw = ops.get("firewall")
    if fw is not None:
        linha["fw"] = 1 if fw else 0
    if ops.get("screen_lock"):
        linha["lk"] = 1

    append_capped(
        machine_dir(image_id, mac) / ARQUIVO,
        json.dumps(linha, ensure_ascii=False, separators=(",", ":")) + "\n",
        cap=POR_MAQUINA,
    )


def series(image_id: str, mac: str, since: float = 0, until: float = 0) -> list[dict]:
    """As amostras do intervalo, em ordem. Linha corrompida é pulada: o
    truncamento pela metade pode cortar a primeira ao meio."""
    p = machine_dir(image_id, mac) / ARQUIVO
    if not p.is_file():
        return []
    out = []
    for linha in p.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha.startswith("{"):
            continue
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        t = d.get("t") or 0
        if since and t < since:
            continue
        if until and t > until:
            continue
        out.append(d)
    return out


def primeira_amostra(image_id: str, mac: str) -> float:
    """Quando começa o que sobrou em disco — para o relatório poder dizer que o
    intervalo pedido é mais antigo que os dados."""
    s = series(image_id, mac)
    return float(s[0].get("t", 0)) if s else 0.0


def foi_truncado(image_id: str, mac: str) -> bool:
    """O arquivo chegou ao teto — ou seja, `append_capped` já descartou a
    metade mais antiga pelo menos uma vez.

    É o único sinal honesto de "faltou histórico". Deduzir isso de "a amostra
    mais antiga é recente" acusaria toda máquina que ligou no meio da prova, e
    toda máquina que já existia antes de a amostragem passar a existir.
    """
    p = machine_dir(image_id, mac) / ARQUIVO
    try:
        return p.stat().st_size >= POR_MAQUINA * 0.9
    except OSError:
        return False


def machine_key(image_id: str, mac: str) -> str:
    return f"{image_id}/{mac}"


def limpar(image_id: str, mac: str) -> None:
    p = machine_dir(image_id, mac) / ARQUIVO
    if p.is_file():
        fsdb.write_text(p, "")
