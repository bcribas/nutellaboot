"""Envio de eventos para sistemas externos (MOJ), assinado com HMAC.

O MOJ pode tanto consultar a API quanto receber estes avisos. A assinatura
permite ao destinatário confirmar que o evento veio daqui:

    X-NB-Signature: sha256=<hmac_sha256(segredo, corpo)>

Cada entrega tem um identificador, `delivery`, DENTRO do corpo (logo, dentro
da assinatura) e repetido em `X-NB-Delivery`. Ele é o mesmo nas três
tentativas, e o corpo também: `at` é o instante do EVENTO, não o da tentativa.
É por `delivery` que o destinatário descarta a repetição de uma entrega que
ele já tinha recebido mas cuja resposta se perdeu.

Entrega é "melhor esforço" com poucas tentativas: um webhook lento nunca pode
segurar o boot nem o comando de bloqueio.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
import weakref
from urllib.parse import urlsplit

import httpx

from ..settings import VERSION
from . import logcap
from .store import site_image_dir

TIMEOUT = 5.0
TENTATIVAS = 3
ESPERAS = (1.0, 2.0)  # entre as tentativas; depois da última não se espera nada
SIMULTANEAS = 8
MAX_EM_VOO = 1000
LOG = "webhooks.log"
LOG_TETO = 256 * 1024

# a tarefa só vive enquanto alguém a referencia: o loop guarda referência fraca,
# e uma entrega no meio do caminho podia ser recolhida pelo coletor
_tarefas: set[asyncio.Task] = set()
# um semáforo por loop (um objeto asyncio preso a um loop não serve em outro:
# é a armadilha do asyncio.Event, no CLAUDE.md)
_semaforos: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def webhooks_for(image_id: str, event: str) -> list[dict]:
    from . import webhooks_store

    # pelo store: o arquivo antigo (sem id, sem dono) sai normalizado
    conf = webhooks_store.carregar(image_id)
    return [w for w in conf if not w.get("events") or event in w["events"]]


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _registra(image_id: str, linha: dict) -> None:
    """Só o que deu errado, e nunca o corpo, o segredo nem a query string (é
    onde o destinatário costuma pôr o token dele)."""
    logcap.append_capped(
        site_image_dir(image_id) / LOG, json.dumps(linha, ensure_ascii=False), LOG_TETO
    )


def _destino(url: str) -> dict:
    partes = urlsplit(url)
    return {"host": partes.netloc.rsplit("@", 1)[-1], "path": partes.path}


async def _deliver(image_id: str, w: dict, event: str, delivery: str, body: bytes) -> bool:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"NutellaBoot3/{VERSION}",
        "X-NB-Event": event,
        "X-NB-Delivery": delivery,
    }
    if w.get("id"):
        headers["X-NB-Webhook-Id"] = str(w["id"])
    if w.get("secret"):
        headers["X-NB-Signature"] = sign(w["secret"], body)

    if str(w.get("owner", "")).startswith("service:"):
        # de novo, na hora de bater: o DNS pode ter mudado desde o cadastro
        from . import webhook_guard

        motivo = await asyncio.to_thread(webhook_guard.motivo_da_recusa, w["url"])
        if motivo:
            linha = {"at": int(time.time()), "delivery": delivery, "event": event,
                     "webhook_id": w.get("id", ""), **_destino(w["url"]), "attempts": 0,
                     "error": "forbidden_destination"}
            await asyncio.to_thread(_registra, image_id, linha)
            return False

    loop = asyncio.get_running_loop()
    semaforo = _semaforos.get(loop)
    if semaforo is None:
        semaforo = _semaforos[loop] = asyncio.Semaphore(SIMULTANEAS)

    ultimo: dict = {}
    async with semaforo:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            for tentativa in range(TENTATIVAS):
                headers["X-NB-Attempt"] = str(tentativa + 1)
                try:
                    r = await client.post(w["url"], content=body, headers=headers)
                    if r.status_code < 400:
                        return True
                    ultimo = {"last_status": r.status_code}
                except httpx.HTTPError as e:
                    ultimo = {"error": type(e).__name__}
                if tentativa < len(ESPERAS):
                    await asyncio.sleep(ESPERAS[tentativa])
    linha = {
        "at": int(time.time()),
        "delivery": delivery,
        "event": event,
        "webhook_id": w.get("id", ""),
        **_destino(w["url"]),
        "attempts": TENTATIVAS,
        **ultimo,
    }
    await asyncio.to_thread(_registra, image_id, linha)
    return False


async def testar(image_id: str, w: dict) -> dict:
    """Uma entrega só, esperada, para o botão "enviar teste": diz na hora se a
    URL responde e se o destinatário aceita a assinatura."""
    delivery = uuid.uuid4().hex
    corpo = json.dumps(
        {"event": "webhook.test", "image": image_id, "at": int(time.time()),
         "delivery": delivery, "data": {"test": True, "webhook_id": w.get("id", "")}},
        ensure_ascii=False,
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"NutellaBoot3/{VERSION}",
        "X-NB-Event": "webhook.test",
        "X-NB-Delivery": delivery,
        "X-NB-Attempt": "1",
        "X-NB-Webhook-Id": str(w.get("id", "")),
    }
    if w.get("secret"):
        headers["X-NB-Signature"] = sign(w["secret"], corpo)
    inicio = time.monotonic()
    saida = {"ok": False, "status_code": None, "error": "", "delivery": delivery}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            r = await client.post(w["url"], content=corpo, headers=headers)
        saida.update(ok=r.status_code < 400, status_code=r.status_code)
    except httpx.HTTPError as e:
        saida["error"] = type(e).__name__
    saida["elapsed_ms"] = int((time.monotonic() - inicio) * 1000)
    return saida


def falhas(image_id: str, n: int = 100) -> list[dict]:
    caminho = site_image_dir(image_id) / LOG
    if not caminho.is_file():
        return []
    out = []
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
        try:
            out.append(json.loads(linha))
        except ValueError:
            continue
    return out


def emit(image_id: str, event: str, data: dict) -> None:
    """Dispara em segundo plano; nunca bloqueia quem chamou. Precisa estar no
    event loop: quem publica de uma rota `def` usa `eventos.publicar`."""
    alvos = webhooks_for(image_id, event)
    if not alvos:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # fora de contexto assíncrono (testes síncronos): ignora
    agora = int(time.time())
    for w in alvos:
        delivery = uuid.uuid4().hex
        if len(_tarefas) >= MAX_EM_VOO:
            # destinatário morto com `events: []` (assina machine.status, dezenas
            # por segundo na frota): descarta, e deixa escrito que descartou
            _registra(
                image_id,
                {"at": agora, "delivery": delivery, "event": event, "webhook_id": w.get("id", ""),
                 **_destino(w["url"]), "attempts": 0, "error": "dropped"},
            )
            continue
        # um corpo POR assinante (o `delivery` é de cada um), montado uma vez:
        # as três tentativas levam exatamente os mesmos bytes
        corpo = json.dumps(
            {"event": event, "image": image_id, "at": agora, "delivery": delivery, "data": data},
            ensure_ascii=False,
        ).encode()
        tarefa = loop.create_task(_deliver(image_id, w, event, delivery, corpo))
        _tarefas.add(tarefa)
        tarefa.add_done_callback(_tarefas.discard)
