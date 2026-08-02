"""Rotas públicas de auto-atendimento: criar imagem com código de convite e
enviar pedido para a fila. Sem chave de admin, então tudo aqui é
rate-limited por IP e recusa nomes reservados."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..services import invites, ratelimit, requests, store

router = APIRouter(prefix="/api/v1/public")

# rajada curta permitida, depois ~1 a cada poucos segundos
_CREATE = {"rate": 0.2, "burst": 5}
_REQUEST = {"rate": 0.1, "burst": 3}


def _limit(request: Request, escopo: str, cfg: dict) -> None:
    ip = ratelimit.client_ip(request)
    if not ratelimit.allow(f"{escopo}:{ip}", rate=cfg["rate"], burst=cfg["burst"]):
        raise HTTPException(429, "muitas tentativas; tente de novo em instantes")


@router.get("/templates")
async def public_templates() -> dict:
    """Templates que a criação por convite pode usar (marcados `public`)."""
    return {"templates": store.list_public_templates()}


@router.post("/images", status_code=201)
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

    template = inv.get("template") or str(body.get("template", ""))
    if not store.template_is_public(template):
        raise HTTPException(400, "template inválido ou não disponível para auto-atendimento")

    try:
        created = store.create_image(
            image_id,
            str(body.get("fullname", "")),
            template,
            # Perfil Livre por padrão: quem cria a própria imagem manda nela
            # inteira (RAM mínima, firewall, pendrive, página inicial...). O
            # convite pode ter sido emitido como Oficial, e aí as travas do
            # template valem.
            unlocked=bool(inv.get("unlocked", True)),
            extra={
                "self_service": True,
                "build_quota": int(inv.get("build_quota", invites.DEFAULT_BUILD_QUOTA)),
                "invite": code,
            },
        )
    except store.ImageError as e:
        raise HTTPException(400, str(e))

    invites.consume(code, image_id)
    return created


@router.post("/requests", status_code=201)
async def submit_request(body: dict, request: Request) -> dict:
    _limit(request, "request", _REQUEST)
    wanted = str(body.get("wanted_name", "")).strip()
    contact = str(body.get("contact", "")).strip()
    if not wanted or not contact:
        raise HTTPException(400, "informe o nome desejado e um contato")
    req = requests.submit(wanted, contact, str(body.get("note", "")))
    return {"ok": True, "id": req["id"]}
