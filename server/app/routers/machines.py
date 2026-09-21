"""Telemetria, fila de comandos (long-poll), bloqueio de tela e eventos (SSE)."""

from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .. import auth
from ..errors import erro
from ..services import alerts, command_log, logs
from ..services import machines as m
from ..services import eventos
from ..services.notify import notify

router = APIRouter(prefix="/api/v1")

# Teto do long-poll. O agente pede wait=25 e o servidor devolve na hora em que
# um comando é enfileirado — latência de segundos com UMA requisição por
# máquina a cada ~25 s (o nb2 fazia polling a cada 5-30 s e ainda somava o
# atraso configurado, passando de 30 s até a tela travar).
MAX_WAIT = 30.0

# De quanto em quanto tempo o long-poll reconfere a fila NO DISCO.
#
# É rede de segurança, não o caminho normal: quem acorda a espera é o `notify`,
# no instante em que o comando é enfileirado, e a latência disso é de
# milissegundos. Este número só decide quanto tempo um sinal PERDIDO demora a
# se recuperar sozinho.
#
# Ele importa por causa da escala: com 1600 máquinas seguradas ao mesmo tempo,
# 5 s viram 320 leituras de disco por segundo dentro do único event loop que
# atende todo o resto — para sempre, mesmo com a sala parada. Em 25 s são 64/s.
# Por isso é parâmetro: em desenvolvimento 5 s é cômodo, em produção não.
BACKSTOP = float(os.environ.get("NB3_LONGPOLL_BACKSTOP", "5"))


def _machine(image: str, x_nb_machine_key: str | None, mac: str) -> str:
    auth.require_machine(image, x_nb_machine_key)
    mac = m.normalize_mac(mac)
    if not m.valid_mac(mac):
        # a chave de máquina confere: é um agente nosso com a identificação
        # quebrada. Guardar isso é o que faz o painel poder dizer por que não
        # aparece máquina nenhuma, em vez de só mostrar a lista vazia.
        m.record_rejected(image, mac[:64])
        raise erro(400, "invalid_mac", "MAC inválido")
    return mac


def publicar_evento(image: str, event: str, data: dict) -> None:
    """Avisa o painel (SSE) e os sistemas externos inscritos (webhooks)."""
    eventos.publicar(image, event, data)


# A telemetria é um dict livre (o servidor não conhece o formato de propósito:
# um parts.d novo no cliente entra sem mudança aqui). Livre não pode ser
# infinito, porém — sem teto, uma máquina escreve um status.json de qualquer
# tamanho no disco do servidor.
MAX_STATUS = 256 * 1024


@router.post("/site-images/{image}/machines/{mac}/status")
async def post_status(
    image: str, mac: str, request: Request, x_nb_machine_key: str | None = Header(None)
) -> dict:
    mac = _machine(image, x_nb_machine_key, mac)
    bruto = await request.body()
    if len(bruto) > MAX_STATUS:
        raise HTTPException(413, f"telemetria grande demais ({len(bruto)} bytes)")
    try:
        body = json.loads(bruto or b"{}")
    except ValueError:
        raise HTTPException(400, "telemetria nao e JSON valido")
    if not isinstance(body, dict):
        raise HTTPException(400, "telemetria precisa ser um objeto JSON")
    res = m.record_status(image, mac, body)
    publicar_evento(image, "machine.status", {"mac": mac})
    if res["first_seen"]:
        publicar_evento(image, "machine.first_seen", {"mac": mac})
    if res.get("alert"):
        publicar_evento(image, "alert.raised", {"mac": mac, **res["alert"]})
    return {
        "pending_commands": len(m.ready_commands(image, mac)),
        "lock": m.get_lock(image, mac),
    }


@router.post("/site-images/{image}/machines/{mac}/logs")
async def post_logs(
    image: str,
    mac: str,
    request: Request,
    origem: str = Query("journal", pattern="^[a-z]{1,16}$"),
    x_nb_machine_key: str | None = Header(None),
) -> dict:
    """Recebe um pedaço do journal (texto puro). O corpo tem teto: é o único
    ponto onde a máquina escreve dado de tamanho livre, e uma máquina em laço
    de erro encheria o disco do servidor sozinha."""
    mac = _machine(image, x_nb_machine_key, mac)
    bruto = await request.body()
    if len(bruto) > logs.MAX_ENVIO:
        raise HTTPException(
            413, f"log grande demais ({len(bruto)} bytes; o teto é {logs.MAX_ENVIO})"
        )
    res = logs.record(image, mac, bruto.decode("utf-8", "replace"), origem=origem)
    return {"ok": True, **res}


