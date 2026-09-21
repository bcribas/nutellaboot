"""O que foi feito com as credenciais, por quem e de onde.

Criar e revogar chave é o tipo de coisa que se quer reconstituir depois. Uma
linha JSON por ato, em `data/audit.jsonl`, com teto. Nunca entra aqui um
segredo: nem chave, nem código de convite (o dono de um sub-admin é
`invite:<CÓDIGO>`, então ele vai pela referência curta e pelo rótulo).
"""

from __future__ import annotations

import json
import time

from ..settings import settings
from . import logcap

TETO = 512 * 1024


def _caminho():
    return settings.data_root / "audit.jsonl"


def registrar(p, request, action: str, target: str = "", detail: dict | None = None) -> None:
    from . import ownership, ratelimit

    ator = getattr(p, "name", "") or ""
    if getattr(p, "kind", "") == "subadmin":
        ator = ownership.owner_ref(ator)
    linha = {
        "at": int(time.time()),
        "actor_kind": getattr(p, "kind", "") or "anonymous",
        "actor": ator,
        "ip": ratelimit.client_ip(request) if request is not None else "",
        "action": action,
        "target": target,
        "detail": detail or {},
    }
    logcap.append_capped(_caminho(), json.dumps(linha, ensure_ascii=False), TETO)


def ler(n: int = 200) -> list[dict]:
    caminho = _caminho()
    if not caminho.is_file():
        return []
    out = []
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
        try:
            out.append(json.loads(linha))
        except ValueError:
            continue
    return out[::-1]  # o mais recente primeiro
