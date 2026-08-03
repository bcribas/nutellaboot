"""Alertas de máquina — o que alguém precisa olhar agora.

O caso que motivou: pendrive ou celular espetado numa máquina durante a prova.
A regra escolhida é que o alerta **fica até alguém dispensar**, e não some
sozinho quando o dispositivo é removido — quem espeta um pendrive por cinco
segundos não pode escapar do registro. Some só quando um fiscal clica, e fica
gravado quem dispensou e quando.

Dois arquivos por máquina:
  * `alerts.json` — os abertos, que a tela mostra;
  * `alerts.log`  — o histórico completo (com teto), que responde depois da
    prova "o que apareceu naquela máquina, e quem dispensou".
"""

from __future__ import annotations

import json
import secrets
import time

from .. import fsdb
from .logcap import append_capped
from .machines import machine_dir, list_macs

# Tipos conhecidos. A lista existe para a tela saber traduzir e escolher o
# ícone; um tipo desconhecido continua entrando (o cliente pode evoluir sem o
# servidor), só cai no texto genérico.
TIPOS = (
    "usb.storage",  # pendrive, HD externo, leitor de cartão
    "usb.phone",  # celular em MTP/PTP
    "usb.network",  # tethering (RNDIS/CDC/NCM)
    "usb.other",
    # disco inserido num drive óptico — que costuma ser interno, e por isso
    # não é `usb.*`. Ter o leitor não alarma; pôr um disco nele, sim.
    "media.cd",
)

MAX_ABERTOS = 50  # por máquina; acima disso o mais antigo cede lugar
HISTORICO = 256 * 1024


def _path(image_id: str, mac: str):
    return machine_dir(image_id, mac) / "alerts.json"


def open_alerts(image_id: str, mac: str) -> list[dict]:
    return fsdb.read_json(_path(image_id, mac), []) or []


def raise_alert(image_id: str, mac: str, kind: str, detail: str = "", extra: dict | None = None) -> dict:
    """Registra um alerta novo. Devolve o alerta criado."""
    kind = str(kind or "usb.other")[:40]
    alerta = {
        "id": secrets.token_hex(6),
        "kind": kind,
        "detail": str(detail or "")[:300],
        "at": time.time(),
        "mac": mac,
        **(extra or {}),
    }
    d = machine_dir(image_id, mac)
    with fsdb.locked(d):
        abertos = fsdb.read_json(d / "alerts.json", []) or []
        abertos.append(alerta)
        fsdb.write_json(d / "alerts.json", abertos[-MAX_ABERTOS:])
    append_capped(
        d / "alerts.log",
        json.dumps({"event": "raised", **alerta}, ensure_ascii=False),
        cap=HISTORICO,
    )
    return alerta


def dismiss(image_id: str, mac: str, alert_id: str, by: str) -> dict | None:
    """Dispensa um alerta. Devolve o que foi dispensado, ou None se já não
    estava aberto (dois fiscais clicando ao mesmo tempo é normal)."""
    d = machine_dir(image_id, mac)
    achado = None
    with fsdb.locked(d):
        abertos = fsdb.read_json(d / "alerts.json", []) or []
        restantes = []
        for a in abertos:
            if a.get("id") == alert_id and achado is None:
                achado = a
            else:
                restantes.append(a)
        if achado is not None:
            fsdb.write_json(d / "alerts.json", restantes)
    if achado is None:
        return None
    achado = {**achado, "dismissed_at": time.time(), "dismissed_by": by}
    append_capped(
        d / "alerts.log",
        json.dumps({"event": "dismissed", **achado}, ensure_ascii=False),
        cap=HISTORICO,
    )
    return achado


def dismiss_all(image_id: str, mac: str, by: str) -> list[dict]:
    return [
        d
        for a in list(open_alerts(image_id, mac))
        if (d := dismiss(image_id, mac, a["id"], by)) is not None
    ]


def list_open(image_id: str) -> list[dict]:
    """Todos os alertas abertos da sede, do mais recente para o mais antigo."""
    todos = []
    for mac in list_macs(image_id):
        todos += open_alerts(image_id, mac)
    return sorted(todos, key=lambda a: a.get("at", 0), reverse=True)


def history(image_id: str, mac: str, linhas: int = 200) -> list[dict]:
    p = machine_dir(image_id, mac) / "alerts.log"
    if not p.is_file():
        return []
    out = []
    for linha in p.read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:]:
        try:
            out.append(json.loads(linha))
        except ValueError:
            continue
    return out
