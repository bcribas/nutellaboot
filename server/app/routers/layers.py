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

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from .. import auth, fsdb
from ..services import ownership, publish, store
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


def _builds_for_owner(owner: str) -> int:
    """Cota de build do sub-admin: conta tentativas, não sucessos. Contar só
    os que deram certo faria uma fila de builds quebrados sair de graça."""
    n = 0
    for estado in ESTADOS:
        d = _dir(estado)
        if not d.is_dir():
            continue
        for f in d.glob("*.json"):
            if (fsdb.read_json(f) or {}).get("owner") == owner:
                n += 1
    return n


def _find(job_id: str) -> tuple[str, dict] | tuple[None, None]:
    for estado in ESTADOS:
        p = _dir(estado) / f"{job_id}.json"
        if p.is_file():
            return estado, fsdb.read_json(p)
    return None, None


@router.post("/layerbuilds", status_code=201)
async def create_build(body: dict, p=Depends(auth.require_console)) -> dict:
    nome = str(body.get("name", "")).strip()
    if not NAME_RE.match(nome):
        raise HTTPException(400, "nome inválido para a camada")
    model = str(body.get("model", ""))
    if not ownership.can_manage_model(p, model):
        raise HTTPException(404, "modelo não existe")

    if p.kind != "admin":
        limite = ownership.quota(p, "builds")
        usados = _builds_for_owner(p.owner)
        if limite is not None and usados >= limite:
            raise HTTPException(403, f"cota de builds esgotada ({usados}/{limite})")

    destinos = [str(i) for i in (body.get("attach_to") or [])]
    for image_id in destinos:
        if not ownership.can_manage_site_image(p, image_id):
            raise HTTPException(404, f"imagem '{image_id}' não existe")

    pacotes = _validate_packages(body.get("packages"))
    job = {
        "id": secrets.token_hex(6),
        "name": nome,
        "model": model,
        "packages": pacotes,
        "requested_by": p.name,
        "owner": p.owner,
        "created_at": time.time(),
        "attach_to": destinos,
    }
    fsdb.write_json(_dir("queue") / f"{job['id']}.json", job)
    return job


@router.post("/site-images/{image}/layerbuilds", status_code=201)
async def create_build_for_image(
    image: str,
    body: dict,
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Build de camada da PRÓPRIA imagem. Aceito do admin (sem limite) ou do
    dono da imagem (token da imagem), respeitando a quota da imagem. A camada
    é anexada automaticamente a esta imagem quando fica pronta."""
    sem_cota = _acesso_a_imagem(image, request, authorization)
    info = store.get_site_image(image)
    if info is None:
        raise HTTPException(404, "imagem não existe")

    if not sem_cota:
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
        "requested_by": "console" if sem_cota else f"image:{image}",
        "created_at": time.time(),
        "image": image,
        "attach_to": [image],  # anexa sozinho ao terminar
    }
    fsdb.write_json(_dir("queue") / f"{job['id']}.json", job)
    return {**job, "quota": None if sem_cota else int(info.get("build_quota", 0))}


@router.get("/site-images/{image}/layerbuilds")
async def list_builds_for_image(
    image: str,
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    sem_cota = _acesso_a_imagem(image, request, authorization)
    info = store.get_site_image(image)
    if info is None:
        raise HTTPException(404, "imagem não existe")

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
    return {"builds": builds, "used": len(builds), "quota": None if sem_cota else quota}


@router.get("/layerbuilds")
async def list_builds(p=Depends(auth.require_console)) -> dict:
    out = []
    for estado in ESTADOS:
        d = _dir(estado)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            job = fsdb.read_json(f) or {}
            if not _job_visivel(p, job):
                continue
            out.append({**job, "state": estado})
    out.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return {"builds": out}


@router.get("/layerbuilds/{job_id}")
async def get_build(job_id: str, p=Depends(auth.require_console)) -> dict:
    estado, job = _find(job_id)
    if job is None or not _job_visivel(p, job):
        raise HTTPException(404, "job não existe")
    log = _dir(estado) / f"{job_id}.log"
    return {
        **job,
        "state": estado,
        "log": log.read_text()[-8000:] if log.is_file() else "",
    }


@router.post("/layerbuilds/{job_id}/attach")
async def attach(job_id: str, body: dict, p=Depends(auth.require_console)) -> dict:
    """Registra a camada pronta nas imagens indicadas. As camadas extras vão
    na frente do manifest, então têm prioridade sobre a imagem base."""
    estado, job = _find(job_id)
    if job is None or not _job_visivel(p, job):
        raise HTTPException(404, "job não existe")
    if estado != "done":
        raise HTTPException(400, f"job ainda não terminou (estado: {estado})")

    saida = job.get("output") or {}
    # o worker é confiável, mas o que sai daqui vira linha de manifest de boot:
    # mesma validação de `add_layer`, não uma mais frouxa por vir de dentro
    if not re.fullmatch(r"[0-9a-f]{32}", str(saida.get("md5", ""))):
        raise HTTPException(400, "job sem md5 válido")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", str(saida.get("file", ""))):
        raise HTTPException(400, "job sem arquivo de saída válido")

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
        if not ownership.can_manage_site_image(p, image_id):
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
async def add_layer(image: str, body: dict, p=Depends(auth.require_console)) -> dict:
    """Registra uma camada já construída (caminho da VM: nb3-pack-upper).
    No nb2 isto era editar model.extra na mão, com o md5 copiado do
    terminal — e o arquivo ficava com a URL literal 'unk' quando ninguém
    lembrava de preencher."""
    if not ownership.can_manage_site_image(p, image):
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
async def detach(image: str, file: str, p=Depends(auth.require_console)) -> None:
    if not ownership.can_manage_site_image(p, image):
        raise HTTPException(404, "imagem não existe")
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


def _acesso_a_imagem(image: str, request: Request, authorization: str | None) -> bool:
    """Quem pode pedir build desta imagem: admin, o sub-admin dono dela, ou o
    próprio token da imagem (é o que o configureitor usa). Devolve True quando
    o pedido não gasta a cota — ela existe para conter o auto-atendimento, não
    quem administra a imagem.

    Passa por `auth.principal` como todo o resto. Enquanto lia `Authorization`
    na mão, o console inteiro (que autentica por cookie desde a sessão) levava
    401 aqui: o botão de montar camada por imagem não funcionava para ninguém.
    """
    p = auth.principal(request, authorization, image_id=image)
    if p is None:
        raise HTTPException(401, "credencial inválida")
    if p.kind in ("admin", "subadmin"):
        if not ownership.can_manage_site_image(p, image):
            raise HTTPException(404, "imagem não existe")
        return True
    if p.kind == "image" and p.name == image:
        return False
    raise HTTPException(401, "credencial inválida")


def _job_visivel(p, job: dict) -> bool:
    """O sub-admin vê os builds que pediu e os que caem nas imagens dele — um
    build alheio pode anexar numa imagem dele se o admin quiser, e nesse caso
    ele precisa acompanhar o resultado."""
    if p.kind == "admin":
        return True
    if job.get("owner") == p.owner:
        return True
    alvos = list(job.get("attach_to") or []) + ([job["image"]] if job.get("image") else [])
    return any(store.site_image_owner(i) == p.owner for i in alvos)
