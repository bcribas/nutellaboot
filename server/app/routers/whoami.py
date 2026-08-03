"""Quem sou eu — o que a tela de administração consulta ao abrir.

Sem isto o console teria que descobrir o que pode fazer tentando e apanhando
de 403, o que enche a tela de erro para o sub-admin em uso normal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import auth
from ..services import invites, owners, ownership

router = APIRouter(prefix="/api/v1")


@router.get("/whoami")
async def whoami(p=Depends(auth.require_console)) -> dict:
    return ownership.whoami(p)


@router.get("/owners")
async def list_owners(p=Depends(auth.require_admin)) -> dict:
    """Sub-admins existentes, com cota e uso — a lista que a administração
    olha para decidir quem precisa de mais espaço ou de ser suspenso."""
    return {"owners": owners.list_all()}


@router.post("/owners/{owner_id}/disable")
async def disable_owner(owner_id: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """Suspende (ou reativa) sem apagar o convite. Apagar o convite também
    corta o acesso, mas perde o histórico de quem criou o quê."""
    if not owners.is_owner_id(owner_id):
        raise HTTPException(400, "identificador de dono inválido")
    valor = bool(body.get("disabled", True))
    return owners.set_disabled(owner_id, valor)


@router.patch("/owners/{owner_id}/quotas")
async def set_quotas(owner_id: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """Aumenta o teto de um sub-admin sem emitir convite novo (o que criaria
    uma segunda identidade e espalharia os objetos entre duas)."""
    if not owners.is_owner_id(owner_id):
        raise HTTPException(400, "identificador de dono inválido")
    campos = {}
    for k in ("max_models", "max_images", "build_quota"):
        if k in body:
            try:
                campos[k] = max(0, int(body[k]))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} precisa ser um número")
    if not campos:
        raise HTTPException(400, "informe max_models, max_images ou build_quota")
    if invites.set_fields(owners.code_of(owner_id), campos) is None:
        raise HTTPException(404, "convite deste sub-admin não existe mais")
    return {"id": owner_id, "quotas": owners.quotas(owner_id), "usage": owners.usage(owner_id)}
