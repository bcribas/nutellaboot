"""Pool de seeders por imagem, com TTL por heartbeat e liberação remota.

`seeders.json` = {"<ip>": {"last_seen": epoch, "released"?: true}}. Um seeder
entra com `join` (que respeita o limite SEEDMAX da imagem), renova com
`heartbeat` (a cada ~60 s) e sai com `leave`; quem parar de renovar expira
sozinho após `seeder_ttl_sec` — nenhum boot fica preso em seeder morto (e o
manifest sempre traz o CDN como última fonte).

O console pode liberar um seeder (`release`): a entrada vira um tombstone
`released` que o heartbeat da máquina enxerga — ela então sai do modo seed,
chama `leave` e termina o boot. O tombstone também expira pelo TTL, cobrindo
a máquina que morreu antes de se despedir.
"""

from __future__ import annotations

import ipaddress
import time

from .. import fsdb
from .store import site_image_dir, server_conf


def _path(image_id: str):
    return site_image_dir(image_id) / "seeders.json"


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


def _vivos(pool: dict) -> int:
    return sum(1 for e in pool.values() if not e.get("released"))


def live(image_id: str) -> list[str]:
    now = time.time()
    pool = _prune(fsdb.read_json(_path(image_id), {}) or {}, now)
    ativos = {ip: e for ip, e in pool.items() if not e.get("released")}
    # ordena do heartbeat mais recente para o mais antigo
    return sorted(ativos, key=lambda ip: -ativos[ip]["last_seen"])


def detail(image_id: str) -> list[dict]:
    now = time.time()
    pool = _prune(fsdb.read_json(_path(image_id), {}) or {}, now)
    ttl = _ttl()
    return [
        {
            "ip": ip,
            "last_seen": int(e["last_seen"]),
            "ttl_left": int(ttl - (now - e["last_seen"])),
            "released": bool(e.get("released")),
        }
        for ip, e in sorted(pool.items(), key=lambda kv: -kv[1]["last_seen"])
    ]


def join(image_id: str, ip: str, cap: int) -> dict:
    """Entra no pool respeitando o limite de seeders simultâneos.

    Renovação de IP já vivo sempre passa (não é entrada nova); voltar de um
    tombstone conta como entrada nova — a máquina reiniciou — e limpa o
    tombstone se aceita.
    """
    now = time.time()
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        pool = _prune(fsdb.read_json(_path(image_id), {}) or {}, now)
        entrada = pool.get(ip)
        renovando = entrada is not None and not entrada.get("released")
        if not renovando and cap > 0 and _vivos(pool) >= cap:
            fsdb.write_json(_path(image_id), pool)
            return {"accepted": False, "new": False, "count": _vivos(pool)}
        pool[ip] = {"last_seen": now}
        fsdb.write_json(_path(image_id), pool)
        return {"accepted": True, "new": not renovando, "count": _vivos(pool)}


def heartbeat(image_id: str, ip: str) -> dict:
    """Renova o registro; devolve se o console liberou a máquina.

    O tombstone também tem o last_seen renovado: sem isso ele expiraria no
    meio da conversa e o próprio heartbeat ressuscitaria a entrada como viva.
    """
    now = time.time()
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        pool = _prune(fsdb.read_json(_path(image_id), {}) or {}, now)
        released = bool(pool.get(ip, {}).get("released"))
        pool[ip] = {"last_seen": now, **({"released": True} if released else {})}
        fsdb.write_json(_path(image_id), pool)
        return {"released": released, "count": _vivos(pool)}


def release(image_id: str, ip: str) -> None:
    """Marca o tombstone: a máquina sai sozinha no próximo heartbeat e o
    `leave` dela é quem remove a entrada de vez."""
    now = time.time()
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        pool = _prune(fsdb.read_json(_path(image_id), {}) or {}, now)
        pool[ip] = {"last_seen": now, "released": True}
        fsdb.write_json(_path(image_id), pool)


def leave(image_id: str, ip: str) -> None:
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        pool = fsdb.read_json(_path(image_id), {}) or {}
        pool.pop(ip, None)
        fsdb.write_json(_path(image_id), pool)
