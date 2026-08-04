"""Configuração da imagem (configureitor) e wallpaper."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from .. import auth
from ..services import config as cfg
from ..services import store, webhook_push
from ..services import wallpaper as wp
from ..services.notify import notify

router = APIRouter(prefix="/api/v1")


def _check_wallpaper_editable(image: str, p) -> None:
    """Wallpaper travado é decisão da organização (como os campos `locked`):
    só a administração troca.

    A trava pode vir do MODELO (vale para todas as sedes dele, e é o caminho
    normal) ou da própria sede (que os convites emitem por imagem)."""
    if wp.travado(image) and p.kind != "admin":
        raise HTTPException(400, "o papel de parede desta imagem foi definido pela organização")


@router.get("/site-images/{image}/config")
async def get_config(image: str, p=Depends(auth.require_image_access())) -> dict:
    info = store.get_site_image(image) or {}
    achado = wp.efetivo(image)
    # com `origin`: um papel de parede que a pessoa não reconhece e não
    # consegue trocar, sem dizer de onde veio, vira chamado de suporte
    wallpaper = achado[1] if achado else None
    can_edit_locked = p.kind == "admin" or bool(info.get("unlocked"))
    return {
        "image": {
            "id": image,
            "fullname": info.get("fullname", ""),
            "model": info.get("model", ""),
            "unlocked": bool(info.get("unlocked")),
        },
        "schema": cfg.schema_for(image),
        "values": cfg.effective_values(image),
        "wallpaper": wallpaper,
        "can_edit_locked": can_edit_locked,
        # wallpaper travado: definido pela organização (no modelo ou na
        # própria sede), o dono não troca
        "can_edit_wallpaper": p.kind == "admin" or not wp.travado(image),
    }


@router.put("/site-images/{image}/config")
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
    # o evento existia no catálogo desde o começo e nunca era emitido: quem
    # inscrevesse um webhook em config.updated não recebia nada
    notify.publish(image, {"event": "config.updated", "data": {"keys": sorted(applied)}, "at": time.time()})
    webhook_push.emit(image, "config.updated", {"keys": sorted(applied)})
    return {"ok": True, "values": applied}


@router.get("/site-images/{image}/wallpaper")
async def get_wallpaper(image: str, request: Request, tk: str = Query("")):
    """O arquivo em si, para a prévia do configureitor.

    `<img src>` não manda cabeçalho: aceita o token da imagem em `?tk=` ou o
    cookie de sessão SEM exigir `X-NB-Console` — mesmo desenho, e mesma razão,
    do SSE em `machines.py`. É GET, não muda estado, e sem CORS uma página de
    outro site não lê a resposta.

    A tela apontava para `/boot/v3/{id}/wallpaper`, que pede a chave de boot —
    credencial que a sede não tem e que um `<img>` não conseguiria mandar. A
    prévia nunca carregou em imagem nenhuma.
    """
    p = auth.principal_de_link(request, tk, image)
    if p is None or not p.can_see_image(image):
        raise HTTPException(401, "credencial ausente ou inválida")

    achado = wp.efetivo(image)
    if not achado:
        raise HTTPException(404, "sem wallpaper")
    caminho, meta = achado
    return FileResponse(
        caminho,
        media_type=meta.get("content_type", "image/png"),
        headers={"ETag": f'"{meta["md5"]}"'},
    )


@router.put("/site-images/{image}/wallpaper")
async def put_wallpaper(
    image: str,
    file: UploadFile = File(...),
    p=Depends(auth.require_image_access(service_scope="config:write")),
) -> dict:
    """Recebe o arquivo (o nb2 pedia uma URL, baixava no servidor na hora de
    salvar e derrubava o salvamento inteiro quando a URL falhava)."""
    _check_wallpaper_editable(image, p)
    data = await file.read(wp.MAX_BYTES + 1)
    try:
        return wp.gravar(store.site_image_dir(image), data, file.filename or "")
    except wp.WallpaperError as e:
        raise HTTPException(413 if "maior que" in str(e) else 400, str(e))


@router.delete("/site-images/{image}/wallpaper", status_code=204)
async def delete_wallpaper(
    image: str, p=Depends(auth.require_image_access(service_scope="config:write"))
) -> None:
    _check_wallpaper_editable(image, p)
    # apaga só o DA SEDE; se o modelo tiver um, a sede volta a usar aquele
    wp.apagar(store.site_image_dir(image))
