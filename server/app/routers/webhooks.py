"""Configuração de webhooks e chaves de serviço (MOJ).

Tudo aqui é `require_admin`, diferente de config/roster/camadas, que o
sub-admin dono administra. É de propósito: um webhook faz o servidor bater
numa URL escolhida por quem o configura, de dentro da rede da máquina de
gestão. Entregar isso a quem entrou por convite é dar um cliente HTTP na rede
interna de graça.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, fsdb
from ..services import store
from ..settings import settings

router = APIRouter(prefix="/api/v1")

EVENTOS = [
    "machine.first_seen",
    "machine.status",
    "machine.locked",
    "machine.unlocked",
    "machine.bound",
    "machine.unbound",
    "command.sent",
    "command.acked",
    "config.updated",
    "seeder.joined",
    "alert.raised",
    "alert.dismissed",
]

ESCOPOS = [
    "machines:read",
    "commands:write",
    "bindings:write",
    "roster:read",
    "roster:write",
    "config:write",
]


@router.get("/events/types")
async def event_types() -> dict:
    """Catálogo de eventos e escopos — serve de documentação viva para quem
    for integrar (o MOJ, por exemplo)."""
    return {"events": EVENTOS, "scopes": ESCOPOS}


@router.get("/site-images/{image}/webhooks")
async def get_webhooks(image: str, p=Depends(auth.require_admin)) -> dict:
    conf = fsdb.read_json(store.site_image_dir(image) / "webhooks.json", []) or []
    # o segredo não volta em claro
    return {
        "webhooks": [
            {**w, "secret": "***" if w.get("secret") else ""} for w in conf
        ]
    }


@router.put("/site-images/{image}/webhooks")
async def put_webhooks(image: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    if not store.site_image_exists(image):
        raise HTTPException(404, "imagem não existe")
    hooks = body.get("webhooks")
    if not isinstance(hooks, list):
        raise HTTPException(400, "esperava {webhooks: [...]}")
    limpo = []
    for h in hooks:
        url = str(h.get("url", ""))
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, f"url inválida: {url}")
        eventos = h.get("events") or []
        for e in eventos:
            if e not in EVENTOS:
                raise HTTPException(400, f"evento desconhecido: {e}")
        limpo.append({"url": url, "secret": str(h.get("secret", "")), "events": eventos})
    fsdb.write_json(store.site_image_dir(image) / "webhooks.json", limpo, mode=0o600)
    return {"ok": True, "webhooks": len(limpo)}


@router.post("/service-keys")
async def create_service_key(body: dict, p=Depends(auth.require_admin)) -> dict:
    """Cria a credencial que o MOJ usa. O escopo limita o que ela faz e
    `images` limita a quais imagens ela enxerga."""
    nome = str(body.get("name", "")).strip()
    if not nome:
        raise HTTPException(400, "informe um nome")
    escopos = body.get("scopes") or []
    for s in escopos:
        if s not in ESCOPOS:
            raise HTTPException(400, f"escopo desconhecido: {s}")

    key = auth.new_key("nb3s")
    path = settings.data_root / "keys" / "services.json"
    with fsdb.locked(path.parent):
        conf = fsdb.read_json(path, {}) or {}
        conf[nome] = {
            "sha256": auth.key_hash(key),
            "scopes": escopos,
            "images": body.get("images") or [],
        }
        fsdb.write_json(path, conf, mode=0o600)
    return {"name": nome, "key": key, "scopes": escopos, "images": body.get("images") or []}


@router.get("/service-keys")
async def list_service_keys(p=Depends(auth.require_admin)) -> dict:
    conf = fsdb.read_json(settings.data_root / "keys" / "services.json", {}) or {}
    return {
        "service_keys": [
            {"name": n, "scopes": v.get("scopes", []), "images": v.get("images", [])}
            for n, v in conf.items()
        ]
    }


@router.delete("/service-keys/{name}", status_code=204)
async def delete_service_key(name: str, p=Depends(auth.require_admin)) -> None:
    path = settings.data_root / "keys" / "services.json"
    with fsdb.locked(path.parent):
        conf = fsdb.read_json(path, {}) or {}
        conf.pop(name, None)
        fsdb.write_json(path, conf, mode=0o600)
