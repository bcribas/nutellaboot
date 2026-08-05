"""Resumo da frota: uma linha por sede, para o painel de quem administra.

Existe porque a rota por sede não escala para o conjunto. Medido com 1890
máquinas de mentira (54 sedes × 35, que é a primeira fase):

    list_machines() para a frota inteira   222 ms e 0,9 MB
    este resumo (3 leituras por máquina)   119 ms

O painel por sede reatualiza 400 ms depois de qualquer evento; repetir isso na
frota seria 30% do worker ÚNICO, para sempre — o mesmo que atende o boot da
sala. Daí duas decisões: o payload é o que a tela mostra (não o status inteiro
de cada máquina) e a tela sonda a cada 5 s em vez de reagir a evento.

O cache de poucos segundos põe teto no custo independentemente de quantos
painéis abram ou de quão rápido alguém aperte F5.
"""

from __future__ import annotations

import time

from .. import fsdb
from . import machines as m
from . import ownership, store

# Quanto tempo um resumo serve. Curto o bastante para a tela parecer viva e
# longo o bastante para F5 repetido não virar carga.
CACHE_SEG = 3.0

DIAS_PADRAO = 7

# a chave inclui QUEM perguntou: um cache por janela só, compartilhado entre
# principais, serviria a um sub-admin a contagem de sedes que não são dele
_cache: dict[tuple, tuple[float, list[dict]]] = {}


def _janela(dias: float) -> float:
    return time.time() - max(0.0, dias) * 86400


# A lista de alertas por sede tem teto: o payload da sondagem de 5 s não pode
# crescer sem limite (35 máquinas × 50 alertas abertos — o teto por máquina —
# seriam 1750 entradas numa linha). A contagem `alerts` continua sendo o
# TOTAL: a coluna não pode mentir quando a lista trunca.
ALERTAS_NA_LINHA = 15


def resumo_de(image_id: str, *, desde: float) -> dict:
    """As contas de uma sede. Cinco leituras por máquina — a quinta é o
    `status.json`, e ela tem regra própria: o arquivo é LIVRE (um parts.d novo
    no agente pode inflá-lo até 256 kB), então daqui saem só campos fixos de
    `sysresources` e o `cores`, nunca o dict — o payload da sondagem não pode
    crescer com o que o agente resolver mandar. Hoje ele tem ~500 B e a
    leitura custa ~25 ms na frota inteira, dentro do cache de 3 s."""
    agora = time.time()
    total = ativas = novas = online = travadas = alertas = sem_time = 0
    lista_alertas: list[dict] = []
    mems: list[int] = []
    cpus: list[int] = []
    swap_mb = swap_on = 0
    for mac in m.list_macs(image_id):
        d = m.machine_dir(image_id, mac)
        info = fsdb.read_json(d / "machine.json", {}) or {}
        binding = fsdb.read_json(d / "binding.json")
        total += 1
        visto = info.get("last_seen", 0)
        if visto >= desde:
            ativas += 1
        if info.get("first_seen", 0) >= desde:
            novas += 1
        esta_online = (agora - visto) < m.ONLINE_WINDOW
        if esta_online:
            online += 1
            # recursos SÓ das ligadas: o mem_pct de uma máquina desligada é o
            # último valor antes de morrer, e entraria na média como se fosse
            # de agora
            status = fsdb.read_json(d / "status.json", {}) or {}
            res = status.get("sysresources") or {}
            hw = status.get("hwinfo") or {}
            if isinstance(res.get("mem_pct"), (int, float)):
                mems.append(int(res["mem_pct"]))
            load = res.get("loadavg")
            cores = hw.get("cores")
            if (
                isinstance(load, list) and load
                and isinstance(load[0], (int, float))
                and isinstance(cores, (int, float)) and cores
            ):
                # CPU% não existe na telemetria; o proxy honesto é load1 por
                # núcleo, saturado em 100
                cpus.append(min(100, round(100 * load[0] / cores)))
            sw = res.get("swap_used_mb")
            if isinstance(sw, (int, float)) and sw > 0:
                swap_mb += int(sw)
                swap_on += 1
        if (fsdb.read_json(d / "lockstate.json", {}) or {}).get("locked"):
            travadas += 1
        # o arquivo sempre foi lido INTEIRO e só o len() era aproveitado — foi
        # assim que o painel dizia "3 alertas" sem conseguir dizer quais
        abertos = fsdb.read_json(d / "alerts.json", []) or []
        alertas += len(abertos)
        for a in abertos:
            if not isinstance(a, dict):
                continue
            lista_alertas.append({
                "mac": mac,
                "kind": a.get("kind", ""),
                "detail": a.get("detail", ""),
                "vendor": a.get("vendor", ""),
                "at": a.get("at", 0),
                "team": (binding or {}).get("name", ""),
            })
        if not binding:
            sem_time += 1
    lista_alertas.sort(key=lambda a: a.get("at") or 0, reverse=True)
    return {
        "machines": total,
        "active": ativas,
        "new": novas,
        "online": online,
        "locked": travadas,
        "alerts": alertas,
        "unbound": sem_time,
        "alert_list": lista_alertas[:ALERTAS_NA_LINHA],
        # agregados O(1) por sede — é o que o dashboard desenha
        "res": {
            "mem_avg": round(sum(mems) / len(mems)) if mems else None,
            "mem_max": max(mems) if mems else None,
            "cpu_avg": round(sum(cpus) / len(cpus)) if cpus else None,
            "cpu_max": max(cpus) if cpus else None,
            "swap_mb": swap_mb,
            "swap_on": swap_on,
        },
    }


def resumo(p, *, dias: float = DIAS_PADRAO) -> list[dict]:
    """Uma linha por sede visível a este principal."""
    chave = (getattr(p, "kind", ""), getattr(p, "owner", ""), getattr(p, "name", ""), float(dias))
    agora = time.time()
    guardado = _cache.get(chave)
    if guardado and (agora - guardado[0]) < CACHE_SEG:
        return guardado[1]

    desde = _janela(dias)
    linhas = [
        {
            "id": i["id"],
            "fullname": i.get("fullname", ""),
            "model": i.get("model", ""),
            **resumo_de(i["id"], desde=desde),
        }
        for i in ownership.visible_site_images(p)
    ]
    linhas.sort(key=lambda l: l["id"])
    _cache[chave] = (agora, linhas)
    return linhas


def limpar_cache() -> None:
    """Para os testes: sem isto, um teste enxergaria a contagem do anterior."""
    _cache.clear()


COLUNAS_CSV = (
    "id",
    "fullname",
    "machines",
    "active",
    "new",
    "online",
    "locked",
    "alerts",
    "unbound",
)


def csv_de(linhas: list[dict]) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUNAS_CSV)
    for l in linhas:
        w.writerow([l.get(c, "") for c in COLUNAS_CSV])
    return buf.getvalue()


def site_existe(image_id: str) -> bool:
    return store.site_image_exists(image_id)
