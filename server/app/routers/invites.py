"""Códigos de convite e fila de pedidos — lado administração."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import auth
from ..services import invites, owners, requests, store

router = APIRouter(prefix="/api/v1")


@router.post("/invites", status_code=201)
async def create_invite(body: dict, p=Depends(auth.require_admin)) -> dict:
    model = body.get("model")
    if model and not store.model_exists(model):
        raise HTTPException(400, f"modelo '{model}' não existe")
    novos = invites.create(
        max_images=int(body.get("max_images", invites.DEFAULT_MAX_IMAGES)),
        max_models=int(body.get("max_models", owners.DEFAULT_MAX_MODELS)),
        build_quota=int(body.get("build_quota", invites.DEFAULT_BUILD_QUOTA)),
        model=model,
        expires_at=body.get("expires_at"),
        note=str(body.get("note", "")),
        label=str(body.get("label", "")),
        count=int(body.get("count", 1)),
        unlocked=bool(body.get("unlocked", True)),
        wallpaper_locked=bool(body.get("wallpaper_locked", False)),
    )
    return {"invites": novos}


@router.get("/invites")
async def list_invites(p=Depends(auth.require_admin)) -> dict:
    return {"invites": invites.list_all()}


@router.delete("/invites/{code}")
async def delete_invite(code: str, force: bool = False, p=Depends(auth.require_admin)) -> dict:
    """Apagar o convite derruba o console do sub-admin — o código É a
    credencial. Se já criou coisa, exige ?force=true e diz o que fica órfão,
    para ninguém tirar o acesso sem perceber."""
    oid = owners.owner_id(code)
    modelos = store.list_models(owner=oid)
    imagens = [i["id"] for i in store.list_site_images(owner=oid)]
    if (modelos or imagens) and not force:
        raise HTTPException(
            409,
            "este convite virou console de sub-admin; apagar tira o acesso a "
            f"{len(modelos)} modelo(s) e {len(imagens)} site-image(s). "
            "Prefira suspender (POST /owners/{id}/disable) ou repita com ?force=true",
        )
    invites.delete(code)
    return {"ok": True, "orphaned": {"models": modelos, "site_images": imagens}}


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
            model=body.get("model"),
            note=f"pedido {rid}: {req.get('wanted_name', '')}",
            label=str(req.get("wanted_name", "")),
            unlocked=bool(body.get("unlocked", True)),
        )[0]
        requests.set_status(rid, "approved", {"issued_code": code["code"]})
        return {"issued": code}

    # criar a imagem direto
    image_id = body.get("id") or req.get("wanted_name", "")
    model = body.get("model")
    if not model or not store.model_exists(model):
        raise HTTPException(400, "informe um modelo válido")
    try:
        created = store.create_site_image(
            image_id,
            body.get("fullname", req.get("wanted_name", "")),
            model,
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
