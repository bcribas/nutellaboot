"""Limite de taxa por chave (em memória, token-bucket).

Guarda estado só na memória do processo — cabe no invariante de worker único
(o mesmo do notify.py). Serve para conter rajadas nas rotas públicas
(criação por convite e envio de pedido) sem depender de infra externa.

ATENÇÃO DE OPERAÇÃO: atrás do proxy, o IP visto é o do proxy (127.0.0.1). Para
o limite por IP funcionar de verdade, o nginx precisa repassar
`X-Forwarded-For` (proxy_set_header). Ver docs/operations.md.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_buckets: dict[str, tuple[float, float]] = {}  # chave -> (tokens, ultimo_ts)


def allow(key: str, *, rate: float, burst: float, now: float | None = None) -> bool:
    """True se a ação é permitida. `rate` = tokens por segundo; `burst` = teto.

    Consome 1 token por chamada. Sem token disponível, retorna False.
    """
    now = time.monotonic() if now is None else now
    with _lock:
        tokens, last = _buckets.get(key, (burst, now))
        tokens = min(burst, tokens + (now - last) * rate)
        if tokens < 1.0:
            _buckets[key] = (tokens, now)
            return False
        _buckets[key] = (tokens - 1.0, now)
        return True


def client_ip(request) -> str:
    """IP do cliente, respeitando X-Forwarded-For (primeiro da lista)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def reset() -> None:
    """Limpa o estado — usado nos testes."""
    with _lock:
        _buckets.clear()
