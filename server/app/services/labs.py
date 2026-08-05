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
    """As contas de uma sede. Quatro leituras por máquina, e nenhuma delas é o
    `status.json` — que é livre, pode ter 256 kB e não cabe num resumo."""
    agora = time.time()
    total = ativas = novas = online = travadas = alertas = sem_time = 0
    lista_alertas: list[dict] = []
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
        if (agora - visto) < m.ONLINE_WINDOW:
            online += 1
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