@router.get("/site-images/{image}/machines/{mac}/logs")
async def get_logs(
    image: str,
    mac: str,
    tail: int = Query(500, ge=1, le=20000),
    p=Depends(auth.require_image_access(service_scope="machines:read")),
) -> dict:
    mac = m.normalize_mac(mac)
    return {
        "mac": mac,
        "bytes": logs.tamanho(image, mac),
        "journal": logs.tail(image, mac, tail),
        "acks": logs.acks(image, mac),
    }


# o teto PADRÃO do payload de série: 24 h a ~50 s são ~1700 amostras, e
# ninguém distingue isso numa tela. Quem analisa (o MOJ) pede `limit` maior.
MAX_AMOSTRAS = 400
MAX_AMOSTRAS_TETO = 5000


# `def`, não `async def`: lê até 2 MiB por máquina, e no event loop único
# (invariante 2) isso travaria o long-poll de toda a frota. O FastAPI roda a
# rota síncrona no threadpool.
@router.get("/site-images/{image}/machines/{mac}/samples")
def get_samples(
    image: str,
    mac: str,
    since: float = Query(0, ge=0),
    until: float = Query(0, ge=0),
    limit: int = Query(MAX_AMOSTRAS, ge=1, le=MAX_AMOSTRAS_TETO),
    p=Depends(auth.require_image_access(service_scope="machines:read")),
) -> dict:
    """A série da máquina (o que o `samples.jsonl` guarda), reamostrada a
    `limit` pontos mantendo o primeiro e o último, com os metadados do que foi
    feito (`resampled`, `native_points`, `interval_s`) e `truncated` só
    quando o teto do arquivo cortou de fato dentro da janela."""
    from ..services import samples

    return samples.janela(image, m.normalize_mac(mac), since, until, limit)


@router.get("/site-images/{image}/samples")
def get_samples_lote(
    image: str,
    since: float = Query(0, ge=0),
    until: float = Query(0, ge=0),
    limit: int = Query(MAX_AMOSTRAS, ge=1, le=MAX_AMOSTRAS_TETO),
    active_since: float = Query(0, ge=0),
    p=Depends(auth.require_image_access(service_scope="machines:read")),
) -> StreamingResponse:
    """Todas as máquinas da sede de uma vez: uma linha NDJSON por máquina, no
    mesmo formato da rota individual. Um request por sede em vez de um por
    máquina (o MOJ fazia 1.700 por coleta). O gerador é SÍNCRONO de
    propósito: o Starlette o itera no threadpool, máquina a máquina, sem
    montar tudo em memória."""
    from .. import fsdb
    from ..services import samples

    def gerar():
        for mac in m.list_macs(image):
            if active_since:
                info = fsdb.read_json(m.machine_dir(image, mac) / "machine.json", {}) or {}
                if (info.get("last_seen") or 0) < active_since:
                    continue
            try:
                corpo = samples.janela(image, mac, since, until, limit)
            except OSError:
                continue
            yield json.dumps(corpo, ensure_ascii=False, separators=(",", ":")) + "\n"

    return StreamingResponse(
        gerar(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/site-images/{image}/machines/{mac}/events")
async def post_event(
    image: str, mac: str, body: dict, x_nb_machine_key: str | None = Header(None)
) -> dict:
    """A máquina avisa que algo aconteceu — hoje, dispositivo USB conectado.

    Canal separado da telemetria de propósito: a telemetria vai a cada ~45 s e
    é um retrato do agora; um pendrive espetado por dez segundos precisa
    chegar na hora e FICAR registrado mesmo depois de removido.
    """
    mac = _machine(image, x_nb_machine_key, mac)
    alerta = alerts.raise_alert(
        image,
        mac,
        str(body.get("kind", "usb.other")),
        str(body.get("detail", "")),
        {"vendor": str(body.get("vendor", ""))[:120]} if body.get("vendor") else None,
    )
    # o mesmo dispositivo com alerta ainda aberto não é mudança de estado
    if not alerta.get("repeated"):
        publicar_evento(image, "alert.raised", {"mac": mac, **alerta})
    return {"ok": True, "id": alerta["id"], "repeated": bool(alerta.get("repeated"))}


@router.get("/site-images/{image}/alerts")
async def list_alerts(
    image: str, p=Depends(auth.require_image_access(service_scope="machines:read"))
) -> dict:
    return {"alerts": alerts.list_open(image)}


# Dispensar alerta tinha o escopo de COMANDO: quem podia limpar a faixa vermelha
# podia, por tabela, desligar a sala. `alerts:write` separa; `commands:write`
# continua aceito para não quebrar a chave que o MOJ já tem.
ESCOPO_DISPENSA = ("alerts:write", "commands:write")


@router.post("/site-images/{image}/machines/{mac}/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    image: str,
    mac: str,
    alert_id: str,
    p=Depends(auth.require_image_access(service_scope=ESCOPO_DISPENSA)),
) -> dict:
    mac = m.normalize_mac(mac)
    alerta = alerts.dismiss(image, mac, alert_id, p.name or "console")
    if alerta is None:
        # dois fiscais clicando ao mesmo tempo é o caso normal, não um erro
        return {"ok": True, "already": True}
    publicar_evento(image, "alert.dismissed", {"mac": mac, **alerta})
    return {"ok": True, "alert": alerta}


@router.post("/site-images/{image}/machines/{mac}/alerts/dismiss-all")
async def dismiss_all_alerts(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope=ESCOPO_DISPENSA))
) -> dict:
    mac = m.normalize_mac(mac)
    limpos = alerts.dismiss_all(image, mac, p.name or "console")
    for a in limpos:
        publicar_evento(image, "alert.dismissed", {"mac": mac, **a})
    return {"ok": True, "dismissed": len(limpos)}


