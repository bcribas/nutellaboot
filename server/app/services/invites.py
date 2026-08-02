"""Códigos de convite para criação de imagens por auto-atendimento.

O código é o segredo distribuído (não fica como hash, igual a token/boot.key):
quem o recebe cria a própria imagem sem precisar de aprovação, dentro da cota.

`data/invites.json` = {CODIGO: {max_images, used_images, expires_at,
template, build_quota, note, created_at}}.
"""

from __future__ import annotations

import secrets
import time

from .. import fsdb
from ..settings import settings

# alfabeto sem caracteres ambíguos (sem O/0, I/1, etc.) — o código é entregue
# por e-mail/mensagem e às vezes digitado à mão
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_MAX_IMAGES = 1
DEFAULT_BUILD_QUOTA = 5


def _path():
    return settings.data_root / "invites.json"


def _load() -> dict:
    return fsdb.read_json(_path(), {}) or {}


def normalize(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def _gen_code() -> str:
    grp = lambda: "".join(secrets.choice(_ALPHABET) for _ in range(4))  # noqa: E731
    return f"NB3-{grp()}-{grp()}"


def create(
    *,
    max_images: int = DEFAULT_MAX_IMAGES,
    build_quota: int = DEFAULT_BUILD_QUOTA,
    template: str | None = None,
    expires_at: float | None = None,
    note: str = "",
    count: int = 1,
    unlocked: bool = True,
    wallpaper_locked: bool = False,
) -> list[dict]:
    """Gera `count` códigos e devolve a lista (com o código em claro).

    `unlocked` define o perfil da imagem que o código vai criar: Livre (padrão
    — o dono edita tudo) ou Oficial (os campos obrigatórios do template ficam
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
                "used_images": [],
                "build_quota": int(build_quota),
                "template": template,
                "expires_at": expires_at,
                "note": note,
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
