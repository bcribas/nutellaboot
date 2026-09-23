"""Construções de camada: onde os jobs moram no disco e quem enxerga cada um.

O roteador de camadas, o catálogo de camadas dos modelos e a conta de uso dos
sub-admins precisam das mesmas contas, e serviço não importa roteador: por isso
vivem aqui, e não em `routers/layers.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .. import fsdb
from ..settings import settings
from . import publish, store

ESTADOS = ("queue", "running", "done", "failed")


def pasta(estado: str) -> Path:
    return settings.data_root / "layerbuilds" / estado


def todos() -> Iterator[tuple[str, dict]]:
    """(estado, job) de todas as construções, em qualquer estado."""
    for estado in ESTADOS:
        d = pasta(estado)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            job = fsdb.read_json(f) or {}
            if job:
                yield estado, job


def achar(job_id: str) -> tuple[str, dict] | tuple[None, None]:
    for estado in ESTADOS:
        p = pasta(estado) / f"{job_id}.json"
        if p.is_file():
            return estado, fsdb.read_json(p)
    return None, None


def contar_da_imagem(image_id: str) -> int:
    """Tentativas de construção de uma imagem (todos os estados): a base da cota
    do auto-atendimento."""
    return sum(
        1
        for _, job in todos()
        if job.get("image") == image_id or image_id in (job.get("attach_to") or [])
    )


def contar_do_dono(owner: str) -> int:
    """Cota de construção do sub-admin: conta tentativas, não sucessos. Contar só
    as que deram certo faria uma fila de construções quebradas sair de graça."""
    return sum(1 for _, job in todos() if job.get("owner") == owner)


def visivel(p, job: dict) -> bool:
    """O sub-admin vê as construções que pediu e as que caem nas imagens dele:
    uma construção alheia pode anexar numa imagem dele se o admin quiser, e
    nesse caso ele precisa acompanhar o resultado."""
    if p.kind == "admin":
        return True
    if job.get("owner") == p.owner:
        return True
    alvos = list(job.get("attach_to") or []) + ([job["image"]] if job.get("image") else [])
    return any(store.site_image_owner(i) == p.owner for i in alvos)


def url_da_camada(saida: dict) -> str:
    """URL de download da camada: a publicada no servidor de arquivos quando
    existe, senão a servida pela máquina de gestão."""
    if saida.get("url"):
        return saida["url"]
    estado = publish.state(saida["file"])
    if estado and estado.get("status") == "done" and estado.get("url"):
        return estado["url"]
    return f"{settings.base_url}/blobs/{saida['file']}"


def disponivel(saida: dict) -> bool:
    """A camada ainda tem de onde ser baixada: blob no disco ou publicada.

    Sem isto, anexar uma construção antiga cujo blob já foi apagado (e que nunca
    foi publicada) gera um manifest apontando para /blobs/<arquivo> que dá 404:
    a sala inteira para no download, com o manifest parecendo certo.
    """
    arquivo = str(saida.get("file", ""))
    if not arquivo:
        return False
    if saida.get("url"):
        return True
    estado = publish.state(arquivo)
    if estado and estado.get("status") == "done" and estado.get("url"):
        return True
    return (settings.data_root / "blobs" / arquivo).is_file()
