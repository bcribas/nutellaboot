"""Sinais em memória para long-poll e SSE.

Só sinais de wakeup vivem aqui — o estado é sempre o do disco. Por isso o
servidor DEVE rodar com um único worker uvicorn (invariante documentada em
docs/architecture.md).

Detalhe importante: os `asyncio.Event` são criados DENTRO da requisição que
espera, nunca guardados entre requisições. Um Event fica preso ao event loop
em que foi criado; guardá-lo em um dicionário de longa duração quebra assim
que outro loop tenta usá-lo.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict


class Notify:
    def __init__(self) -> None:
        self._waiters: dict[tuple[str, str], set[asyncio.Event]] = defaultdict(set)
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    # --- long-poll de comandos (por máquina) ---

    def wake_machine(self, image: str, mac: str) -> None:
        for ev in list(self._waiters.get((image, mac), ())):
            ev.set()

    def wake_all_machines(self, image: str) -> None:
        for (img, _mac), evs in self._waiters.items():
            if img == image:
                for ev in list(evs):
                    ev.set()

    async def wait_machine(self, image: str, mac: str, timeout: float) -> bool:
        """Espera um sinal para esta máquina. Retorna True se acordou por
        sinal, False se estourou o tempo."""
        ev = asyncio.Event()
        key = (image, mac)
        self._waiters[key].add(ev)
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._waiters[key].discard(ev)
            if not self._waiters[key]:
                self._waiters.pop(key, None)

    # --- SSE por imagem (painel do laboratório) ---

    def subscribe(self, image: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[image].add(q)
        return q

    def unsubscribe(self, image: str, q: asyncio.Queue) -> None:
        self._subscribers[image].discard(q)
        if not self._subscribers[image]:
            self._subscribers.pop(image, None)

    def publish(self, image: str, event: dict) -> None:
        for q in list(self._subscribers.get(image, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # assinante parado: descarta em vez de segurar o servidor
                self._subscribers[image].discard(q)


notify = Notify()
