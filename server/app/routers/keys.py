"""As credenciais que a administração emite: chaves de admin e de serviço.

Tudo aqui é `require_admin`. As rotas de chave de ADMIN pedem mais: a chave
redigitada (`current_key`) quando a requisição vem por cookie, porque cunhar
uma chave de admin é o único ato que sobrevive à sessão que o fez (ver
`auth.conferir_reauth`). Cada ato fica na auditoria.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from .. import auth
from ..errors import erro
from ..services import audit, keys, sessions
from .webhooks import ESCOPOS

router = APIRouter(prefix="/api/v1")


def _levanta(e: keys.ErroDeChave):
    return erro(e.status, e.code, e.detail)


# --- administração ---


@router.get("/admin-keys")
async def list_admin_keys(p=Depends(auth.require_admin)) -> dict:
    chaves = keys.admin_listar()
    for c in chaves:
        # `current`: a chave com que ESTA requisição entrou (para a tela avisar
        # antes de alguém revogar a própria)
        c["current"] = bool(p.key_fp) and c["fp"] == p.key_fp and c["id"] == p.name
        c["sessions"] = sessions.contar_da_chave(c["id"], c["fp"])
    return {"keys": chaves}


@router.post("/admin-keys", status_code=201)
async def create_admin_key(
    body: dict, request: Request, authorization: str | None = Header(None), p=Depends(auth.require_admin)
) -> dict:
    """Cunha mais uma chave de administração. A chave aparece UMA vez."""
    auth.conferir_reauth(p, request, authorization, body.get("current_key"))
    try:
        nova = keys.admin_criar(body.get("id"), by=p.name)
    except keys.ErroDeChave as e:
        raise _levanta(e)
    audit.registrar(p, request, "admin_key.created", nova["id"], {"fp": nova["fp"]})
    return nova


@router.post("/admin-keys/{key_id}/revoke")
async def revoke_admin_key(
    key_id: str,
    body: dict,
    request: Request,
    authorization: str | None = Header(None),
    p=Depends(auth.require_admin),
) -> dict:
    """Revoga uma chave de admin e derruba as sessões abertas com ela. Não há
    "rotacionar": crie a nova, confira que ela entra, e só então revogue a
    velha (rotacionar mataria a sessão de quem pediu, no meio do pedido)."""
    auth.conferir_reauth(p, request, authorization, body.get("current_key"))
    fp = str(body.get("fp") or "")
    propria = key_id == p.name and (not fp or not p.key_fp or fp == p.key_fp)
    if propria and str(body.get("confirm") or "") != key_id:
        raise erro(
            409, "confirm_required",
            f'esta é a chave com que você entrou: para revogá-la, mande confirm: "{key_id}"',
        )
    try:
        r = keys.admin_revogar(key_id, fp)
    except keys.ErroDeChave as e:
        raise _levanta(e)
    encerradas = sessions.delete_da_chave(r["id"], r["fp"])
    audit.registrar(p, request, "admin_key.revoked", r["id"], {"fp": r["fp"], "sessions_ended": encerradas})
    return {"revoked": r["id"], "fp": r["fp"], "sessions_ended": encerradas, "remaining": r["remaining"]}


# --- serviço ---


def _confere_escopos(escopos) -> list[str]:
    escopos = escopos or []
    if not isinstance(escopos, list):
        raise erro(400, "bad_request", "scopes é uma lista")
    for s in escopos:
        if s not in ESCOPOS:
            raise erro(400, "bad_request", f"escopo desconhecido: {s}")
    return escopos


@router.post("/service-keys")
async def create_service_key(body: dict, request: Request, p=Depends(auth.require_admin)) -> dict:
    """Cria a credencial que o MOJ usa. O escopo limita o que ela faz e
    `images` limita a quais imagens ela enxerga. A chave aparece UMA vez."""
    escopos = _confere_escopos(body.get("scopes"))
    try:
        nova = keys.servico_criar(
            body.get("name"), escopos, body.get("images") or [], body.get("follow") or "", by=p.name
        )
    except keys.ErroDeChave as e:
        raise _levanta(e)
    audit.registrar(p, request, "service_key.created", nova["name"],
                    {"scopes": nova["scopes"], "images": nova["images"], "follow": nova["follow"]})
    return nova


@router.get("/service-keys")
async def list_service_keys(p=Depends(auth.require_admin)) -> dict:
    return {"service_keys": keys.servico_listar()}


@router.patch("/service-keys/{name}")
async def patch_service_key(name: str, body: dict, request: Request, p=Depends(auth.require_admin)) -> dict:
    campos = {k: body[k] for k in ("scopes", "images", "follow") if k in body}
    if "scopes" in campos:
        campos["scopes"] = _confere_escopos(campos["scopes"])
    try:
        r = keys.servico_alterar(name, campos)
    except keys.ErroDeChave as e:
        raise _levanta(e)
    audit.registrar(p, request, "service_key.changed", name, campos)
    return r


@router.post("/service-keys/{name}/rotate")
async def rotate_service_key(name: str, request: Request, p=Depends(auth.require_admin)) -> dict:
    """Chave nova com o MESMO nome, escopos e globs. A antiga morre na hora."""
    try:
        r = keys.servico_rotacionar(name)
    except keys.ErroDeChave as e:
        raise _levanta(e)
    audit.registrar(p, request, "service_key.rotated", name)
    return r


@router.delete("/service-keys/{name}", status_code=204)
async def delete_service_key(name: str, request: Request, p=Depends(auth.require_admin)) -> Response:
    if keys.servico_apagar(name):
        audit.registrar(p, request, "service_key.revoked", name)
    return Response(status_code=204)


# --- auditoria ---


@router.get("/audit")
def read_audit(limit: int = Query(200, ge=1, le=2000), p=Depends(auth.require_admin)) -> dict:
    return {"entries": audit.ler(limit)}
