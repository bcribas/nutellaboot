"""O pendrive de boot: estado, geração e download.

Três coisas para baixar, e a ordem em que as telas as mostram é de propósito:
a imagem genérica (uma só, sem segredo dentro), o `nutellaboot.conf` da sala
(quatro linhas, com a chave de boot) e — para quem prefere não copiar arquivo
nenhum — a imagem já configurada para a sala.

Os downloads não vão para `/blobs`: aquilo é `StaticFiles` sem autenticação, e
a imagem da sala carrega a chave de boot dentro.
"""

from __future__ import annotations

import gzip
import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse

from .. import auth
from ..services import store, usb

router = APIRouter(prefix="/api/v1")


# Quanto se lê do disco por vez ao compactar na hora.
BLOCO = 4 * 1024 * 1024


def _gzip_em_pedacos(caminho: Path):
    """Gerador SÍNCRONO de propósito: o Starlette itera geradores síncronos
    numa thread do pool, então os ~4 s de CPU do gzip não travam o event loop
    do worker único (invariante 2). Com um gerador `async` eles travariam."""
    buf = io.BytesIO()
    gz = gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6)
    with open(caminho, "rb") as f:
        while pedaco := f.read(BLOCO):
            gz.write(pedaco)
            saida = buf.getvalue()
            if saida:
                buf.seek(0)
                buf.truncate()
                yield saida
    gz.close()
    yield buf.getvalue()


def _entregar(estado: dict):
    """Redireciona para o servidor de arquivos, ou compacta e transmite daqui.

    O redirecionamento é a saída normal em produção: são 206 MB que deixam de
    sair da máquina que atende o boot de 1600 computadores. Ele só vale quando
    a cópia publicada corresponde a ESTA construção — `public_url` já não é
    preenchida quando não corresponde (services/usb.py).

    A outra saída é para quando não há cópia lá (publicação desligada, envio
    falhado, ou publicada e velha). Ela compacta na hora, e por isso não tem
    `Content-Length`: o navegador baixa sem porcentagem. É o caminho de
    exceção; guardar um `.gz` ao lado de cada `.img` custaria ~11 GB para
    servir bem um caso que quase não acontece.
    """
    if estado.get("status") != "done" or not estado.get("file"):
        raise HTTPException(404, "imagem do pendrive ainda não foi gerada")

    url = usb.url_publicada_atual(estado)
    if url:
        return RedirectResponse(url, status_code=302)

    nome = estado["file"]
    caminho = usb.file_path(nome)
    if not caminho.is_file():
        raise HTTPException(404, "imagem do pendrive ainda não foi gerada")
    return StreamingResponse(
        _gzip_em_pedacos(caminho),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{nome}.gz"'},
    )


# --- visão da administração ---


@router.get("/usb")
async def estado_geral(p=Depends(auth.require_admin)) -> dict:
    """Tudo que a seção "Pendrive" do console mostra."""
    return {
        "kernel": usb.kernel_state(),
        "generic": usb.generic_state(),
        "auto_generate": bool(usb.conf().get("auto_generate", True)),
        "images": [
            {"id": i["id"], "fullname": i.get("fullname", ""), **usb.image_state(i["id"])}
            for i in store.list_site_images()
        ],
    }


@router.post("/usb/generic", status_code=202)
async def gerar_generica(p=Depends(auth.require_admin)) -> dict:
    usb.agendar_generica(forcado=True)
    return usb.generic_state()


# --- por sala ---


@router.get("/site-images/{image}/usb")
async def estado_da_sala(image: str, p=Depends(auth.require_image_access())) -> dict:
    return {
        "kernel": usb.kernel_state(),
        "generic": usb.generic_state(),
        "image": usb.image_state(image),
    }


@router.post("/site-images/{image}/usb", status_code=202)
async def gerar_da_sala(image: str, p=Depends(auth.require_image_access())) -> dict:
    """Gera (ou regera) a imagem já configurada para esta sala.

    O dono da sede pode disparar: é o pendrive dele, e regerar sobrescreve o
    mesmo arquivo — não acumula nada.
    """
    usb.agendar(image, forcado=True)
    return usb.image_state(image)


# --- downloads (o navegador carrega sozinho: não há cabeçalho para mandar) ---


@router.get("/site-images/{image}/usb/conf")
async def baixar_conf(image: str, request: Request, tk: str = Query("")):
    """O `nutellaboot.conf` da sala, para copiar por cima do que está no
    pendrive gravado com a imagem genérica."""
    p = auth.principal_de_link(request, tk, image)
    if p is None or not p.can_see_image(image):
        raise HTTPException(401, "credencial ausente ou inválida")
    if not store.site_image_exists(image):
        raise HTTPException(404, "imagem não existe")
    return PlainTextResponse(
        usb.conf_text(image),
        headers={"Content-Disposition": 'attachment; filename="nutellaboot.conf"'},
    )


@router.get("/site-images/{image}/usb/image")
async def baixar_da_sala(image: str, request: Request, tk: str = Query("")):
    p = auth.principal_de_link(request, tk, image)
    if p is None or not p.can_see_image(image):
        raise HTTPException(401, "credencial ausente ou inválida")
    return _entregar(usb.image_state(image))


@router.get("/usb/generic/image")
async def baixar_generica(request: Request, tk: str = Query(""), id: str = Query("")):
    """A imagem genérica.

    Não leva segredo nenhum dentro — é a mesma para todas as sedes —, mas ainda
    assim pede credencial: quando não há cópia no servidor de arquivos, são
    centenas de MB saindo da máquina que responde à API durante a prova. Do
    console vale o cookie; da tela de uma sede, `?id=&tk=`, que é o que ela já
    tem na URL.
    """
    p = auth.principal_de_link(request, tk, id or None)
    if p is None:
        raise HTTPException(401, "credencial ausente ou inválida")
    if p.kind == "image" and id and not p.can_see_image(id):
        raise HTTPException(401, "credencial ausente ou inválida")
    return _entregar(usb.generic_state())
