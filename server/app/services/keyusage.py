"""Quando cada chave foi usada pela última vez.

Uma chave que vazou há seis meses era indistinguível de uma em uso: nada dizia
"esta não bate aqui desde julho". O custo não pode ser uma escrita em disco por
requisição (são dezenas por segundo na frota, num worker só): o instante fica
num mapa EM MEMÓRIA e é despejado no máximo uma vez por minuto, num arquivo
SEPARADO (`keys/last-used.json`). Separado de propósito: um defeito neste
despejo nunca pode tocar o `admin.json` e trancar a administração para fora.

Só chaves de admin (pela impressão digital) e de serviço (pelo nome). Token de
sede e chave de máquina batem o tempo todo; o "último uso" deles é o
`last_seen` das máquinas.
"""

from __future__ import annotations

import asyncio
import time

from .. import fsdb
from ..settings import settings

INTERVALO = 60
_memoria: dict[str, float] = {}
_sujo = False
_tarefa = None


def _caminho():
    return settings.data_root / "keys" / "last-used.json"


def tocar(kind: str, ident: str) -> None:
    global _sujo
    _memoria[f"{kind}:{ident}"] = time.time()
    _sujo = True


def ultimo(kind: str, ident: str) -> int | None:
    chave = f"{kind}:{ident}"
    disco = (fsdb.read_json(_caminho(), {}) or {}).get(chave) or 0
    valor = max(_memoria.get(chave, 0), disco)
    return int(valor) or None


def esquecer(kind: str, ident: str) -> None:
    global _sujo
    _memoria.pop(f"{kind}:{ident}", None)
    dados = fsdb.read_json(_caminho(), {}) or {}
    if dados.pop(f"{kind}:{ident}", None) is not None:
        fsdb.write_json(_caminho(), dados, mode=0o600)


def despejar() -> bool:
    """Grava o que mudou. Devolve True se escreveu."""
    global _sujo
    if not _sujo:
        return False
    _sujo = False
    dados = fsdb.read_json(_caminho(), {}) or {}
    for chave, quando in _memoria.items():
        dados[chave] = max(int(quando), int(dados.get(chave) or 0))
    fsdb.write_json(_caminho(), dados, mode=0o600)
    return True


async def _laco() -> None:
    while True:
        await asyncio.sleep(INTERVALO)
        try:
            await asyncio.to_thread(despejar)
        except Exception:  # noqa: BLE001 — estatística não derruba servidor
            pass


def iniciar() -> None:
    global _tarefa
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _tarefa is None or _tarefa.done():
        _tarefa = loop.create_task(_laco())


def reset() -> None:
    global _sujo
    _memoria.clear()
    _sujo = False
