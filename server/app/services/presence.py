"""Quem sumiu: o evento `machine.offline`.

`online` sempre foi uma conta feita na leitura (`agora - last_seen < 90 s`).
Ninguém AVISAVA que uma máquina tinha parado de reportar; o MOJ só descobria
perguntando. Aqui vive a única coisa que precisa de relógio próprio: uma tarefa
no worker único (invariante 2) que olha, a cada 30 s, um mapa EM MEMÓRIA do
último contato de cada máquina. A varredura não toca o disco: o mapa é
alimentado pela própria rota de telemetria e semeado uma vez, numa thread, ao
subir.

`machine.online` e `machine.rebooted` não moram aqui: saem do `record_status`,
que vê o intervalo desde o contato anterior e a troca de `boot_id` (e por isso
sobrevivem a um restart do servidor). O mesmo tique fecha os comandos que
venceram (`command.expired`).

Ao subir, quem já estava fora do ar é dado por anunciado, em silêncio: o
primeiro deploy não pode despejar um `machine.offline` para cada máquina
desligada da frota. A exceção são as que sumiram nos últimos minutos, que ainda
são notícia (no pior caso o aviso sai repetido depois de um restart).
"""

from __future__ import annotations

import asyncio
import time

from .. import fsdb
from . import command_log, eventos, store
from .machines import ONLINE_WINDOW, list_macs, machine_dir

INTERVALO = 30
AINDA_E_NOTICIA = 300  # segundos: sumiço mais velho que isto, ao subir, não se anuncia

_vistos: dict[tuple[str, str], float] = {}
_fora: set[tuple[str, str]] = set()
_comandos: dict[tuple[str, str], float] = {}  # (imagem, cid) -> quando vence
_tarefa = None


def marcar(image: str, mac: str, agora: float | None = None) -> None:
    chave = (image, mac)
    _vistos[chave] = time.time() if agora is None else agora
    _fora.discard(chave)


def esquecer_imagem(image: str) -> None:
    for mapa in (_vistos, _comandos):
        for chave in [c for c in mapa if c[0] == image]:
            mapa.pop(chave, None)
    for chave in [c for c in _fora if c[0] == image]:
        _fora.discard(chave)


def acompanhar_comando(image: str, cid: str, vence: float) -> None:
    _comandos[(image, cid)] = vence


def varrer(agora: float | None = None) -> list[tuple[str, str, float]]:
    """As máquinas que cruzaram a janela desde a última varredura. Só memória."""
    agora = time.time() if agora is None else agora
    novas = []
    for chave, visto in _vistos.items():
        if chave not in _fora and agora - visto >= ONLINE_WINDOW:
            _fora.add(chave)
            novas.append((chave[0], chave[1], visto))
    return novas


def comandos_vencidos(agora: float | None = None) -> list[tuple[str, str]]:
    agora = time.time() if agora is None else agora
    vencidos = [c for c, vence in _comandos.items() if agora > vence]
    for c in vencidos:
        _comandos.pop(c, None)
    return vencidos


def _semear() -> None:
    agora = time.time()
    for img in store.list_site_images():
        for mac in list_macs(img["id"]):
            info = fsdb.read_json(machine_dir(img["id"], mac) / "machine.json", {}) or {}
            visto = float(info.get("last_seen") or 0)
            chave = (img["id"], mac)
            _vistos.setdefault(chave, visto)
            if agora - visto >= ONLINE_WINDOW + AINDA_E_NOTICIA:
                _fora.add(chave)


def _anunciar_expirados(image: str, cid: str) -> None:
    estado = command_log.estado(image, cid)
    if not estado:
        return
    macs = [t["mac"] for t in estado["targets"] if t["state"] == "expired"]
    if macs:
        eventos.publicar(
            image,
            "command.expired",
            {"command_id": cid, "command": estado["command"], "machines": macs, "count": len(macs)},
        )


async def tique() -> None:
    for image, mac, visto in varrer():
        eventos.publicar(image, "machine.offline", {"mac": mac, "last_seen": int(visto)})
    for image, cid in comandos_vencidos():
        # lê dois arquivos pequenos: fora do loop mesmo assim
        await asyncio.to_thread(_anunciar_expirados, image, cid)


async def _laco() -> None:
    try:
        await asyncio.to_thread(_semear)
    except Exception:  # noqa: BLE001 — uma sede podre não pode matar o vigia
        pass
    while True:
        await asyncio.sleep(INTERVALO)
        try:
            await tique()
        except Exception:  # noqa: BLE001
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
    """Limpa o estado — usado nos testes."""
    _vistos.clear()
    _fora.clear()
    _comandos.clear()
