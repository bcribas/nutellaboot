"""CRUD de site-images: criação (individual e em massa), credenciais e
semeadores. Os modelos ficam em routers/models.py."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .. import auth
from ..models import BulkRequest, SiteImageCreate, SiteImagePatch
from ..services import ownership, seeders, store, usb

router = APIRouter(prefix="/api/v1")


@router.post("/site-images", status_code=201)
async def create_image(body: SiteImageCreate, p=Depends(auth.require_console)) -> dict:
    erro = ownership.check_can_create(p, "site_images", body.id)
    if erro:
        raise HTTPException(403, erro)
    if not ownership.can_use_model(p, body.model):
        raise HTTPException(404, "modelo não existe")
    try:
        criada = store.create_site_image(
            body.id,
            body.fullname,
            body.model,
            unlocked=body.unlocked,
            owner=p.owner,
            extra={"wallpaper_locked": bool(body.wallpaper_locked)} if body.wallpaper_locked else None,
        )
    except store.ImageError as e:
        raise HTTPException(400, str(e))
    # o pendrive é o único jeito de a máquina ligar: começa a ser gerado junto
    # com a imagem, para o cartão de credenciais já mostrar o link
    usb.agendar(criada["id"])
    return criada


@router.post("/site-images/bulk")
async def bulk_create(
    request: Request,
    format: str = Query("json", pattern="^(json|csv)$"),
    p=Depends(auth.require_admin),
):
    """Criação em massa. Aceita JSON {rows:[{id,fullname,model}...]} ou
    corpo `text/tab-separated-values` com linhas `id<TAB>fullname<TAB>model`.
    Com ?format=csv devolve as credenciais em CSV para distribuir."""
    ctype = request.headers.get("content-type", "")
    rows: list[dict]
    if "json" in ctype:
        body = BulkRequest.model_validate(await request.json())
        rows = [r.model_dump() for r in body.rows]
    else:
        text = (await request.body()).decode()
        rows = []
        modelo_padrao = store.list_models()[0] if store.list_models() else ""
        for ln, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                raise HTTPException(400, f"linha {ln}: esperado id<TAB>fullname[<TAB>model]")
            rows.append(
                {
                    "id": parts[0].strip(),
                    "fullname": parts[1].strip(),
                    "model": (parts[2].strip() if len(parts) > 2 else modelo_padrao),
                    "unlocked": False,
                }
            )

    results = []
    for row in rows:
        try:
            created = store.create_site_image(
                row["id"],
                row["fullname"],
                row["model"],
                unlocked=row.get("unlocked", False),
                extra=({"wallpaper_locked": True} if row.get("wallpaper_locked") else None),
            )
            usb.agendar(created["id"])
            results.append({"ok": True, **created})
        except store.ImageError as e:
            results.append({"ok": False, "id": row.get("id", "?"), "error": str(e)})

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        # as DUAS telas da sede: são os dois links que se entregam ao
        # coordenador, e o CSV é o que se distribui depois de criar 50 sedes.
        # Só o configureitor saía daqui, então metade do que a criação em massa
        # produziu ficava só no JSON.
        colunas = [
            "id",
            "ok",
            "token",
            "machine_key",
            "boot_key",
            "configureitor_url",
            "hotconfig_url",
            "error",
        ]
        w.writerow(colunas)
        for r in results:
            w.writerow([r.get("ok", "") if c == "ok" else r.get(c, "") for c in colunas])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    return {"results": results}


@router.get("/site-images")
async def list_images(prefix: str = "", p=Depends(auth.require_console)) -> dict:
    return {"images": ownership.visible_site_images(p, prefix)}


@router.get("/site-images/{image}")
async def get_site_image(image: str, p=Depends(auth.require_image_access())) -> dict:
    return store.get_site_image(image) or {}


@router.patch("/site-images/{image}")
async def patch_image(image: str, body: SiteImagePatch, p=Depends(auth.require_console)) -> dict:
    _minha(p, image)
    campos = body.model_dump()

    if campos.get("model") and not ownership.can_use_model(p, campos["model"]):
        # sem esta checagem, um sub-admin apontaria a imagem dele para um
        # modelo privado da administração e levaria as camadas dele junto
        raise HTTPException(404, "modelo não existe")

    if campos.get("unlocked") is not None and p.kind != "admin":
        # o perfil (Oficial × Livre) vem do convite: deixar o dono virar a
        # chave sozinho anularia todos os cadeados de uma imagem de prova
        raise HTTPException(403, "só a administração muda o perfil da imagem")

    if campos.get("build_quota") is not None and p.kind != "admin":
        # cota que o próprio dono aumenta não é cota
        raise HTTPException(403, "só a administração muda a cota de builds")

    if campos.get("wallpaper_locked") is not None and p.kind != "admin":
        # o mesmo portão do `unlocked`: a trava do wallpaper é decisão da
        # organização (o convite a fixa na criação), e o dono podia desligá-la
        # por aqui — o único campo de cadeado sem portão
        raise HTTPException(403, "só a administração muda a trava do wallpaper")

    try:
        return store.patch_site_image(image, campos)
    except store.ImageError as e:
        raise HTTPException(400, str(e))


@router.delete("/site-images/{image}", status_code=204)
async def delete_image(image: str, p=Depends(auth.require_console)) -> None:
    _minha(p, image)
    store.delete_site_image(image)


@router.post("/site-images/{image}/token/rotate")
async def rotate_token(image: str, p=Depends(auth.require_console)) -> dict:
    _minha(p, image)
    return {"token": store.rotate_token(image)}


@router.get("/site-images/{image}/credentials")
async def get_credentials(image: str, p=Depends(auth.require_console)) -> dict:
    """Token, chaves e links prontos da imagem — para o admin entregar ao
    coordenador sem precisar rotacionar nada (o que invalidaria links já
    distribuídos)."""
    _minha(p, image)
    return store.credentials(image)


@router.get("/site-images/{image}/boot-key")
async def get_boot_key(image: str, p=Depends(auth.require_console)) -> dict:
    """Chave que vai no nutellaboot.conf do pendrive desta imagem."""
    _minha(p, image)
    return {"boot_key": store.boot_key(image)}


@router.post("/site-images/{image}/boot-key/rotate")
async def rotate_boot_key(image: str, p=Depends(auth.require_console)) -> dict:
    """Troca a chave de boot. Depois disso, os pendrives daquela imagem
    precisam ter o nutellaboot.conf atualizado — senão param de bootar."""
    _minha(p, image)
    return {"boot_key": store.rotate_boot_key(image)}


@router.get("/site-images/{image}/seeders")
async def list_seeders(image: str, p=Depends(auth.require_image_access())) -> dict:
    return {"seeders": seeders.detail(image)}


@router.delete("/site-images/{image}/seeders/{ip}", status_code=204)
async def remove_seeder(image: str, ip: str, p=Depends(auth.require_image_access())) -> None:
    seeders.leave(image, ip)


def _minha(p, image: str) -> None:
    """404 e não 403 quando a imagem é de outro dono: um 403 confirmaria que o
    nome existe, e nomes são livres por ordem de chegada."""
    if not ownership.can_manage_site_image(p, image):
        raise HTTPException(404, "imagem não existe")
