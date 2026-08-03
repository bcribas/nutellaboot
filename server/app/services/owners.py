"""Sub-admins: quem entrou por convite e tem console próprio.

O registro do sub-admin vive em `data/owners/<slug>.json`, **separado do
convite**. Isso é de propósito: o campo `owner` gravado em cada modelo e
site-image aponta para este registro, então apagar o convite (que é o que
revoga o acesso) não deixa objetos apontando para o nada. O convite continua
sendo a credencial; o registro é a identidade.

Cotas são lidas do convite e o uso é **contado varrendo o disco**, nunca por
contador incrementado: contador erra quando alguém apaga um objeto por fora, e
o erro só aparece quando a cota trava sem motivo.
"""

from __future__ import annotations

import re
import time

from .. import fsdb
from ..settings import settings
from . import invites

DEFAULT_MAX_MODELS = 2


def owner_id(code: str) -> str:
    return f"invite:{invites.normalize(code)}"


def is_owner_id(valor: str) -> bool:
    return isinstance(valor, str) and valor.startswith("invite:")


def code_of(owner: str) -> str:
    return owner.split(":", 1)[1] if is_owner_id(owner) else ""


def _slug(owner: str) -> str:
    # o código já vem de um alfabeto restrito, mas o nome vira arquivo:
    # sanitizar é barato e evita qualquer travessia de caminho
    return re.sub(r"[^A-Za-z0-9_-]", "_", owner.replace(":", "_"))


def _path(owner: str):
    return settings.data_root / "owners" / f"{_slug(owner)}.json"


def get(owner: str) -> dict | None:
    return fsdb.read_json(_path(owner))


def ensure(code: str, *, label: str = "") -> dict:
    """Cria o registro na primeira vez que o código é usado, ou devolve o que
    já existe (atualizando o último acesso)."""
    oid = owner_id(code)
    inv = invites.get(code) or {}
    with fsdb.locked(settings.data_root / "owners"):
        rec = fsdb.read_json(_path(oid))
        if rec is None:
            rec = {
                "id": oid,
                "kind": "subadmin",
                "label": label or inv.get("label") or inv.get("note") or "",
                "created_at": time.time(),
            }
        rec["last_seen"] = time.time()
        fsdb.write_json(_path(oid), rec, mode=0o600)
    return rec


def disabled(owner: str) -> bool:
    """Suspensão sem apagar o convite — mantém o histórico e o dono dos
    objetos, só corta o acesso ao console."""
    return bool((get(owner) or {}).get("disabled"))


def set_disabled(owner: str, valor: bool) -> dict:
    with fsdb.locked(settings.data_root / "owners"):
        rec = fsdb.read_json(_path(owner)) or {"id": owner, "kind": "subadmin"}
        rec["disabled"] = bool(valor)
        fsdb.write_json(_path(owner), rec, mode=0o600)
    return rec


def quotas(owner: str) -> dict:
    """Tetos deste sub-admin, vindos do convite (o registro pode sobrescrever).
    `None` em qualquer campo significa sem limite."""
    inv = invites.get(code_of(owner)) or {}
    rec = get(owner) or {}
    base = {
        "models": int(inv.get("max_models", DEFAULT_MAX_MODELS)),
        "site_images": int(inv.get("max_images", invites.DEFAULT_MAX_IMAGES)),
        "builds": int(inv.get("build_quota", invites.DEFAULT_BUILD_QUOTA)),
    }
    base.update({k: v for k, v in (rec.get("quotas") or {}).items() if k in base})
    return base


def usage(owner: str) -> dict:
    """Uso atual, varrendo o disco."""
    from . import store

    return {
        "models": len(store.list_models(owner=owner)),
        "site_images": len(store.list_site_images(owner=owner)),
    }


def list_all() -> list[dict]:
    base = settings.data_root / "owners"
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.iterdir()):
        if p.suffix != ".json":
            continue
        rec = fsdb.read_json(p)
        if not rec:
            continue
        oid = rec.get("id", "")
        ok, motivo = invites.is_valid_for_console(code_of(oid))
        out.append(
            {
                **rec,
                "quotas": quotas(oid),
                "usage": usage(oid),
                "console_ok": ok,
                "console_reason": motivo,
            }
        )
    return out
