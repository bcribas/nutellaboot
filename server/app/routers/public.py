"""Rotas públicas de auto-atendimento: criar imagem com código de convite e
enviar pedido para a fila. Sem chave de admin, então tudo aqui é
rate-limited por IP e recusa nomes reservados."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..services import invites, owners, ratelimit, requests, store, usb
from ..settings import settings

router = APIRouter(prefix="/api/v1/public")

# Rajada curta permitida, depois ~1 a cada poucos segundos.
#
# Configurável no `data/server.json` porque o limite é POR IP e uma
# instituição inteira sai por um NAT só: cinco pessoas da mesma sede criando a
# imagem delas ao mesmo tempo é uso normal, não abuso. O padrão é apertado de
# propósito — quem precisa de mais, afrouxa sabendo o que está fazendo.
_CREATE = {"rate": 0.2, "burst": 5}
_REQUEST = {"rate": 0.1, "burst": 3}


def _cfg(escopo: str, padrao: dict) -> dict:
    from .. import fsdb

    server = fsdb.read_json(settings.data_root / "server.json", {}) or {}
    return {**padrao, **((server.get("ratelimit") or {}).get(escopo) or {})}


def _limit(request: Request, escopo: str, padrao: dict) -> None:
    cfg = _cfg(escopo, padrao)
    if not cfg.get("rate"):  # rate 0 = desligado
        return
    ip = ratelimit.client_ip(request)
    if not ratelimit.allow(f"{escopo}:{ip}", rate=cfg["rate"], burst=cfg["burst"]):
        raise HTTPException(429, "muitas tentativas; tente de novo em instantes")


@router.get("/models")
async def public_models() -> dict:
    """Templates que a criação por convite pode usar (marcados `public`)."""
    return {"models": store.list_public_models()}


@router.post("/site-images", status_code=201)
async def self_create_image(body: dict, request: Request) -> dict:
    _limit(request, "create", _CREATE)

    code = invites.normalize(body.get("code", ""))
    ok, motivo = invites.is_valid(code)
    if not ok:
        raise HTTPException(403, motivo)

    inv = invites.get(code)
    image_id = str(body.get("id", "")).strip()

    # nomes reservados (dígito inicial) são só da administração
    if store.reserved_re().match(image_id):
        raise HTTPException(403, "esse nome é reservado à administração; escolha outro")

    model = inv.get("model") or str(body.get("model", ""))
    if not store.model_is_public(model):
        raise HTTPException(400, "modelo inválido ou não disponível para auto-atendimento")

    try:
        created = store.create_site_image(
            image_id,
            str(body.get("fullname", "")),
            model,
            # Perfil Livre por padrão: quem cria a própria imagem manda nela
            # inteira (RAM mínima, firewall, pendrive, página inicial...). O
            # convite pode ter sido emitido como Oficial, e aí as travas do
            # model valem.
            unlocked=bool(inv.get("unlocked", True)),
            # o dono é a identidade, NÃO o código: gravar o código aqui
            # entregaria a credencial de console do sub-admin a quem tivesse
            # só o token da imagem (que lê o image.json pelo configureitor)
            owner=owners.owner_id(code),
            extra={
                "self_service": True,
                "build_quota": int(inv.get("build_quota", invites.DEFAULT_BUILD_QUOTA)),
                "wallpaper_locked": bool(inv.get("wallpaper_locked", False)),
            },
        )
    except store.ImageError as e:
        raise HTTPException(400, str(e))

    invites.consume(code, image_id)
    owners.ensure(code)
    usb.agendar(image_id)
    # o mesmo código abre o console de sub-admin: quem criou volta para
    # gerenciar o que é seu, sem cadastro separado
    return {**created, "console_url": f"{settings.base_url}/admin/", "console_code": code}


@router.post("/requests", status_code=201)
async def submit_request(body: dict, request: Request) -> dict:
    _limit(request, "request", _REQUEST)
    wanted = str(body.get("wanted_name", "")).strip()
    contact = str(body.get("contact", "")).strip()
    if not wanted or not contact:
        raise HTTPException(400, "informe o nome desejado e um contato")
    req = requests.submit(wanted, contact, str(body.get("note", "")))
    return {"ok": True, "id": req["id"]}
