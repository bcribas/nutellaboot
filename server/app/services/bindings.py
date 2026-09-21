"""Vínculo máquina ↔ time, com histórico.

O `binding.json` é o vínculo ATUAL (o painel e a tela de bloqueio leem só
ele). Mas o MOJ precisa de mais: quem afirmou o vínculo (`source`), quando o
cliente o viu (`client_at`, o instante do login no juiz) e em qual boot
(`boot_id`) — e a troca de máquina no meio da prova é informação, não ruído.
Por isso toda mudança vira uma linha em `bindings.log`, com teto, no mesmo
padrão do `alerts.log` e do `acks.log`.
"""

from __future__ import annotations

import json
import time

from .. import fsdb
from .logcap import append_capped
from .machines import machine_dir

ARQUIVO = "binding.json"
LOG = "bindings.log"
HISTORICO = 256 * 1024
CAMPOS_DO_VINCULO = ("user_id", "name", "seat", "boot_id", "client_at", "note")


def _log(d, evento: dict) -> None:
    append_capped(d / LOG, json.dumps(evento, ensure_ascii=False), cap=HISTORICO)


def gravar(image_id: str, mac: str, binding: dict) -> dict:
    d = machine_dir(image_id, mac)
    d.mkdir(parents=True, exist_ok=True)
    with fsdb.locked(d):
        fsdb.write_json(d / ARQUIVO, binding)
        _log(d, {"event": "bound", "mac": mac, **binding})
    return binding


def remover(image_id: str, mac: str, *, by: str, source: str) -> dict | None:
    """Devolve o vínculo removido, ou None se não havia (aí não há linha)."""
    d = machine_dir(image_id, mac)
    with fsdb.locked(d):
        anterior = fsdb.read_json(d / ARQUIVO)
        (d / ARQUIVO).unlink(missing_ok=True)
        if anterior:
            _log(
                d,
                {
                    "event": "unbound",
                    "mac": mac,
                    "at": int(time.time()),
                    "by": by,
                    "source": source,
                    **{k: anterior[k] for k in CAMPOS_DO_VINCULO if k in anterior},
                },
            )
    return anterior


def history(image_id: str, mac: str, linhas: int = 200) -> list[dict]:
    p = machine_dir(image_id, mac) / LOG
    if not p.is_file():
        return []
    out = []
    for linha in p.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:]:
        try:
            out.append(json.loads(linha))
        except ValueError:
            continue
    return out