@router.get("/site-images/{image}/machines/{mac}/alerts/history")
async def alerts_history(
    image: str,
    mac: str,
    p=Depends(auth.require_image_access(service_scope="machines:read")),
) -> dict:
    return {"history": alerts.history(image, m.normalize_mac(mac))}


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
        await notify.wait_machine(image, mac, min(restante, BACKSTOP))


@router.post("/site-images/{image}/machines/{mac}/commands/{cid}/ack")
async def ack_command(
    image: str, mac: str, cid: str, body: dict, x_nb_machine_key: str | None = Header(None)
) -> dict:
    mac = _machine(image, x_nb_machine_key, mac)
    found = m.ack(image, mac, cid, {"status": body.get("status", "done"), "output": body.get("output", "")})
    # `id` é o nome antigo do campo; `command_id` é o que o POST devolve
    dados = {"mac": mac, "id": cid, "command_id": cid, "status": body.get("status")}
    comando = (command_log.ler(image, cid) or {}).get("command")
    if comando:
        dados["command"] = comando
    publicar_evento(image, "command.acked", dados)
    return {"ok": True, "found": found}


@router.get("/site-images/{image}/machines")
async def list_machines(
    image: str,
    active_since: float = Query(0, ge=0),
    p=Depends(auth.require_image_access(service_scope="machines:read")),
) -> dict:
    maquinas = m.list_machines(image, active_since)
    corpo = {"machines": maquinas}
    # só quando não há máquina nenhuma (e sem filtro: lista vazia por
    # `active_since` é normal): é aí que o painel vazio precisa explicar que
    # alguém ESTÁ tentando, e com que identificação
    if not maquinas and not active_since:
        rejeitadas = m.rejected(image)
        if rejeitadas:
            corpo["rejected"] = rejeitadas
    return corpo


@router.get("/site-images/{image}/machines/{mac}")
async def get_machine(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope="machines:read"))
) -> dict:
    return m.get_machine(image, m.normalize_mac(mac))


def comandos_bloqueados(image: str, *, is_admin: bool) -> dict[str, str]:
    """Comandos que esta credencial NÃO pode mandar nesta imagem, e por causa
    de qual campo.

    O cadeado do modelo vale aqui pelo mesmo motivo que vale no configureitor —
    e por um tempo não valeu: quem a tela de configuração impedia de desligar o
    firewall desligava pela tela do laboratório, na sala inteira.
    """
    from ..services import config as cfg

    valores = cfg.effective_values(image)
    fora = {}
    for comando, (campo, impoe) in m.COMANDOS_DE_CONFIG.items():
        if cfg.pode_editar(image, campo, is_admin=is_admin):
            continue
        # só o sentido que CONTRADIZ o valor travado é barrado: voltar para ele
        # é a sede consertando o que a organização quer
        if valores.get(campo) != impoe:
            fora[comando] = campo
    return fora


