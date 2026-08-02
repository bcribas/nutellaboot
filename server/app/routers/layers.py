"""Camadas extras: fila de construção e anexação às imagens.

Fluxo: a API só enfileira; quem constrói é o worker (tools/nb3-layer-worker),
que roda como usuário comum — sem root. Ao terminar, o worker chama
/layerbuilds/{job}/attach para registrar a camada nas imagens escolhidas; o
banco continua sendo escrito só pela API.
"""

from __future__ import annotations

import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import auth, fsdb
from ..services import publish, store
from ..settings import settings

router = APIRouter(prefix="/api/v1")

PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}$")
ESTADOS = ("queue", "running", "done", "failed")


def _dir(estado: str):
    return settings.data_root / "layerbuilds" / estado


def _validate_packages(pacotes) -> list[str]:
    if not isinstance(pacotes, list) or not pacotes:
        raise HTTPException(400, "informe ao menos um pacote")
    for pkg in pacotes:
        if not PKG_RE.match(str(pkg)):
            raise HTTPException(400, f"nome de pacote inválido: {pkg}")
    return [str(x) for x in pacotes]


def _layer_url(saida: dict) -> str:
    """URL de download da camada: a publicada no servidor de arquivos quando
    existe, senão a servida pela máquina de gestão."""
    if saida.get("url"):
        return saida["url"]
    estado = publish.state(saida["file"])
    if estado and estado.get("status") == "done" and estado.get("url"):
        return estado["url"]
    return f"{settings.base_url}/blobs/{saida['file']}"


def _builds_for_image(image_id: str) -> int:
    """Conta as tentativas de build de uma imagem (todos os estados) — base da
    quota do auto-atendimento."""
    n = 0
    for estado in ESTADOS:
        d = _dir(estado)
        if not d.is_dir():
            continue
        for f in d.glob("*.json"):
            job = fsdb.read_json(f) or {}
            if job.get("image") == image_id or image_id in (job.get("attach_to") or []):
                n += 1
    return n


def _find(job_id: str) -> tuple[str, dict] | tuple[None, None]:
    for estado in ESTADOS:
        p = _dir(estado) / f"{job_id}.json"
        if p.is_file():
            return estado, fsdb.read_json(p)
    return None, None


@router.post("/layerbuilds", status_code=201)
async def create_build(body: dict, p=Depends(auth.require_admin)) -> dict:
    nome = str(body.get("name", "")).strip()
    if not NAME_RE.match(nome):
        raise HTTPException(400, "nome inválido para a camada")
    model = str(body.get("model", ""))
    if not store.model_exists(model):
        raise HTTPException(400, f"modelo '{model}' não existe")

    pacotes = _validate_packages(body.get("packages"))
    job = {
        "id": secrets.token_hex(6),
        "name": nome,
        "model": model,
        "packages": pacotes,
        "requested_by": p.name,
        "created_at": time.time(),
        "attach_to": body.get("attach_to") or [],
    }
    fsdb.write_json(_dir("queue") / f"{job['id']}.json", job)
    return job


@router.post("/site-images/{image}/layerbuilds", status_code=201)
async def create_build_for_image(
    image: str,
    body: dict,
    authorization: str | None = Header(None),
    x_nb_machine_key: str | None = Header(None),
) -> dict:
    """Build de camada da PRÓPRIA imagem. Aceito do admin (sem limite) ou do
    dono da imagem (token da imagem), respeitando a quota da imagem. A camada
    é anexada automaticamente a esta imagem quando fica pronta."""
    info = store.get_site_image(image)
    if info is None:
        raise HTTPException(404, "imagem não existe")

    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
    is_admin = bool(token) and auth.identify(token) and auth.identify(token).kind == "admin"
    if not is_admin and not auth.image_owner(image, token):
        raise HTTPException(401, "credencial inválida")

    if not is_admin:
        quota = int(info.get("build_quota", 0))
        usados = _builds_for_image(image)
        if usados >= quota:
            raise HTTPException(
                403, f"cota de builds da imagem esgotada ({usados}/{quota}); peça ao administrador"
            )

    nome = str(body.get("name", "")).strip()
    if not NAME_RE.match(nome):
        raise HTTPException(400, "nome inválido para a camada")
    pacotes = _validate_packages(body.get("packages"))

    job = {
        "id": secrets.token_hex(6),
        "name": nome,
        "model": info.get("model", ""),
        "packages": pacotes,
        "requested_by": "admin" if is_admin else f"image:{image}",
        "created_at": time.time(),
        "image": image,
        "attach_to": [image],  # anexa sozinho ao terminar
    }
    fsdb.write_json(_dir("queue") / f"{job['id']}.json", job)
    return {**job, "quota": None if is_admin else int(info.get("build_quota", 0))}


