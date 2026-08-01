"""Pool de seeders por imagem, com TTL por heartbeat.

`seeders.json` = {"<ip>": {"last_seen": epoch}}. Um seeder entra com `join`,
renova com `heartbeat` (a cada ~60 s) e sai com `leave`; quem parar de
renovar expira sozinho após `seeder_ttl_sec` — nenhum boot fica preso em
seeder morto (e o manifest sempre traz o CDN como última fonte).
"""

from __future__ import annotations

import ipaddress
import time

from .. import fsdb
from .store import image_dir, server_conf


def _path(image_id: str):
    return image_dir(image_id) / "seeders.json"


def _ttl() -> int:
    return int(server_conf().get("seeder_ttl_sec", 180))


def valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _prune(pool: dict, now: float) -> dict:
    ttl = _ttl()
    return {ip: e for ip, e in pool.items() if now - e.get("last_seen", 0) <= ttl}


def live(image_id: str) -> list[str]:
    now = time.time()
    pool = fsdb.read_json(_path(image_id), {}) or {}
    fresh = _prune(pool, now)
    # ordena do heartbeat mais recente para o mais antigo
    return sorted(fresh, key=lambda ip: -fresh[ip]["last_seen"])


def detail(image_id: str) -> list[dict]:
    now = time.time()
    pool = _prune(fsdb.read_json(_path(image_id), {}) or {}, now)
    ttl = _ttl()
    return [
        {"ip": ip, "last_seen": int(e["last_seen"]), "ttl_left": int(ttl - (now - e["last_seen"]))}
        for ip, e in sorted(pool.items(), key=lambda kv: -kv[1]["last_seen"])
    ]


def touch(image_id: str, ip: str) -> None:
    """join e heartbeat são a mesma operação: registrar last_seen agora."""
    now = time.time()
    d = image_dir(image_id)
    with fsdb.locked(d):
        pool = fsdb.read_json(_path(image_id), {}) or {}
        pool[ip] = {"last_seen": now}
        fsdb.write_json(_path(image_id), _prune(pool, now))


def leave(image_id: str, ip: str) -> None:
    d = image_dir(image_id)
    with fsdb.locked(d):
        pool = fsdb.read_json(_path(image_id), {}) or {}
        pool.pop(ip, None)
        fsdb.write_json(_path(image_id), pool)
