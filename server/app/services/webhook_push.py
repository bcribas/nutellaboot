"""Envio de eventos para sistemas externos (MOJ), assinado com HMAC.

O MOJ pode tanto consultar a API quanto receber estes avisos. A assinatura
permite ao destinatário confirmar que o evento veio daqui:

    X-NB-Signature: sha256=<hmac_sha256(segredo, corpo)>

Entrega é "melhor esforço" com poucas tentativas: um webhook lento nunca pode
segurar o boot nem o comando de bloqueio.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

import httpx

from .. import fsdb
from .store import image_dir

TIMEOUT = 5.0
TENTATIVAS = 3


def webhooks_for(image_id: str, event: str) -> list[dict]:
    conf = fsdb.read_json(image_dir(image_id) / "webhooks.json", []) or []
    return [w for w in conf if not w.get("events") or event in w["events"]]


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _deliver(url: str, secret: str, body: bytes) -> bool:
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-NB-Signature"] = sign(secret, body)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for tentativa in range(TENTATIVAS):
            try:
                r = await client.post(url, content=body, headers=headers)
                if r.status_code < 400:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2**tentativa)
    return False


def emit(image_id: str, event: str, data: dict) -> None:
    """Dispara em segundo plano; nunca bloqueia quem chamou."""
    alvos = webhooks_for(image_id, event)
    if not alvos:
        return
    payload = json.dumps(
        {"event": event, "image": image_id, "at": time.time(), "data": data},
        ensure_ascii=False,
    ).encode()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # fora de contexto assíncrono (testes síncronos): ignora
    for w in alvos:
        loop.create_task(_deliver(w["url"], w.get("secret", ""), payload))
