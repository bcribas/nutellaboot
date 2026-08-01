"""Configuração da imagem (configureitor) e wallpaper."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import auth, fsdb
from ..services import config as cfg
from ..services import store

router = APIRouter(prefix="/api/v1")

MAX_WALLPAPER_BYTES = 12 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


@router.get("/images/{image}/config")
async def get_config(image: str, p=Depends(auth.require_image_access())) -> dict:
    info = store.get_image(image) or {}
    wallpaper = fsdb.read_json(store.image_dir(image) / "wallpaper.json")
    return {
        "image": {
            "id": image,
            "fullname": info.get("fullname", ""),
            "template": info.get("template", ""),
            "unlocked": bool(info.get("unlocked")),
        },
        "schema": cfg.schema_for(image),
        "values": cfg.effective_values(image),
        "wallpaper": wallpaper,
        "can_edit_locked": p.kind == "admin" or bool(info.get("unlocked")),
    }


@router.put("/images/{image}/config")
async def put_config(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="config:write"))
) -> dict:
    values = body.get("values", body)
    if not isinstance(values, dict):
        raise HTTPException(400, "esperava um objeto com os valores")
    try:
        applied = cfg.write_values(image, values, is_admin=(p.kind == "admin"))
    except cfg.ConfigError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "values": applied}


@router.put("/images/{image}/wallpaper")
async def put_wallpaper(
    image: str,
    file: UploadFile = File(...),
    p=Depends(auth.require_image_access(service_scope="config:write")),
) -> dict:
    """Recebe o arquivo (o nb2 pedia uma URL, baixava no servidor na hora de
    salvar e derrubava o salvamento inteiro quando a URL falhava)."""
    data = await file.read(MAX_WALLPAPER_BYTES + 1)
    if len(data) > MAX_WALLPAPER_BYTES:
        raise HTTPException(413, f"arquivo maior que {MAX_WALLPAPER_BYTES // 2**20} MB")
    if not data:
        raise HTTPException(400, "arquivo vazio")
    if not (data.startswith(PNG_MAGIC) or data.startswith(JPEG_MAGIC)):
        raise HTTPException(400, "formato não reconhecido: envie PNG ou JPEG")

    md5 = hashlib.md5(data).hexdigest()
    d = store.image_dir(image)
    with fsdb.locked(d):
        (d / "wallpaper.png").write_bytes(data)
        meta = {
            "md5": md5,
            "size": len(data),
            "filename": file.filename,
            "content_type": "image/png" if data.startswith(PNG_MAGIC) else "image/jpeg",
        }
        fsdb.write_json(d / "wallpaper.json", meta)
    return meta


@router.delete("/images/{image}/wallpaper", status_code=204)
async def delete_wallpaper(
    image: str, p=Depends(auth.require_image_access(service_scope="config:write"))
) -> None:
    d = store.image_dir(image)
    with fsdb.locked(d):
        (d / "wallpaper.png").unlink(missing_ok=True)
        (d / "wallpaper.json").unlink(missing_ok=True)
