"""CRUD de site-images: criação (individual e em massa), credenciais e
semeadores. Os modelos ficam em routers/models.py."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .. import auth
from ..models import BulkRequest, SiteImageCreate, SiteImagePatch
from ..services import audit, eventos, fleet_views, invites, owners, ownership, presence, seeders, store, usb

router = APIRouter(prefix="/api/v1")


@router.post("/site-images", status_code=201)
async def create_image(body: SiteImageCreate, p=Depends(auth.require_console)) -> dict:
    erro = ownership.check_can_create(p, "site_images", body.id)
    if erro:
        raise HTTPException(403, erro)
    if not ownership.can_use_model(p, body.model):
        raise HTTPException(404, "modelo não existe")
    extra = {}
    unlocked = body.unlocked
    wallpaper_locked = body.wallpaper_locked
    if p.kind != "admin":
        # O convite decide, como na auto-criação (`routers/public.py`). O PATCH
        # já proibia o sub-admin de mudar perfil e trava; a criação deixava
        # escolher, e uma imagem Livre ignora todos os cadeados do modelo.
        # Oficial (mais restrito que o convite) continua sendo escolha dele.
        inv = invites.get(owners.code_of(p.owner)) or {}
        if unlocked and not bool(inv.get("unlocked", True)):
            raise HTTPException(403, "o convite só permite imagens Oficiais")
        trava = bool(inv.get("wallpaper_locked", False))
        if "wallpaper_locked" in body.model_fields_set and wallpaper_locked != trava:
            raise HTTPException(403, "a trava do papel de parede vem do convite")
        wallpaper_locked = trava
        # a cota de construções por imagem também: sem ela, a imagem criada
        # pelo console ficava com cota 0 e a do /criar/ com a do convite
        extra["build_quota"] = int(inv.get("build_quota", invites.DEFAULT_BUILD_QUOTA))
    if wallpaper_locked:
        extra["wallpaper_locked"] = True
    if body.dashboard_hidden:
        if p.kind != "admin":
            # o PATCH já tinha este portão; a criação não
            raise HTTPException(403, "só a administração oculta uma imagem do dashboard")
        extra["dashboard_hidden"] = True
    if body.country:
        extra["country"] = body.country
    try:
        criada = store.create_site_image(
            body.id,
            body.fullname,
            body.model,
            unlocked=unlocked,
            owner=p.owner,
            extra=extra or None,
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
def list_images(prefix: str = "", p=Depends(auth.require_console_or_service)) -> dict:
    # `def`: para a chave de serviço conta as máquinas de cada sede (disco)
    if p.kind == "service":
        return {"images": ownership.imagens_para_servico(p, prefix)}
    # com o dono de cada uma, do jeito que pode ser mostrado (rótulo, e não o
    # código do convite): a lista do console não dizia de quem era a imagem
    return {
        "images": [
            {**i, **ownership.owner_publico(str(i.get("owner") or "admin"))}
            for i in ownership.visible_site_images(p, prefix)
        ]
    }


@router.get("/site-images/{image}")
async def get_site_image(
    image: str, p=Depends(auth.require_image_access(service_scope=auth.QUALQUER))
) -> dict:
    # Qualquer chave de serviço cujo glob cubra a imagem, sem escopo específico:
    # ela já conhece o id (whoami e a lista o dão) e aqui não há telemetria.
    # Exigir `machines:read` devolveria o 403 a toda chave só de roster.
    if p.kind == "service":
        return ownership.imagem_para_servico(store.get_site_image(image) or {}, completa=True)
    # nunca o image.json cru: o `owner` de uma sede criada por convite é o
    # código do convite, e esta rota atende o token da sede (o hotconfig a lê)
    return ownership.site_image_para(p, store.get_site_image(image) or {})


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

    if campos.get("dashboard_hidden") is not None and p.kind != "admin":
        # tirar a própria sede do placar da organização não é decisão do dono
        raise HTTPException(403, "só a administração oculta uma imagem do dashboard")

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
    # senão o vigia anunciaria `machine.offline` de uma sede que não existe mais
    presence.esquecer_imagem(image)
    fleet_views.purge_image(image)


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


@router.post("/site-images/{image}/machine-key/rotate")
def rotate_machine_key(image: str, body: dict, request: Request, p=Depends(auth.require_console)) -> dict:
    """Troca a chave de máquina da sede (era a única credencial sem rotação).

    `grace_hours` (0 a 72, padrão 12): por quanto tempo a chave ANTIGA ainda
    vale. A máquina só recebe a chave no boot; sem carência, quem está ligada
    para de reportar e de receber ordem na hora, e uma máquina travada não
    receberia o destravar. Por isso `grace_hours: 0` (chave vazada) é recusado
    enquanto houver máquina travada, a não ser com `force`."""
    _minha(p, image)
    horas = body.get("grace_hours", 12)
    if not isinstance(horas, (int, float)) or isinstance(horas, bool) or not 0 <= horas <= 72:
        raise HTTPException(400, "grace_hours vai de 0 a 72")
    from ..services import machines as m

    maquinas = m.list_machines(image)
    travadas = sum(1 for x in maquinas if (x.get("lock") or {}).get("locked"))
    ligadas = sum(1 for x in maquinas if x.get("online"))
    if horas == 0 and travadas and not body.get("force"):
        raise HTTPException(
            409,
            f"{travadas} máquina(s) travada(s) ficariam sem receber o destravar: "
            "destrave antes, use carência, ou repita com force",
        )
    r = store.rotate_machine_key(image, float(horas))
    audit.registrar(p, request, "machine_key.rotated", image, {"grace_hours": horas, "online": ligadas})
    return {**r, "online": ligadas, "locked": travadas}


@router.get("/site-images/{image}/seeders")
async def list_seeders(image: str, p=Depends(auth.require_image_access())) -> dict:
    return {"seeders": seeders.detail(image)}


@router.delete("/site-images/{image}/seeders/{ip}", status_code=204)
async def remove_seeder(image: str, ip: str, p=Depends(auth.require_image_access())) -> None:
    """Libera o seeder: marca o tombstone e a máquina, ao ver `released=t` no
    heartbeat, sai do modo seed e termina o boot."""
    seeders.release(image, ip)
    eventos.publicar(image, "seeder.released", {"ip": ip})


def _minha(p, image: str) -> None:
    """404 e não 403 quando a imagem é de outro dono: um 403 confirmaria que o
    nome existe, e nomes são livres por ordem de chegada."""
    if not ownership.can_manage_site_image(p, image):
        raise HTTPException(404, "imagem não existe")
