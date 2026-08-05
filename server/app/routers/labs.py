"""Painel da frota: todas as sedes de quem administra, numa tela só.

O painel por sede (`/hotconfig/`) responde "como está a MINHA sala agora".
Estas duas rotas respondem outra pergunta — "o que está acontecendo no
conjunto, e como ajo num recorte dele" — e por isso não são as mesmas com mais
linhas: o desenho inteiro (payload enxuto, sondagem em vez de evento) sai da
conta de 1890 máquinas, que está em `services/labs.py`.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from .. import auth
from ..services import fleet_report, labs, labs_series, ownership, store
from ..services import machines as m
from .machines import comandos_bloqueados, publicar_evento

router = APIRouter(prefix="/api/v1")


def _principal_da_frota(request: Request, tk: str = ""):
    """Quem pode LER a frota: console (admin/sub-admin) e a chave de serviço
    com `labs:read` — a chave compartilhável do dashboard. Ela nunca chega a
    comando (require_console recusa serviço) nem ao hotconfig (machines exige
    `machines:read`, que não é concedido) — só leitura de agregados."""
    p = auth.principal_de_link(request, tk)
    if p is None:
        raise HTTPException(401, "credencial ausente ou inválida")
    if p.kind in ("admin", "subadmin"):
        return p
    if p.kind == "service" and "labs:read" in p.scopes:
        return p
    raise HTTPException(401, "credencial ausente ou inválida")


@router.get("/labs")
async def visao_geral(
    request: Request,
    dias: float = Query(labs.DIAS_PADRAO, ge=0, le=3650),
    format: str = Query("json", pattern="^(json|csv)$"),
    tk: str = Query(""),
):
    """Uma linha por sede: quantas máquinas, quantas ativas na janela, quantas
    apareceram nela, e o estado de agora.

    `dias` responde "quantas máquinas de cada sede rodaram nos últimos X dias".
    São DOIS números porque a pergunta tem duas leituras: `active` é quem teve
    contato dentro da janela e `new` é quem foi visto pela primeira vez nela.

    `first_seen` é quando ESTE servidor viu aquele MAC pela primeira vez, não o
    primeiro boot da máquina na vida — recriar o `data/` reinicia a conta.

    **Credencial de link**: o cookie vale aqui SEM `X-NB-Console`, porque o
    botão de baixar o CSV é um `<a download>` e um `<a>` não manda cabeçalho —
    era 401 na cara de quem clicava. É a mesma exceção da prévia do wallpaper,
    do SSE e do relatório por sede: GET, não muda estado, e sem CORS uma página
    de outro site não lê a resposta. O `POST /commands` continua exigindo o
    cabeçalho, e é o que importa: lá se desliga a frota.
    """
    p = _principal_da_frota(request, tk)
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
        # a mesma regra da rota por sede: a trava do precontest só dura se o
        # servidor gravar o estado — o agente obedece o lockstate do long-poll
        if command == "precontest":
            for mac in macs:
                m.set_lock(image, mac, True, p.name)
            publicar_evento(image, "machine.locked", {"machines": macs})
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


@router.get("/labs/series")
async def serie_da_frota(
    request: Request,
    since: float = Query(0, ge=0),
    until: float = Query(0, ge=0),
    site: str = Query(""),
    tk: str = Query(""),
) -> dict:
    """O histórico da frota (ou de uma sede, com `site=`), gravado pelo
    servidor a um ponto por minuto. `since`/`until` recortam — "só o período
    da competição importa". A resposta tem teto de pontos (downsample).

    Aceita a chave compartilhada (`labs:read`) por `?tk=` ou Bearer, além do
    console. A visibilidade filtra os pontos, e o total é recalculado do
    subconjunto — o total bruto vazaria a contagem das sedes alheias.
    """
    p = _principal_da_frota(request, tk)
    try:
        pontos = labs_series.serie(p, since=since, until=until, site=site)
    except KeyError:
        raise HTTPException(404, "imagem não existe")
    return {"points": pontos, "site": site or None}


@router.get("/labs/inventory")
async def inventario_da_frota(request: Request, tk: str = Query("")) -> dict:
    """De que é feito o parque: processadores, RAM instalada, editores em uso
    e os discos mais cheios. Console (sub-admin vê só as sedes dele) e a chave
    compartilhada; aceita o cookie sem cabeçalho pela mesma razão do resumo —
    é GET de leitura para telas que sondam."""
    return labs.inventario(_principal_da_frota(request, tk))


# --- o relatório da frota ----------------------------------------------------
#
# Só a administração. O artefato é UM arquivo com a frota inteira dentro;
# gerá-lo por dono custaria os ~118 s por pessoa e abriria um caminho para a
# sede de alguém entrar no relatório de outro. Sub-admin continua com o
# relatório da sede dele, que já existe e é barato.


@router.get("/labs/report")
async def estado_do_relatorio(p=Depends(auth.require_admin)) -> dict:
    return fleet_report.estado()


@router.post("/labs/report", status_code=202)
async def gerar_relatorio(
    body: dict | None = None,
    dias: float = Query(7, gt=0, le=3650),
    p=Depends(auth.require_admin),
) -> dict:
    """Dispara a passada. Responde 202 e o estado — quem pergunta se ficou
    pronto é a tela, na sondagem de 5 s que ela já faz.

    Pedir de novo enquanto uma anda NÃO é erro: a tela sonda, e duas abas
    abertas fariam a segunda receber um 409 que ninguém pediu. `started` diz
    qual das duas foi a que disparou.

    `excluir` (no corpo) tira sedes do relatório — a de teste inflaria o
    perfil nacional. Os ids são validados ANTES de virarem argumento de
    subprocesso, e a escolha fica gravada no estado: a próxima geração vem
    pré-marcada igual.
    """
    corpo = body or {}
    excluir = corpo.get("excluir") or []
    if not isinstance(excluir, list):
        raise HTTPException(400, "excluir deve ser uma lista de ids")
    ruins = [x for x in excluir if not store.site_image_exists(str(x))]
    if ruins:
        raise HTTPException(400, f"sedes desconhecidas: {', '.join(map(str, ruins))}")
    if "dias" in corpo:
        dias = float(corpo["dias"])
        if not (0 < dias <= 3650):
            raise HTTPException(400, "dias fora do intervalo")

    ate = time.time()
    iniciou = fleet_report.agendar(ate - dias * 86400, ate, tuple(str(x) for x in excluir))
    return {**fleet_report.estado(), "started": iniciou}


@router.get("/labs/report/{nome}")
async def baixar_do_relatorio(nome: str, request: Request):
    """Os arquivos gerados.

    `principal_de_link` porque são `<a download>`, que não manda cabeçalho — foi
    exatamente assim que o CSV da frota deu 401 na cara de quem clicava. E o
    `nome` sai de uma LISTA FECHADA: é caminho vindo da URL indo para o disco, e
    o diretório vizinho tem as chaves de todas as sedes.
    """
    p = auth.principal_de_link(request)
    if p is None or p.kind != "admin":
        raise HTTPException(401, "credencial ausente ou inválida")
    caminho = fleet_report.caminho_de(nome)
    if caminho is None:
        raise HTTPException(404, "arquivo não existe")
    return FileResponse(
        caminho,
        media_type=fleet_report.TIPOS.get(caminho.suffix, "application/octet-stream"),
        filename=nome,
    )
