"""A série histórica da frota, gravada pelo próprio servidor.

O dashboard precisa responder "como estava desde as 14:00" — e a série
acumulada no navegador morre no F5 e só existe desde que a tela abriu. Ler os
samples.jsonl da frota a cada requisição seria O(máquinas) × 2 MiB. Então o
servidor grava UM ponto por minuto com os agregados por sede: ~3,5 kB/min na
frota real, cap de 32 MiB ≈ uma semana de prova em passo de minuto.

O gravador é uma tarefa asyncio no worker único (invariante 2 é o que torna
isso simples): um laço, um ponto por vez, sem concorrência de escrita.
"""

from __future__ import annotations

import asyncio
import json
import time

from ..settings import settings
from . import labs, store
from .logcap import append_capped

ARQUIVO = "serie-frota.jsonl"
# 32 MiB: o ponto ganhou os editores por sede (~3,5 kB/min na frota real),
# e o teto guarda ~1 semana de prova em passo de minuto
CAP = 32 * 1024 * 1024
INTERVALO = 60
# a resposta tem teto de pontos: janela longa sai com passo maior (a prática
# dos painéis de monitoramento — ninguém distingue 5000 pontos numa tela)
MAX_PONTOS = 400


def _path():
    return settings.data_root / "reports" / ARQUIVO


def gravar_ponto(agora: float | None = None) -> dict:
    """Um ponto: {t, sites: {id: [online, mem_avg, cpu_avg, alerts, {ed: n}]}}.

    Os editores ficam POR SEDE, não no total: é o que permite ao `serie()`
    recortar pela visibilidade de quem pergunta — um total da frota gravado
    pronto vazaria para sub-admin e chave com glob. Pontos antigos têm a
    lista com 4 elementos; o 5º é opcional na leitura."""
    agora = agora or time.time()
    desde = agora - 86400  # a janela de "ativas" não importa aqui
    sites = {}
    for img in store.list_site_images():
        r = labs.resumo_de(img["id"], desde=desde)
        # compacto de propósito: 55 sedes × 1440 pontos/dia somam rápido
        v = [
            r["online"],
            r["res"]["mem_avg"],
            r["res"]["cpu_avg"],
            r["alerts"],
        ]
        ed = dict(sorted(r.get("editors_now", {}).items(), key=lambda kv: -kv[1])[:4])
        if ed:
            v.append(ed)
        sites[img["id"]] = v
    ponto = {"t": int(agora), "sites": sites}
    append_capped(_path(), json.dumps(ponto, separators=(",", ":")), cap=CAP)
    return ponto


async def gravador() -> None:
    while True:
        try:
            gravar_ponto()
        except Exception:  # noqa: BLE001 — o gravador não pode morrer por uma sede podre
            pass
        await asyncio.sleep(INTERVALO)


_tarefa = None


def iniciar() -> None:
    global _tarefa
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _tarefa is None or _tarefa.done():
        _tarefa = loop.create_task(gravador())


def _pode_ver(p, site_id: str) -> bool:
    kind = getattr(p, "kind", "")
    if kind == "admin":
        return True
    if kind == "service":
        return p.can_see_image(site_id)
    # sub-admin: dono
    info = store.get_site_image(site_id) or {}
    return info.get("owner") == getattr(p, "owner", None)


def serie(p, *, since: float = 0, until: float = 0, site: str = "") -> list[dict]:
    """Os pontos da janela, filtrados pela VISIBILIDADE de quem pergunta.

    O total da frota é recalculado do subconjunto visível — devolver o total
    bruto vazaria a contagem das sedes alheias para sub-admin e para a chave
    compartilhada com glob.
    """
    until = until or time.time()
    caminho = _path()
    if not caminho.is_file():
        return []
    if site and not _pode_ver(p, site):
        # 404 e não 403: mesmo contrato do resto do console
        raise KeyError(site)

    visiveis: dict[str, bool] = {}

    def ve(sid: str) -> bool:
        if sid not in visiveis:
            visiveis[sid] = _pode_ver(p, sid)
        return visiveis[sid]

    pontos = []
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            try:
                d = json.loads(linha)
            except ValueError:
                continue  # o cap corta a metade antiga; a 1ª linha pode estar partida
            t = d.get("t") or 0
            if t < since or t > until:
                continue
            sites = d.get("sites") or {}
            if site:
                v = sites.get(site)
                if v is None:
                    continue
                p_ = {"t": t, "online": v[0], "mem": v[1], "cpu": v[2], "alerts": v[3]}
                if len(v) > 4 and v[4]:
                    p_["ed"] = v[4]
                pontos.append(p_)
                continue
            on = al = 0
            mems = []
            cpus = []
            eds: dict[str, int] = {}
            for sid, v in sites.items():
                if not ve(sid):
                    continue
                on += v[0] or 0
                al += v[3] or 0
                if v[1] is not None:
                    mems.append(v[1])
                if v[2] is not None:
                    cpus.append(v[2])
                if len(v) > 4 and isinstance(v[4], dict):
                    for ed, n in v[4].items():
                        eds[ed] = eds.get(ed, 0) + (n or 0)
            p_ = {
                "t": t,
                "online": on,
                "mem": round(sum(mems) / len(mems)) if mems else None,
                "cpu": round(sum(cpus) / len(cpus)) if cpus else None,
                "alerts": al,
            }
            if eds:
                p_["ed"] = eds
            pontos.append(p_)
    if len(pontos) > MAX_PONTOS:
        passo = len(pontos) / MAX_PONTOS
        pontos = [pontos[int(i * passo)] for i in range(MAX_PONTOS)]
    return pontos
