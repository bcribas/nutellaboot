"""Disparo e estado do relatório da frota.

Mesmo formato de `services/usb.py`, e pelo mesmo motivo: é trabalho longo
demais para uma requisição. A frota inteira com 7 dias de amostra são 1,5 GB e
~118 s de CPU (medido). Dentro do worker congelaria o boot de todas as salas —
e thread não resolveria, porque quem gasta o tempo é `json.loads`, que segura a
GIL enquanto roda.

Por isso: subprocesso, estado em disco, e a tela perguntando se já ficou pronto.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import time
from pathlib import Path

from .. import fsdb
from ..settings import REPO_ROOT, settings

FERRAMENTA = REPO_ROOT / "tools" / "nb3-relatorio-frota"

# Uma frota grande leva minutos; meia hora é o sinal de que algo travou.
TIMEOUT = 1800

# O que a rota de download aceita. Lista fechada porque é nome vindo da URL
# indo para o disco, e o diretório vizinho tem as chaves de todas as sedes.
ARQUIVOS = (
    "relatorio.html",
    "inventario.csv",
    "editores.csv",
    "recursos-hora.csv",
    "recursos-brutos.csv.gz",
    "alertas.csv",
    "resumo.json",
)

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".gz": "application/gzip",
    ".json": "application/json",
}


def _dir() -> Path:
    return settings.data_root / "reports" / "frota"


def _estado_path() -> Path:
    return settings.data_root / "reports" / "frota.json"


def _travado(e: dict) -> bool:
    """`building` que passou do tempo é geração MORTA, não geração andando.

    A tarefa vive no laço do worker: se ele reiniciar no meio (deploy, OOM), o
    estado em disco fica `building` para sempre — e como `agendar` recusa
    enquanto estiver assim, o botão nunca mais funcionaria. Ninguém ia ligar as
    duas coisas olhando a tela.
    """
    return e.get("status") == "building" and time.time() - (e.get("started_at") or 0) > TIMEOUT


def estado() -> dict:
    e = fsdb.read_json(_estado_path(), {}) or {"status": "missing"}
    if _travado(e):
        e = {**e, "status": "failed", "error": "a geração foi interrompida (o servidor reiniciou?)"}
    e["files"] = []
    if e.get("status") == "done":
        for nome in ARQUIVOS:
            p = _dir() / nome
            if p.is_file():
                e["files"].append({"name": nome, "size": p.stat().st_size})
    return e


def caminho_de(nome: str) -> Path | None:
    if nome not in ARQUIVOS:
        return None
    p = _dir() / nome
    return p if p.is_file() else None


def _marcar(**campos) -> dict:
    atual = fsdb.read_json(_estado_path(), {}) or {}
    novo = {**atual, **campos, "updated_at": time.time()}
    fsdb.write_json(_estado_path(), novo)
    return novo


_lock: asyncio.Lock | None = None
_lock_loop = None


def _obter_lock() -> asyncio.Lock:
    """Um lock por laço de eventos — primitiva de asyncio guardada entre
    requisições quebra quando o laço muda, e a suíte cria um por teste."""
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


async def gerar(desde: float, ate: float) -> dict:
    base = os.environ.get("NB3_RELATORIO_CMD")
    args = ["--desde", f"{desde:.3f}", "--ate", f"{ate:.3f}", "--saida", str(_dir())]
    # `sys.executable` e não o shebang: a ferramenta importa `server.app`, e o
    # `#!/usr/bin/env python3` acharia o Python do SISTEMA, sem o venv — falha
    # com "No module named 'fastapi'" só em produção, onde ninguém está olhando.
    cmd = [*shlex.split(base), *args] if base else [sys.executable, str(FERRAMENTA), *args]

    async with _obter_lock():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(REPO_ROOT),
                env={**os.environ, "NB3_DATA_ROOT": str(settings.data_root)},
            )
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except TimeoutError:
            proc.kill()
            return _marcar(status="failed", error=f"passou de {TIMEOUT // 60} minutos")
        except OSError as e:
            return _marcar(status="failed", error=str(e))

    texto = (saida or b"").decode(errors="replace")[-2000:]
    if proc.returncode != 0:
        return _marcar(status="failed", error=texto.strip()[-800:] or f"código {proc.returncode}")
    return _marcar(status="done", error="", built_at=time.time(), log=texto.strip()[-300:])


_tarefas: set[asyncio.Task] = set()


def agendar(desde: float, ate: float) -> bool:
    """Dispara em segundo plano. Devolve False se já há uma geração andando —
    duas ao mesmo tempo leriam os mesmos 1,5 GB em paralelo, e é o disco que
    atende o boot.

    O `building` é gravado AQUI, e não dentro da tarefa: entre o teste e o
    primeiro `await` da tarefa cabem outras requisições, e dois cliques
    seguidos passariam os dois pela peneira. Aqui não há `await` no meio.
    """
    # `estado()` já converte um `building` morto em `failed`, então aqui
    # "building" quer dizer geração viva de verdade
    if estado().get("status") == "building":
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _marcar(status="building", error="", since=desde, until=ate, started_at=time.time())
    tarefa = loop.create_task(gerar(desde, ate))
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)
    return True