@router.get("/site-images/{image}/commands")
async def comandos_permitidos(
    image: str, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    """O que esta credencial pode mandar. A tela usa para não oferecer botão
    que o servidor vai recusar, e quem integra para não descobrir apanhando."""
    bloqueados = comandos_bloqueados(image, is_admin=(p.kind == "admin"))
    return {
        "allowed": sorted(m.ALLOWED_COMMANDS - set(bloqueados)),
        "blocked": bloqueados,
    }


@router.post("/site-images/{image}/commands")
async def create_command(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="commands:write"))
) -> dict:
    command = body.get("command", "")
    if command not in m.ALLOWED_COMMANDS:
        raise erro(400, "command_not_allowed", f"comando não permitido: {command}")
    bloqueados = comandos_bloqueados(image, is_admin=(p.kind == "admin"))
    if command in bloqueados:
        raise erro(
            403,
            "command_blocked",
            f"{command}: {bloqueados[command]} está bloqueado pela organização da maratona",
        )
    # Sem `target` o padrão é a sala inteira (é contrato). O perigo é o corpo
    # que QUIS escolher máquinas com o nome errado de campo: o nb3-api mandou
    # `macs` por meses e um "desligue esta máquina" desligava a sala. Quem
    # manda um desses campos sem `target` errou, e o erro tem de aparecer.
    if "target" not in body and any(k in body for k in ("macs", "mac", "targets")):
        raise erro(400, "no_target", 'as máquinas vão em "target": "all" ou uma lista de MACs')
    target = body.get("target", "all")
    if target != "all" and not isinstance(target, list):
        # uma string aqui seria percorrida letra a letra
        raise erro(400, "no_target", '"target" é "all" ou uma lista de MACs')
    macs = m.list_macs(image) if target == "all" else [m.normalize_mac(str(x)) for x in target]
    macs = [x for x in macs if m.valid_mac(x)]
    if not macs:
        raise erro(400, "no_target", "nenhuma máquina alvo")

    cid = m.enqueue(image, macs, command, body.get("args", ""), int(body.get("delay", 0)), by=p.name or p.kind)
    # `precontest` inclui travar a tela, e a trava só dura se o SERVIDOR souber
    # dela: o agente obedece o lockstate que vem no long-poll, então o
    # ensure_locked que o comando faz na máquina seria desfeito no ciclo
    # seguinte — travava por segundos e caía, sem ninguém entender.
    if command == "precontest":
        for mac in macs:
            m.set_lock(image, mac, True, p.name)
        publicar_evento(image, "machine.locked", {"machines": macs})
    for mac in macs:
        notify.wake_machine(image, mac)
    publicar_evento(image, "command.sent", {"id": cid, "command": command, "machines": len(macs)})
    return {"command_id": cid, "machines": len(macs)}


@router.get("/site-images/{image}/commands/{command_id}")
def command_status(
    image: str,
    command_id: str,
    p=Depends(auth.require_image_access(service_scope="commands:write")),
) -> dict:
    """Quem executou a ordem: por máquina, `acked`, `pending` (ainda vale e
    ninguém confirmou) ou `expired`. É a fonte da verdade; os eventos
    `command.acked`/`command.expired` são o aviso."""
    estado = command_log.estado(image, command_id)
    if estado is None:
        # também o comando de antes desta versão e o que já foi podado (7 dias)
        raise erro(404, "command_not_found", "comando não existe (ou já saiu do registro)")
    return estado


async def _lock(image: str, macs: list[str], locked: bool, by: str) -> dict:
    """Trava/destrava por DOIS caminhos ao mesmo tempo: grava o estado (que a
    própria tela consulta) e enfileira o comando (que o agente executa). Se um
    falhar, o outro resolve."""
    for mac in macs:
        m.set_lock(image, mac, locked, by)
    cid = m.enqueue(image, macs, "donottouch" if locked else "cantouch", by=by)
    for mac in macs:
        notify.wake_machine(image, mac)
    publicar_evento(image, "machine.locked" if locked else "machine.unlocked", {"machines": macs})
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

    O token vem na query quando a página foi aberta pelo link de sede, porque
    o EventSource não manda cabeçalhos. No console não vem token nenhum: o
    cookie de sessão acompanha por ser mesma origem.

    Aqui o cookie vale sem o cabeçalho X-NB-Console (que o EventSource também
    não consegue mandar). Não abre CSRF: é GET, não muda estado, e um
    EventSource de outra origem esbarra em CORS antes de ler qualquer coisa.
    """
    p = auth.identify(tk, image_id=image)
    if p is None:
        from ..services import sessions

        # EventSource não recebe cookie: não renova (ver auth.principal_de_link)
        p = sessions.resolve(request.cookies.get(sessions.COOKIE, ""), renovar=False)
    if p is not None and p.kind == "service" and not p.can_see_image(image):
        raise erro(403, "image_out_of_scope", "sem acesso a esta imagem")
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
