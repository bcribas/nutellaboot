"""Códigos de convite para criação de imagens por auto-atendimento.

O código é o segredo distribuído (não fica como hash, igual a token/boot.key):
quem o recebe cria a própria imagem sem precisar de aprovação, dentro da cota.

`data/invites.json` = {CODIGO: {max_images, used_images, expires_at,
model, build_quota, note, created_at}}.
"""

from __future__ import annotations

import re
import secrets
import time

from .. import fsdb
from ..settings import settings

# alfabeto sem caracteres ambíguos (sem O/0, I/1, etc.) — o código é entregue
# por e-mail/mensagem e às vezes digitado à mão
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_MAX_IMAGES = 1
DEFAULT_BUILD_QUOTA = 5
# Três grupos = 60 bits de entropia. Os códigos antigos (dois grupos, 40 bits)
# continuam valendo, mas agora o código é credencial de console de longa
# duração, não mais um bilhete de uso único — 40 bits é pouco para isso.
GROUPS = 3


def _path():
    return settings.data_root / "invites.json"


def _load() -> dict:
    return fsdb.read_json(_path(), {}) or {}


def normalize(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def _gen_code() -> str:
    grp = lambda: "".join(secrets.choice(_ALPHABET) for _ in range(4))  # noqa: E731
    return "-".join(["NB3"] + [grp() for _ in range(GROUPS)])


CODE_RE = re.compile(r"^NB3(-[A-Z0-9]{4}){2,6}$")


def looks_like_code(valor: str) -> bool:
    """Só para decidir se vale a pena consultar o arquivo de convites ao
    autenticar — não afirma nada sobre validade."""
    return bool(CODE_RE.match(normalize(valor)))


def create(
    *,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_models: int = 2,
    build_quota: int = DEFAULT_BUILD_QUOTA,
    model: str | None = None,
    expires_at: float | None = None,
    note: str = "",
    label: str = "",
    count: int = 1,
    unlocked: bool = True,
    wallpaper_locked: bool = False,
) -> list[dict]:
    """Gera `count` códigos e devolve a lista (com o código em claro).

    `unlocked` define o perfil da imagem que o código vai criar: Livre (padrão
    — o dono edita tudo) ou Oficial (os campos obrigatórios do model ficam
    travados, como nas imagens de prova)."""
    novos = []
    with fsdb.locked(settings.data_root):
        data = _load()
        for _ in range(max(1, count)):
            code = _gen_code()
            while code in data:
                code = _gen_code()
            data[code] = {
                "max_images": int(max_images),
                "max_models": int(max_models),
                "used_images": [],
                "build_quota": int(build_quota),
                "model": model,
                "expires_at": expires_at,
                "note": note,
                "label": label or note,
                "unlocked": bool(unlocked),
                "wallpaper_locked": bool(wallpaper_locked),
                "created_at": time.time(),
            }
            novos.append({"code": code, **data[code]})
        fsdb.write_json(_path(), data, mode=0o600)
    return novos


def get(code: str) -> dict | None:
    return _load().get(normalize(code))


def is_valid(code: str) -> tuple[bool, str]:
    """(ok, motivo). Motivo só importa quando não ok."""
    inv = get(code)
    if inv is None:
        return False, "código inválido"
    if inv.get("expires_at") and time.time() > inv["expires_at"]:
        return False, "código expirado"
    if len(inv.get("used_images", [])) >= inv.get("max_images", 1):
        return False, "código já atingiu o limite de imagens"
    return True, ""


def is_valid_for_console(code: str) -> tuple[bool, str]:
    """Entrar no console é diferente de criar imagem: a cota esgotada não pode
    trancar o sub-admin para fora do que ele já tem. Só código inexistente,
    expirado ou revogado barra o acesso."""
    inv = get(code)
    if inv is None:
        return False, "código inválido"
    if inv.get("expires_at") and time.time() > inv["expires_at"]:
        return False, "código expirado"
    if inv.get("revoked"):
        return False, "código revogado"
    return True, ""


def set_fields(code: str, campos: dict) -> dict | None:
    """Ajusta cotas/rótulo/revogação de um convite já emitido."""
    permitidos = {
        "label",
        "note",
        "max_images",
        "max_models",
        "build_quota",
        "expires_at",
        "revoked",
        "model",
        "unlocked",
        "wallpaper_locked",
    }
    with fsdb.locked(settings.data_root):
        data = _load()
        inv = data.get(normalize(code))
        if inv is None:
            return None
        for k, v in campos.items():
            if k in permitidos:
                inv[k] = v
        fsdb.write_json(_path(), data, mode=0o600)
        return {"code": normalize(code), **inv}


def consume(code: str, image_id: str) -> None:
    """Registra uma imagem criada com este código (gasta uma unidade da cota)."""
    with fsdb.locked(settings.data_root):
        data = _load()
        inv = data.get(normalize(code))
        if inv is not None:
            inv.setdefault("used_images", []).append(image_id)
            fsdb.write_json(_path(), data, mode=0o600)


def list_all() -> list[dict]:
    return [
        {
            "code": c,
            **v,
            "used": len(v.get("used_images", [])),
            "remaining": max(0, v.get("max_images", 1) - len(v.get("used_images", []))),
        }
        for c, v in sorted(_load().items(), key=lambda kv: -kv[1].get("created_at", 0))
    ]


def delete(code: str) -> bool:
    with fsdb.locked(settings.data_root):
        data = _load()
        if normalize(code) in data:
            del data[normalize(code)]
            fsdb.write_json(_path(), data, mode=0o600)
            return True
    return False
