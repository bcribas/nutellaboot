"""Estado das máquinas, fila de comandos e bloqueio de tela.

Diferença central em relação ao nb2: a fila é por máquina e tem confirmação
(ack). No nb2 havia um único arquivo de texto por sede em /tmp, nunca
truncado, que servia de fila E de histórico; a máquina filtrava as linhas dos
últimos 600 s e cada comando era um nome de função bash executado direto.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from .. import fsdb
from .store import site_image_dir

MAC_RE = re.compile(r"^[0-9a-f]{2}(-[0-9a-f]{2}){5,7}$")

# Comandos aceitos. `mlupdatecommands` (que baixava e executava um script
# remoto sem autenticação nenhuma) foi deliberadamente removido.
ALLOWED_COMMANDS = {
    "donottouch",
    "cantouch",
    "cleanhomenow",
    "mlreboot",
    "mlpoweroff",
    "disablefirewall",
    "enablefirewall",
    "resetcontaeditores",
    "precontest",
}

ONLINE_WINDOW = 90  # segundos sem contato para considerar a máquina offline


def normalize_mac(mac: str) -> str:
    mac = mac.strip().lower().replace(":", "-")
    return mac


def valid_mac(mac: str) -> bool:
    return bool(MAC_RE.match(mac))


# Quantas identificações inválidas diferentes guardar por imagem. É diagnóstico,
# não histórico: o que importa é "alguém está tentando, e com o quê".
MAX_REJEITADAS = 10


def record_rejected(image_id: str, bruto: str) -> None:
    """Guarda quem tentou reportar com uma identificação que não é um MAC.

    Um agente com a detecção de MAC quebrada bate no servidor a cada 25 s e
    leva 400 em tudo — inclusive no `status`, então a máquina nunca chega a
    existir e o painel fica vazio, sem dizer que alguém está tentando. Isso
    aconteceu por 30 horas seguidas antes de alguém olhar o log do servidor.
    """
    d = site_image_dir(image_id)
    if not d.is_dir():
        return
    with fsdb.locked(d):
        atual = fsdb.read_json(d / "rejected.json", {}) or {}
        entrada = atual.get(bruto) or {"first_seen": time.time(), "count": 0}
        entrada["count"] += 1
        entrada["last_seen"] = time.time()
        atual[bruto] = entrada
        if len(atual) > MAX_REJEITADAS:
            velhas = sorted(atual.items(), key=lambda kv: kv[1].get("last_seen", 0))
            atual = dict(velhas[-MAX_REJEITADAS:])
        fsdb.write_json(d / "rejected.json", atual)


def rejected(image_id: str) -> list[dict]:
    dados = fsdb.read_json(site_image_dir(image_id) / "rejected.json", {}) or {}
    out = [{"id": k, **v} for k, v in dados.items()]
    return sorted(out, key=lambda e: -(e.get("last_seen") or 0))


def machine_dir(image_id: str, mac: str) -> Path:
    return site_image_dir(image_id) / "machines" / mac


def list_macs(image_id: str) -> list[str]:
    base = site_image_dir(image_id) / "machines"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "machine.json").is_file())


def record_status(image_id: str, mac: str, status: dict) -> dict:
    d = machine_dir(image_id, mac)
    now = time.time()
    with fsdb.locked(d):
        info = fsdb.read_json(d / "machine.json", {}) or {}
        first = not info
        info.setdefault("mac", mac)
        info.setdefault("first_seen", now)
        info["last_seen"] = now
        fsdb.write_json(d / "machine.json", info)
        fsdb.write_json(d / "status.json", status)
    return {"first_seen": first, "info": info}


def get_machine(image_id: str, mac: str) -> dict:
    d = machine_dir(image_id, mac)
    info = fsdb.read_json(d / "machine.json", {}) or {}
    now = time.time()
    last = info.get("last_seen", 0)
    return {
        **info,
        "mac": mac,
        "online": (now - last) < ONLINE_WINDOW,
        "seconds_since_contact": int(now - last) if last else None,
        "status": fsdb.read_json(d / "status.json", {}) or {},
        "binding": fsdb.read_json(d / "binding.json"),
        "lock": fsdb.read_json(d / "lockstate.json", {"locked": False}),
        "pending": len(pending_commands(image_id, mac)),
        # a tela usa isto para saber se vale abrir a aba de logs; o conteúdo
        # em si só é buscado quando alguém pede
        "logs": {
            "bytes": info.get("logs_bytes", 0),
            "at": info.get("logs_at"),
        },
        # alertas abertos: ficam até alguém dispensar, então sobrevivem a
        # reboot da máquina e a recarga da página
        "alerts": fsdb.read_json(d / "alerts.json", []) or [],
    }


def list_machines(image_id: str) -> list[dict]:
    return [get_machine(image_id, mac) for mac in list_macs(image_id)]


# --- fila de comandos ---


def enqueue(image_id: str, macs: list[str], command: str, args: str = "", delay: int = 0) -> str:
    cid = secrets.token_hex(6)
    entry = {
        "id": cid,
        "command": command,
        "args": args,
        "created_at": time.time(),
        "not_before": time.time() + max(0, delay),
    }
    for mac in macs:
        q = machine_dir(image_id, mac) / "queue"
        q.mkdir(parents=True, exist_ok=True)
        fsdb.write_json(q / f"{int(time.time() * 1000)}-{cid}.json", entry)
    return cid


def pending_commands(image_id: str, mac: str) -> list[dict]:
    q = machine_dir(image_id, mac) / "queue"
    if not q.is_dir():
        return []
    out = []
    for f in sorted(q.glob("*.json")):
        entry = fsdb.read_json(f)
        if entry:
            out.append(entry)
    return out


def ready_commands(image_id: str, mac: str) -> list[dict]:
    now = time.time()
    return [c for c in pending_commands(image_id, mac) if c.get("not_before", 0) <= now]


def ack(image_id: str, mac: str, cid: str, result: dict) -> bool:
    q = machine_dir(image_id, mac) / "queue"
    found = False
    for f in list(q.glob(f"*-{cid}.json")) if q.is_dir() else []:
        f.unlink(missing_ok=True)
        found = True
    line = json.dumps(
        {"id": cid, "mac": mac, "at": time.time(), **result}, ensure_ascii=False
    )
    from .logcap import append_capped

    append_capped(machine_dir(image_id, mac) / "acks.log", line)
    return found


# --- bloqueio de tela ---


def set_lock(image_id: str, mac: str, locked: bool, by: str = "") -> dict:
    d = machine_dir(image_id, mac)
    state = {"locked": locked, "since": time.time(), "by": by}
    with fsdb.locked(d):
        fsdb.write_json(d / "lockstate.json", state)
    return state


def get_lock(image_id: str, mac: str) -> dict:
    return fsdb.read_json(machine_dir(image_id, mac) / "lockstate.json", {"locked": False})
