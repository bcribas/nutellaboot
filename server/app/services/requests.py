"""Fila de pedidos de imagem — para quem não tem código de convite.

Uma pessoa preenche o que quer; o pedido fica pendente até o admin aprovar
(emitindo um código ou criando a imagem direto) ou recusar.

`data/requests/<id>.json`.
"""

from __future__ import annotations

import secrets
import time

from .. import fsdb
from ..settings import settings


def _dir():
    return settings.data_root / "requests"


def submit(wanted_name: str, contact: str, note: str) -> dict:
    rid = secrets.token_hex(6)
    entry = {
        "id": rid,
        "wanted_name": wanted_name[:64],
        "contact": contact[:200],
        "note": note[:1000],
        "status": "pending",
        "created_at": time.time(),
    }
    fsdb.write_json(_dir() / f"{rid}.json", entry)
    return entry


def list_all(status: str | None = None) -> list[dict]:
    d = _dir()
    if not d.is_dir():
        return []
    out = [fsdb.read_json(f) for f in d.glob("*.json")]
    out = [r for r in out if r and (status is None or r.get("status") == status)]
    return sorted(out, key=lambda r: -r.get("created_at", 0))


def get(rid: str) -> dict | None:
    return fsdb.read_json(_dir() / f"{rid}.json")


def set_status(rid: str, status: str, extra: dict | None = None) -> dict | None:
    p = _dir() / f"{rid}.json"
    entry = fsdb.read_json(p)
    if entry is None:
        return None
    entry["status"] = status
    entry["decided_at"] = time.time()
    if extra:
        entry.update(extra)
    fsdb.write_json(p, entry)
    return entry
