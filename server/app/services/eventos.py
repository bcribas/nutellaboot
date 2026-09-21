"""O publicador único de eventos: painel (SSE) e sistemas externos (webhooks).

Havia cinco cópias deste par de linhas espalhadas pelas rotas, todas supondo
que rodavam NO event loop. Duas coisas quebravam em silêncio fora dele:
`notify.publish` mexe em `asyncio.Queue` (não é seguro a partir de outra
thread) e `webhook_push.emit` desistia sem avisar quando não achava loop. Rota
`def` roda no threadpool (é o que a invariante 2 manda para quem varre disco),
então um evento publicado dali simplesmente sumia.

Regra que acompanha este módulo: **nunca publique segurando `fsdb.locked`**.
Uma rota `def` que segura o lock e espera o loop (o salto abaixo) trava se o
loop estiver, ele mesmo, esperando aquele lock. Solte o lock, depois publique.
"""

from __future__ import annotations

import asyncio
import time

import anyio

from . import webhook_push
from .notify import notify


def _no_loop(image: str, event: str, data: dict) -> None:
    notify.publish(image, {"event": event, "data": data, "at": int(time.time())})
    # pelo atributo do módulo, e com três posicionais: os testes trocam o
    # `emit` por um espião com exatamente essa forma
    webhook_push.emit(image, event, data)


def publicar(image: str, event: str, data: dict) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        _no_loop(image, event, data)
        return
    try:
        # thread do threadpool do anyio (rota `def`): volta ao loop para publicar
        anyio.from_thread.run_sync(_no_loop, image, event, data)
    except RuntimeError:
        # sem loop nenhum ao alcance (teste de serviço, ferramenta): o SSE não
        # tem assinante e o emit desiste sozinho
        _no_loop(image, event, data)
