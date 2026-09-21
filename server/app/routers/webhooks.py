"""Configuração de webhooks e chaves de serviço (MOJ).

Nada aqui é do sub-admin nem do token da sede, diferente de config/roster/
camadas, que o dono administra. É de propósito: um webhook faz o servidor bater
numa URL escolhida por quem o configura, de dentro da rede da máquina de
gestão. Entregar isso a quem entrou por convite é dar um cliente HTTP na rede
interna de graça.

A chave de SERVIÇO com `webhooks:write` entra (é a administração que a emite),
mas só mexe nas entradas que ela mesma criou, nas imagens do glob dela, e só
aponta para https público ou destino liberado (`services/webhook_guard.py`).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import auth, fsdb
from ..errors import CODIGOS, erro
from ..services import store, webhook_guard, webhook_push
from ..services import webhooks_store as ws
from ..settings import settings

router = APIRouter(prefix="/api/v1")

EVENTOS = [
    "machine.first_seen",
    "machine.rebooted",
    "machine.online",
    "machine.offline",
    "machine.status",
    "machine.locked",
    "machine.unlocked",
    "machine.bound",
    "machine.unbound",
    "command.sent",
    "command.acked",
    "command.expired",
    "config.updated",
    "seeder.joined",
    "seeder.released",
    "alert.raised",
    "alert.dismissed",
]

ESCOPOS = [
    "machines:read",
    "commands:write",
    # dispensar alerta, sem o poder de mandar comando (commands:write também
    # dispensa, por compatibilidade)
    "alerts:write",
    "bindings:write",
    # instalar e remover os PRÓPRIOS webhooks, nas imagens do glob
    "webhooks:write",
    "roster:read",
    "roster:write",
    "config:write",
    # leitura dos agregados da frota (/labs*): é a chave compartilhável do
    # dashboard — não abre hotconfig (exige machines:read) nem comanda
    "labs:read",
]


@router.get("/events/types")
async def event_types() -> dict:
    """Catálogo de eventos e escopos — serve de documentação viva para quem
    for integrar (o MOJ, por exemplo)."""
    return {"events": EVENTOS, "scopes": ESCOPOS, "error_codes": CODIGOS}


def _dono(p) -> str:
    return f"service:{p.name}" if p.kind == "service" else "admin"


def _minhas(p, lista: list[dict]) -> list[dict]:
    """A administração vê todas; a chave de serviço, só as que ela criou (e nem
    fica sabendo que as outras existem)."""
    if p.kind != "service":
        return lista
    return [w for w in lista if w["owner"] == _dono(p)]


def _confere_eventos(valor) -> list[str]:
    eventos = valor or []
    if not isinstance(eventos, list):
        raise erro(400, "invalid_event", "events é uma lista")
    for e in eventos:
        if e not in EVENTOS:
            raise erro(400, "invalid_event", f"evento desconhecido: {e}")
    return [str(e) for e in eventos]


async def _confere_url(p, valor) -> str:
    url = str(valor or "")
    if not url.startswith(("http://", "https://")):
        raise erro(400, "invalid_url", f"url inválida: {url}")
    if p.kind == "service":
        # resolve DNS: fora do event loop
        motivo = await asyncio.to_thread(webhook_guard.motivo_da_recusa, url)
        if motivo:
            raise erro(400, "webhook_url_forbidden", motivo)
    return url


def _confere_segredo(p, valor) -> str:
    segredo = str(valor or "")
    if segredo == ws.MASCARA:
        raise erro(400, "invalid_secret", f'"{ws.MASCARA}" é a máscara do GET, não um segredo')
    if p.kind == "service" and len(segredo) < ws.SEGREDO_MINIMO:
        # sem segredo o destinatário não tem como saber que fomos nós
        raise erro(400, "invalid_secret", f"o segredo precisa de {ws.SEGREDO_MINIMO} caracteres ou mais")
    return segredo


WEBHOOKS = auth.require_admin_or_service("webhooks:write")


@router.get("/site-images/{image}/webhooks")
async def get_webhooks(image: str, p=Depends(WEBHOOKS)) -> dict:
    return {"webhooks": [ws.publica(w) for w in _minhas(p, ws.carregar(image))]}


@router.post("/site-images/{image}/webhooks")
async def add_webhook(image: str, body: dict, response: Response, p=Depends(WEBHOOKS)) -> dict:
    """Acrescenta UM webhook. A mesma url pelo mesmo dono é a mesma entrada:
    "reinstalar" atualiza em vez de duplicar a entrega."""
    url = await _confere_url(p, body.get("url"))
    eventos = _confere_eventos(body.get("events"))
    dono = _dono(p)
    with ws.editar(image) as lista:
        atual = next((w for w in lista if w["owner"] == dono and w["url"] == url), None)
        if atual is not None:
            atual["events"] = eventos
            if body.get("secret"):
                atual["secret"] = _confere_segredo(p, body.get("secret"))
            return {**ws.publica(atual), "created": False}
        if p.kind == "service" and len(_minhas(p, lista)) >= ws.TETO_POR_SERVICO:
            raise erro(400, "webhook_limit", f"no máximo {ws.TETO_POR_SERVICO} webhooks por chave nesta imagem")
        nova = ws.nova(url, _confere_segredo(p, body.get("secret")), eventos, dono)
        lista.append(nova)
    response.status_code = 201
    return {**ws.publica(nova), "created": True}


def _acha(p, lista: list[dict], webhook_id: str) -> dict:
    w = next((x for x in _minhas(p, lista) if x["id"] == webhook_id), None)
    if w is None:
        raise erro(404, "webhook_not_found", "webhook não existe")
    return w


@router.put("/site-images/{image}/webhooks/{webhook_id}")
async def update_webhook(image: str, webhook_id: str, body: dict, p=Depends(WEBHOOKS)) -> dict:
    """Parcial: só o que vier muda. Mandar só `secret` é a rotação do segredo."""
    url = await _confere_url(p, body["url"]) if "url" in body else None
    eventos = _confere_eventos(body["events"]) if "events" in body else None
    segredo = _confere_segredo(p, body["secret"]) if "secret" in body else None
    with ws.editar(image) as lista:
        w = _acha(p, lista, webhook_id)
        if url is not None:
            w["url"] = url
        if eventos is not None:
            w["events"] = eventos
        if segredo is not None:
            w["secret"] = segredo
        return ws.publica(w)


@router.delete("/site-images/{image}/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(image: str, webhook_id: str, p=Depends(WEBHOOKS)) -> None:
    with ws.editar(image) as lista:
        lista.remove(_acha(p, lista, webhook_id))


@router.post("/site-images/{image}/webhooks/{webhook_id}/test")
async def test_webhook(image: str, webhook_id: str, p=Depends(WEBHOOKS)) -> dict:
    """Dispara `webhook.test` agora e devolve o que o destinatário respondeu."""
    w = _acha(p, ws.carregar(image), webhook_id)
    if w["owner"].startswith("service:"):
        motivo = await asyncio.to_thread(webhook_guard.motivo_da_recusa, w["url"])
        if motivo:
            raise erro(400, "webhook_url_forbidden", motivo)
    return await webhook_push.testar(image, w)


@router.get("/site-images/{image}/webhooks/deliveries")
def webhook_deliveries(image: str, n: int = Query(100, ge=1, le=1000), p=Depends(WEBHOOKS)) -> dict:
    """As entregas que esgotaram as tentativas (ou foram descartadas). Só as
    dos webhooks que `p` enxerga."""
    meus = {w["id"] for w in _minhas(p, ws.carregar(image))}
    linhas = webhook_push.falhas(image, n)
    if p.kind == "service":
        linhas = [x for x in linhas if x.get("webhook_id") in meus]
    return {"deliveries": linhas}


@router.put("/site-images/{image}/webhooks")
async def put_webhooks(image: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """A lista inteira, só da administração (é o que o MOJ fazia com a chave de
    admin: GET, acrescenta o seu, PUT). Três cuidados para o ler-e-regravar não
    destruir nada: a entrada é casada por `id` e depois por `url`, e guarda id,
    dono e data; segredo ausente ou mascarado (`***`) MANTÉM o gravado (`""`
    limpa); e webhook de chave de serviço que ficou de fora NÃO é apagado: ele
    nem aparece para quem só administra os seus. Apagar é pelo DELETE."""
    if not store.site_image_exists(image):
        raise erro(404, "image_not_found", "imagem não existe")
    hooks = body.get("webhooks")
    if not isinstance(hooks, list):
        raise HTTPException(400, "esperava {webhooks: [...]}")
    pedidos = []
    for h in hooks:
        if not isinstance(h, dict):
            raise HTTPException(400, "cada webhook é um objeto")
        pedidos.append((h, await _confere_url(p, h.get("url")), _confere_eventos(h.get("events"))))
    with ws.editar(image) as lista:
        restantes = list(lista)
        nova_lista = []
        for h, url, eventos in pedidos:
            atual = next((w for w in restantes if h.get("id") and w["id"] == h["id"]), None)
            if atual is None:
                atual = next((w for w in restantes if w["url"] == url), None)
            if atual is not None:
                restantes.remove(atual)
            bruto = h.get("secret")
            if bruto is None or bruto == ws.MASCARA:
                if atual is None and bruto == ws.MASCARA:
                    raise erro(400, "invalid_secret", f'"{ws.MASCARA}" é a máscara do GET, não um segredo')
                segredo = atual["secret"] if atual else ""
            else:
                segredo = str(bruto)
            if atual is None:
                nova_lista.append(ws.nova(url, segredo, eventos, "admin"))
            else:
                nova_lista.append({**atual, "url": url, "secret": segredo, "events": eventos})
        mantidos = [w for w in restantes if w["owner"] != "admin"]
        lista[:] = nova_lista + mantidos
    return {"ok": True, "webhooks": len(nova_lista), "kept": len(mantidos)}


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
