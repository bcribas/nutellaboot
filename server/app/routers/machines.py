"""Telemetria, fila de comandos (long-poll), bloqueio de tela e eventos (SSE)."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .. import auth
from ..services import machines as m
from ..services import webhook_push
from ..services.notify import notify

router = APIRouter(prefix="/api/v1")

# Teto do long-poll. O agente pede wait=25 e o servidor devolve na hora em que
# um comando é enfileirado — latência de segundos com UMA requisição por
# máquina a cada ~25 s (o nb2 fazia polling a cada 5-30 s e ainda somava o
# atraso configurado, passando de 30 s até a tela travar).
MAX_WAIT = 30.0


def _machine(image: str, x_nb_machine_key: str | None, mac: str) -> str:
    auth.require_machine(image, x_nb_machine_key)
    mac = m.normalize_mac(mac)
    if not m.valid_mac(mac):
        raise HTTPException(400, "MAC inválido")
    return mac


def _publish(image: str, event: str, data: dict) -> None:
    """Avisa o painel (SSE) e os sistemas externos inscritos (webhooks)."""
    notify.publish(image, {"event": event, "data": data, "at": time.time()})
    webhook_push.emit(image, event, data)


@router.post("/site-images/{image}/machines/{mac}/status")
async def post_status(
    image: str, mac: str, body: dict, x_nb_machine_key: str | None = Header(None)
) -> dict:
    mac = _machine(image, x_nb_machine_key, mac)
    res = m.record_status(image, mac, body)
    _publish(image, "machine.status", {"mac": mac})
    if res["first_seen"]:
        _publish(image, "machine.first_seen", {"mac": mac})
    return {
        "pending_commands": len(m.ready_commands(image, mac)),
        "lock": m.get_lock(image, mac),
    }


@router.get("/site-images/{image}/machines/{mac}/commands")
async def poll_commands(
    image: str,
    mac: str,
    request: Request,
    wait: float = Query(0, ge=0, le=MAX_WAIT),
    x_nb_machine_key: str | None = Header(None),
) -> dict:
    """Long-poll: segura a conexão até chegar comando ou estourar `wait`."""
    mac = _machine(image, x_nb_machine_key, mac)
    deadline = time.monotonic() + wait
    while True:
        cmds = m.ready_commands(image, mac)
        if cmds or wait == 0:
            return {"commands": cmds, "lock": m.get_lock(image, mac)}
        restante = deadline - time.monotonic()
        if restante <= 0:
            return {"commands": [], "lock": m.get_lock(image, mac)}
        if await request.is_disconnected():
            return {"commands": [], "lock": m.get_lock(image, mac)}
        # acorda na hora em que alguém enfileira algo para esta máquina
        await notify.wait_machine(image, mac, min(restante, 5.0))


@router.post("/site-images/{image}/machines/{mac}/commands/{cid}/ack")
async def ack_command(
    image: str, mac: str, cid: str, body: dict, x_nb_machine_key: str | None = Header(None)
) -> dict:
    mac = _machine(image, x_nb_machine_key, mac)
    found = m.ack(image, mac, cid, {"status": body.get("status", "done"), "output": body.get("output", "")})
    _publish(image, "command.acked", {"mac": mac, "id": cid, "status": body.get("status")})
    return {"ok": True, "found": found}


@router.get("/site-images/{image}/machines")
async def list_machines(
    image: str, p=Depends(auth.require_image_access(service_scope="machines:read"))
) -> dict:
    return {"machines": m.list_machines(image)}


@router.get("/site-images/{image}/machines/{mac}")
async def get_machine(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope="machines:read"))
) -> dict:
    return m.get_machine(image, m.normalize_mac(mac))


@router.post("/site-images/{image}/commands")
async def create_command(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    command = body.get("command", "")
    if command not in m.ALLOWED_COMMANDS:
        raise HTTPException(400, f"comando não permitido: {command}")
    target = body.get("target", "all")
    macs = m.list_macs(image) if target == "all" else [m.normalize_mac(x) for x in target]
    macs = [x for x in macs if m.valid_mac(x)]
    if not macs:
        raise HTTPException(400, "nenhuma máquina alvo")

    cid = m.enqueue(image, macs, command, body.get("args", ""), int(body.get("delay", 0)))
    for mac in macs:
        notify.wake_machine(image, mac)
    _publish(image, "command.sent", {"id": cid, "command": command, "machines": len(macs)})
    return {"command_id": cid, "machines": len(macs)}


async def _lock(image: str, macs: list[str], locked: bool, by: str) -> dict:
    """Trava/destrava por DOIS caminhos ao mesmo tempo: grava o estado (que a
    própria tela consulta) e enfileira o comando (que o agente executa). Se um
    falhar, o outro resolve."""
    for mac in macs:
        m.set_lock(image, mac, locked, by)
    cid = m.enqueue(image, macs, "donottouch" if locked else "cantouch")
    for mac in macs:
        notify.wake_machine(image, mac)
    _publish(image, "machine.locked" if locked else "machine.unlocked", {"machines": macs})
    return {"command_id": cid, "machines": len(macs), "locked": locked}


@router.post("/site-images/{image}/lock")
async def lock_all(
    image: str, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    return await _lock(image, m.list_macs(image), True, p.name)


@router.post("/site-images/{image}/unlock")
async def unlock_all(
    image: str, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    return await _lock(image, m.list_macs(image), False, p.name)


@router.post("/site-images/{image}/machines/{mac}/lock")
async def lock_one(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    return await _lock(image, [m.normalize_mac(mac)], True, p.name)


@router.post("/site-images/{image}/machines/{mac}/unlock")
async def unlock_one(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    return await _lock(image, [m.normalize_mac(mac)], False, p.name)


@router.get("/site-images/{image}/events")
async def events(image: str, request: Request, tk: str = Query("")) -> StreamingResponse:
    """Fluxo SSE para o painel do laboratório (sem recarregar a página).
    O token vem na query porque EventSource não manda cabeçalhos."""
    p = auth.identify(tk, image_id=image)
    if not p or not p.can_see_image(image):
        raise HTTPException(401, "credencial inválida")

    async def stream():
        q = notify.subscribe(image)
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # mantém a conexão viva
        finally:
            notify.unsubscribe(image, q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
