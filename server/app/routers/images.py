"""CRUD de imagens (admin) + bulk + templates."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .. import auth
from ..models import BulkRequest, ImageCreate, ImagePatch, TemplateLayers
from ..services import seeders, store

router = APIRouter(prefix="/api/v1")


@router.post("/images", status_code=201)
async def create_image(body: ImageCreate, p=Depends(auth.require_admin)) -> dict:
    try:
        return store.create_image(
            body.id,
            body.fullname,
            body.template,
            unlocked=body.unlocked,
            extra={"wallpaper_locked": bool(body.wallpaper_locked)} if body.wallpaper_locked else None,
        )
    except store.ImageError as e:
        raise HTTPException(400, str(e))


@router.post("/images/bulk")
async def bulk_create(
    request: Request,
    format: str = Query("json", pattern="^(json|csv)$"),
    p=Depends(auth.require_admin),
):
    """Criação em massa. Aceita JSON {rows:[{id,fullname,template}...]} ou
    corpo `text/tab-separated-values` com linhas `id<TAB>fullname<TAB>template`.
    Com ?format=csv devolve as credenciais em CSV para distribuir."""
    ctype = request.headers.get("content-type", "")
    rows: list[dict]
    if "json" in ctype:
        body = BulkRequest.model_validate(await request.json())
        rows = [r.model_dump() for r in body.rows]
    else:
        text = (await request.body()).decode()
        rows = []
        default_template = store.list_templates()[0] if store.list_templates() else ""
        for ln, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                raise HTTPException(400, f"linha {ln}: esperado id<TAB>fullname[<TAB>template]")
            rows.append(
                {
                    "id": parts[0].strip(),
                    "fullname": parts[1].strip(),
                    "template": (parts[2].strip() if len(parts) > 2 else default_template),
                    "unlocked": False,
                }
            )

    results = []
    for row in rows:
        try:
            created = store.create_image(
                row["id"], row["fullname"], row["template"], unlocked=row.get("unlocked", False)
            )
            results.append({"ok": True, **created})
        except store.ImageError as e:
            results.append({"ok": False, "id": row.get("id", "?"), "error": str(e)})

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "ok", "token", "machine_key", "boot_key", "configureitor_url", "error"])
        for r in results:
            w.writerow(
                [
                    r.get("id", ""),
                    r["ok"],
                    r.get("token", ""),
                    r.get("machine_key", ""),
                    r.get("boot_key", ""),
                    r.get("configureitor_url", ""),
                    r.get("error", ""),
                ]
            )
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    return {"results": results}


@router.get("/images")
async def list_images(prefix: str = "", p=Depends(auth.require_admin)) -> dict:
    return {"images": store.list_images(prefix)}


@router.get("/images/{image}")
async def get_image(image: str, p=Depends(auth.require_image_access())) -> dict:
    return store.get_image(image) or {}


@router.patch("/images/{image}")
async def patch_image(image: str, body: ImagePatch, p=Depends(auth.require_admin)) -> dict:
    if not store.image_exists(image):
        raise HTTPException(404, "imagem não existe")
    try:
        return store.patch_image(image, body.model_dump())
    except store.ImageError as e:
        raise HTTPException(400, str(e))


@router.delete("/images/{image}", status_code=204)
async def delete_image(image: str, p=Depends(auth.require_admin)) -> None:
    if not store.image_exists(image):
        raise HTTPException(404, "imagem não existe")
    store.delete_image(image)


@router.post("/images/{image}/token/rotate")
async def rotate_token(image: str, p=Depends(auth.require_admin)) -> dict:
    if not store.image_exists(image):
        raise HTTPException(404, "imagem não existe")
    return {"token": store.rotate_token(image)}


@router.get("/images/{image}/credentials")
async def get_credentials(image: str, p=Depends(auth.require_admin)) -> dict:
    """Token, chaves e links prontos da imagem — para o admin entregar ao
    coordenador sem precisar rotacionar nada (o que invalidaria links já
    distribuídos)."""
    if not store.image_exists(image):
        raise HTTPException(404, "imagem não existe")
    return store.credentials(image)


@router.get("/images/{image}/boot-key")
async def get_boot_key(image: str, p=Depends(auth.require_admin)) -> dict:
    """Chave que vai no nutellaboot.conf do pendrive desta imagem."""
    if not store.image_exists(image):
        raise HTTPException(404, "imagem não existe")
    return {"boot_key": store.boot_key(image)}


@router.post("/images/{image}/boot-key/rotate")
async def rotate_boot_key(image: str, p=Depends(auth.require_admin)) -> dict:
    """Troca a chave de boot. Depois disso, os pendrives daquela imagem
    precisam ter o nutellaboot.conf atualizado — senão param de bootar."""
    if not store.image_exists(image):
        raise HTTPException(404, "imagem não existe")
    return {"boot_key": store.rotate_boot_key(image)}


@router.get("/images/{image}/seeders")
async def list_seeders(image: str, p=Depends(auth.require_image_access())) -> dict:
    return {"seeders": seeders.detail(image)}


@router.delete("/images/{image}/seeders/{ip}", status_code=204)
async def remove_seeder(image: str, ip: str, p=Depends(auth.require_image_access())) -> None:
    seeders.leave(image, ip)


@router.get("/templates")
async def list_templates(p=Depends(auth.require_admin)) -> dict:
    return {
        "templates": [
            {"name": n, "public": store.template_is_public(n)} for n in store.list_templates()
        ]
    }


@router.get("/templates/{name}/schema")
async def get_template_schema(name: str, p=Depends(auth.require_admin)) -> dict:
    """Campos do template com o estado do cadeado — alimenta a tela onde o
    admin escolhe o que as sedes podem ou não mudar."""
    if not store.template_exists(name):
        raise HTTPException(404, "template não existe")
    schema = store.get_schema(name)
    return {
        "name": name,
        "fields": [
            {
                "key": f["key"],
                "type": f.get("type"),
                "label": f.get("label"),
                "locked": bool(f.get("locked")),
            }
            for f in schema.get("fields", [])
        ],
    }


@router.put("/templates/{name}/schema/locks")
async def put_schema_locks(name: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """Liga/desliga o cadeado de campos. Vale para as imagens Oficiais deste
    template (as Livres continuam editando tudo)."""
    if not store.template_exists(name):
        raise HTTPException(404, "template não existe")
    locks = body.get("locks")
    if not isinstance(locks, dict) or not locks:
        raise HTTPException(400, "esperava {locks: {CAMPO: true|false}}")
    try:
        store.set_schema_locks(name, locks)
    except store.ImageError as e:
        raise HTTPException(400, str(e))
    return await get_template_schema(name, p)


@router.patch("/templates/{name}")
async def patch_template(name: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """Marca um template como público (disponível para criação por convite) e
    ajusta a descrição. Templates de prova bloqueados ficam privados."""
    if not store.template_exists(name):
        raise HTTPException(404, "template não existe")
    store.set_template_meta(
        name, public=body.get("public"), description=body.get("description")
    )
    return {"name": name, "public": store.template_is_public(name)}


@router.get("/templates/{name}")
async def get_template(name: str, p=Depends(auth.require_admin)) -> dict:
    tpl = store.get_template(name)
    if tpl is None:
        raise HTTPException(404, "template não existe")
    return tpl


@router.put("/templates/{name}/layers")
async def put_template_layers(
    name: str, body: TemplateLayers, p=Depends(auth.require_admin)
) -> dict:
    if not store.template_exists(name):
        raise HTTPException(404, "template não existe")
    for layer in body.layers:
        if not {"md5", "file"} <= set(layer):
            raise HTTPException(400, "cada camada precisa de md5 e file")
    store.set_template_layers(name, body.layers)
    return {"ok": True, "layers": len(body.layers)}
