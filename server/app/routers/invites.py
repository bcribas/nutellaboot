"""Códigos de convite e fila de pedidos — lado administração."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import auth
from ..services import invites, requests, store

router = APIRouter(prefix="/api/v1")


@router.post("/invites", status_code=201)
async def create_invite(body: dict, p=Depends(auth.require_admin)) -> dict:
    template = body.get("template")
    if template and not store.template_exists(template):
        raise HTTPException(400, f"template '{template}' não existe")
    novos = invites.create(
        max_images=int(body.get("max_images", invites.DEFAULT_MAX_IMAGES)),
        build_quota=int(body.get("build_quota", invites.DEFAULT_BUILD_QUOTA)),
        template=template,
        expires_at=body.get("expires_at"),
        note=str(body.get("note", "")),
        count=int(body.get("count", 1)),
        unlocked=bool(body.get("unlocked", True)),
        wallpaper_locked=bool(body.get("wallpaper_locked", False)),
    )
    return {"invites": novos}


@router.get("/invites")
async def list_invites(p=Depends(auth.require_admin)) -> dict:
    return {"invites": invites.list_all()}


@router.delete("/invites/{code}", status_code=204)
async def delete_invite(code: str, p=Depends(auth.require_admin)) -> None:
    invites.delete(code)


# --- fila de pedidos (lado admin) ---


@router.get("/requests")
async def list_requests(p=Depends(auth.require_admin)) -> dict:
    return {"requests": requests.list_all()}


@router.post("/requests/{rid}/approve")
async def approve_request(rid: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    req = requests.get(rid)
    if req is None:
        raise HTTPException(404, "pedido não existe")

    # o admin escolhe: emitir um código para a pessoa se virar, ou já criar a
    # imagem e devolver as credenciais para repassar
    if body.get("action") == "issue_code":
        code = invites.create(
            max_images=int(body.get("max_images", 1)),
            build_quota=int(body.get("build_quota", invites.DEFAULT_BUILD_QUOTA)),
            template=body.get("template"),
            note=f"pedido {rid}: {req.get('wanted_name', '')}",
            unlocked=bool(body.get("unlocked", True)),
        )[0]
        requests.set_status(rid, "approved", {"issued_code": code["code"]})
        return {"issued": code}

    # criar a imagem direto
    image_id = body.get("id") or req.get("wanted_name", "")
    template = body.get("template")
    if not template or not store.template_exists(template):
        raise HTTPException(400, "informe um template válido")
    try:
        created = store.create_image(
            image_id,
            body.get("fullname", req.get("wanted_name", "")),
            template,
            unlocked=bool(body.get("unlocked", True)),
            extra={"self_service": True, "build_quota": int(body.get("build_quota", invites.DEFAULT_BUILD_QUOTA))},
        )
    except store.ImageError as e:
        raise HTTPException(400, str(e))
    requests.set_status(rid, "approved", {"created_image": image_id})
    return {"created": created}


@router.post("/requests/{rid}/reject", status_code=200)
async def reject_request(rid: str, body: dict | None = None, p=Depends(auth.require_admin)) -> dict:
    if requests.get(rid) is None:
        raise HTTPException(404, "pedido não existe")
    requests.set_status(rid, "rejected", {"reason": (body or {}).get("reason", "")})
    return {"ok": True}
