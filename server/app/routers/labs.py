"""Painel da frota: todas as sedes de quem administra, numa tela só.

O painel por sede (`/hotconfig/`) responde "como está a MINHA sala agora".
Estas duas rotas respondem outra pergunta — "o que está acontecendo no
conjunto, e como ajo num recorte dele" — e por isso não são as mesmas com mais
linhas: o desenho inteiro (payload enxuto, sondagem em vez de evento) sai da
conta de 1890 máquinas, que está em `services/labs.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import auth
from ..services import labs
from ..services import machines as m
from ..services import ownership
from .machines import comandos_bloqueados, publicar_evento

router = APIRouter(prefix="/api/v1")


@router.get("/labs")
async def visao_geral(
    dias: float = Query(labs.DIAS_PADRAO, ge=0, le=3650),
    format: str = Query("json", pattern="^(json|csv)$"),
    p=Depends(auth.require_console),
):
    """Uma linha por sede: quantas máquinas, quantas ativas na janela, quantas
    apareceram nela, e o estado de agora.

    `dias` responde "quantas máquinas de cada sede rodaram nos últimos X dias".
    São DOIS números porque a pergunta tem duas leituras: `active` é quem teve
    contato dentro da janela e `new` é quem foi visto pela primeira vez nela.

    `first_seen` é quando ESTE servidor viu aquele MAC pela primeira vez, não o
    primeiro boot da máquina na vida — recriar o `data/` reinicia a conta.
    """
    linhas = labs.resumo(p, dias=dias)
    if format == "csv":
        return PlainTextResponse(
            labs.csv_de(linhas),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="frota.csv"'},
        )
    return {"sites": linhas, "days": dias}


@router.post("/commands")
async def comandar_frota(body: dict, p=Depends(auth.require_console)) -> dict:
    """Um comando num recorte que atravessa sedes.

    `{"command": "...", "targets": {"26brbr": "all", "26spsp": ["52-54-…"]}}`

    Uma requisição e não uma por sede: com 54 sedes, metade falhando no
    navegador vira meia frota comandada sem ninguém saber quais. Aqui cada sede
    entra no relatório com o que aconteceu, e uma recusada não impede as outras.

    As regras não são reescritas aqui: dono pelo `ownership`, cadeado do modelo
    pelo mesmo `comandos_bloqueados` do painel por sede.
    """
    command = str(body.get("command", ""))
    if command not in m.ALLOWED_COMMANDS:
        raise HTTPException(400, f"comando não permitido: {command}")
    alvos = body.get("targets")
    if not isinstance(alvos, dict) or not alvos:
        raise HTTPException(400, "esperava targets: {sede: 'all' | [macs]}")

    resultados: dict[str, dict] = {}
    for image, quais in alvos.items():
        image = str(image)
        if not ownership.can_manage_site_image(p, image):
            # 404 e não 403, como no resto do console: um 403 confirmaria que o
            # nome existe, e nomes são livres por ordem de chegada
            resultados[image] = {"error": "imagem não existe", "status": 404}
            continue
        bloqueados = comandos_bloqueados(image, is_admin=(p.kind == "admin"))
        if command in bloqueados:
            resultados[image] = {
                "error": f"{bloqueados[command]} está bloqueado pela organização da maratona",
                "status": 403,
            }
            continue

        macs = m.list_macs(image) if quais == "all" else [m.normalize_mac(x) for x in quais or []]
        macs = [x for x in macs if m.valid_mac(x)]
        if not macs:
            resultados[image] = {"error": "nenhuma máquina alvo", "status": 400}
            continue

        cid = m.enqueue(image, macs, command, str(body.get("args", "")), int(body.get("delay", 0)))
        for mac in macs:
            from ..services.notify import notify

            notify.wake_machine(image, mac)
        publicar_evento(image, "command.sent", {"id": cid, "command": command, "machines": len(macs)})
        resultados[image] = {"command_id": cid, "machines": len(macs)}

    return {
        "results": resultados,
        "machines": sum(r.get("machines", 0) for r in resultados.values()),
        "failed": sorted(k for k, r in resultados.items() if r.get("error")),
    }
