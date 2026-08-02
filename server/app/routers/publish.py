"""Publicação de arquivos grandes no servidor de arquivos — lado admin."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .. import auth
from ..services import publish

router = APIRouter(prefix="/api/v1")


@router.get("/publish")
async def list_publish(p=Depends(auth.require_admin)) -> dict:
    c = publish.conf()
    return {
        "enabled": c["enabled"],
        "host": c["host"],
        "paths": c["paths"],
        "base_urls": c["base_urls"],
        "files": publish.list_state(),
    }


@router.post("/publish/retry")
async def retry_publish(p=Depends(auth.require_admin)) -> dict:
    resultados = publish.retry_failed()
    return {
        "retried": len(resultados),
        "ok": len([r for r in resultados if r.get("status") == "done"]),
        "files": resultados,
    }


@router.post("/publish/file")
async def publish_one(body: dict, p=Depends(auth.require_admin)) -> dict:
    """Publica um arquivo já presente na máquina de gestão. Aceita só o nome
    (resolvido em data/blobs ou data/usb) — nunca um caminho arbitrário."""
    filename = Path(str(body.get("file", ""))).name
    kind = str(body.get("kind", "layers"))
    if kind not in ("layers", "usb"):
        raise HTTPException(400, "kind deve ser 'layers' ou 'usb'")
    if not filename:
        raise HTTPException(400, "informe o arquivo")
    local = publish.local_path(filename, kind)
    if not local.is_file():
        raise HTTPException(404, f"arquivo não encontrado em {local.parent}")
    return publish.publish_file(local, kind)