@router.get("/site-images/{image}/layerbuilds")
async def list_builds_for_image(
    image: str,
    authorization: str | None = Header(None),
    x_nb_machine_key: str | None = Header(None),
) -> dict:
    info = store.get_site_image(image)
    if info is None:
        raise HTTPException(404, "imagem não existe")
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
    is_admin = bool(token) and auth.identify(token) and auth.identify(token).kind == "admin"
    if not is_admin and not auth.image_owner(image, token):
        raise HTTPException(401, "credencial inválida")

    builds = []
    for estado in ESTADOS:
        d = _dir(estado)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            job = fsdb.read_json(f) or {}
            if job.get("image") == image or image in (job.get("attach_to") or []):
                builds.append({"id": job.get("id"), "name": job.get("name"),
                               "packages": job.get("packages"), "state": estado,
                               "output": job.get("output"), "error": job.get("error")})
    quota = int(info.get("build_quota", 0))
    return {"builds": builds, "used": len(builds), "quota": None if is_admin else quota}


@router.get("/layerbuilds")
async def list_builds(p=Depends(auth.require_admin)) -> dict:
    out = []
    for estado in ESTADOS:
        d = _dir(estado)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            job = fsdb.read_json(f) or {}
            out.append({**job, "state": estado})
    out.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return {"builds": out}


@router.get("/layerbuilds/{job_id}")
async def get_build(job_id: str, p=Depends(auth.require_admin)) -> dict:
    estado, job = _find(job_id)
    if job is None:
        raise HTTPException(404, "job não existe")
    log = _dir(estado) / f"{job_id}.log"
    return {
        **job,
        "state": estado,
        "log": log.read_text()[-8000:] if log.is_file() else "",
    }


@router.post("/layerbuilds/{job_id}/attach")
async def attach(job_id: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """Registra a camada pronta nas imagens indicadas. As camadas extras vão
    na frente do manifest, então têm prioridade sobre a imagem base."""
    estado, job = _find(job_id)
    if job is None:
        raise HTTPException(404, "job não existe")
    if estado != "done":
        raise HTTPException(400, f"job ainda não terminou (estado: {estado})")

    saida = job.get("output") or {}
    if not saida.get("md5") or not saida.get("file"):
        raise HTTPException(400, "job sem arquivo de saída")

    imagens = body.get("image_ids") or job.get("attach_to") or []
    if not imagens:
        raise HTTPException(400, "informe image_ids")

    camada = {
        "md5": saida["md5"],
        "file": saida["file"],
        # se a camada já foi publicada no servidor de arquivos, é de lá que as
        # máquinas baixam; senão, a própria máquina de gestão serve
        "cdn_url": _layer_url(saida),
        "size": saida.get("size"),
        "from_build": job_id,
    }
    aplicadas = []
    for image_id in imagens:
        if not store.site_image_exists(image_id):
            raise HTTPException(404, f"imagem '{image_id}' não existe")
        d = store.site_image_dir(image_id)
        with fsdb.locked(d):
            extras = fsdb.read_json(d / "layers-extra.json", []) or []
            extras = [c for c in extras if c.get("file") != camada["file"]]
            extras.insert(0, camada)
            fsdb.write_json(d / "layers-extra.json", extras)
        aplicadas.append(image_id)
    return {"ok": True, "layer": camada, "images": aplicadas}


@router.post("/site-images/{image}/layers")
async def add_layer(image: str, body: dict, p=Depends(auth.require_admin)) -> dict:
    """Registra uma camada já construída (caminho da VM: nb3-pack-upper).
    No nb2 isto era editar model.extra na mão, com o md5 copiado do
    terminal — e o arquivo ficava com a URL literal 'unk' quando ninguém
    lembrava de preencher."""
    if not store.site_image_exists(image):
        raise HTTPException(404, "imagem não existe")
    md5 = str(body.get("md5", "")).lower()
    arquivo = str(body.get("file", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise HTTPException(400, "md5 inválido")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", arquivo):
        raise HTTPException(400, "nome de arquivo inválido")

    blob = settings.data_root / "blobs" / arquivo
    camada = {
        "md5": md5,
        "file": arquivo,
        "cdn_url": body.get("cdn_url") or f"{settings.base_url}/blobs/{arquivo}",
        "size": body.get("size") or (blob.stat().st_size if blob.is_file() else None),
    }
    d = store.site_image_dir(image)
    with fsdb.locked(d):
        extras = fsdb.read_json(d / "layers-extra.json", []) or []
        extras = [c for c in extras if c.get("file") != arquivo]
        extras.insert(0, camada)
        fsdb.write_json(d / "layers-extra.json", extras)
    return {"ok": True, "layer": camada}


@router.delete("/site-images/{image}/layers/{file}", status_code=204)
async def detach(image: str, file: str, p=Depends(auth.require_admin)) -> None:
    d = store.site_image_dir(image)
    with fsdb.locked(d):
        extras = fsdb.read_json(d / "layers-extra.json", []) or []
        fsdb.write_json(d / "layers-extra.json", [c for c in extras if c.get("file") != file])


@router.get("/site-images/{image}/layers")
async def list_layers(image: str, p=Depends(auth.require_image_access())) -> dict:
    return {
        "extra": fsdb.read_json(store.site_image_dir(image) / "layers-extra.json", []) or [],
        "all": store.site_image_layers(image),
    }
