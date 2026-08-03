"""Relatório da sede por período.

Abre em outra aba a partir do hotconfig, então aceita a credencial na query
(`?tk=`) como os outros links que o navegador carrega sozinho — é GET e não
muda estado.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from .. import auth
from ..services import report, store

router = APIRouter(prefix="/api/v1")

# um mês: é a ordem de grandeza do que a telemetria guarda por máquina
MAX_JANELA = 31 * 24 * 3600


@router.get("/site-images/{image}/report")
async def relatorio(
    image: str,
    request: Request,
    since: float = Query(0, ge=0),
    until: float = Query(0, ge=0),
    format: str = Query("html", pattern="^(html|json)$"),
    lang: str = Query("pt", pattern="^(pt|en|es)$"),
    tk: str = Query(""),
):
    p = auth.principal_de_link(request, tk, image)
    if p is None or not p.can_see_image(image):
        raise HTTPException(401, "credencial ausente ou inválida")
    if not store.site_image_exists(image):
        raise HTTPException(404, "imagem não existe")

    agora = time.time()
    until = until or agora
    since = since or (until - 4 * 3600)
    if until < since:
        raise HTTPException(400, "o fim do período é anterior ao começo")
    if until - since > MAX_JANELA:
        raise HTTPException(400, f"período longo demais (máximo {MAX_JANELA // 86400} dias)")

    dados = report.coletar(image, since, until)
    if format == "json":
        # a série de cada máquina é o grosso do payload e só serve para
        # desenhar: quem pede JSON quer os números agregados
        return {**dados, "machines": [{**m, "serie": len(m["serie"])} for m in dados["machines"]]}
    return HTMLResponse(report.html_report(dados, lang))
