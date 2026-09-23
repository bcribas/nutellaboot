"""Camadas extras: fila de construção e anexação às imagens e ao modelo.

Fluxo: a API só enfileira; quem constrói é o worker (tools/nb3-layer-worker),
que roda como usuário comum — sem root. Ao terminar, o worker anexa a camada às
imagens escolhidas no pedido; anexar depois (a outras imagens, ou ao modelo
inteiro) é por /layerbuilds/{job}/attach.
"""

from __future__ import annotations

import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from .. import auth, fsdb
from ..services import layerbuilds, ownership, store
from ..settings import settings

router = APIRouter(prefix="/api/v1")

PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}$")


def _validate_packages(pacotes) -> list[str]:
    if not isinstance(pacotes, list) or not pacotes:
        raise HTTPException(400, "informe ao menos um pacote")
    for pkg in pacotes:
        if not PKG_RE.match(str(pkg)):
            raise HTTPException(400, f"nome de pacote inválido: {pkg}")
    return [str(x) for x in pacotes]


def _exigir_cota_do_dono(p) -> None:
    """A cota de construções do sub-admin vale para TODO pedido dele, por modelo
    ou por imagem. A construção por imagem dispensava a cota e saía sem `owner`,
    então nem entrava na conta: era a porta dos fundos da cota."""
    if p.kind == "admin":
        return
    limite = ownership.quota(p, "builds")
    usados = layerbuilds.contar_do_dono(p.owner)
    if limite is not None and usados >= limite:
        raise HTTPException(403, f"cota de construções esgotada ({usados}/{limite})")


@router.post("/layerbuilds", status_code=201)
async def create_build(body: dict, p=Depends(auth.require_console)) -> dict:
    nome = str(body.get("name", "")).strip()
    if not NAME_RE.match(nome):
        raise HTTPException(400, "nome inválido para a camada")
    model = str(body.get("model", ""))
    if not ownership.can_manage_model(p, model):
        raise HTTPException(404, "modelo não existe")

    _exigir_cota_do_dono(p)

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
    fsdb.write_json(layerbuilds.pasta("queue") / f"{job['id']}.json", job)
    return job


@router.post("/site-images/{image}/layerbuilds", status_code=201)
async def create_build_for_image(
    image: str,
    body: dict,
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Construção de camada da PRÓPRIA imagem, anexada a ela sozinha quando
    fica pronta. O admin não tem cota; o sub-admin dono gasta a cota dele (a
    mesma do pedido por modelo); o token da imagem gasta a cota da imagem."""
    p = _acesso_a_imagem(image, request, authorization)
    info = store.get_site_image(image)
    if info is None:
        raise HTTPException(404, "imagem não existe")

    quota_da_imagem = None
    if p.kind == "image":
        quota_da_imagem = int(info.get("build_quota", 0))
        usados = layerbuilds.contar_da_imagem(image)
        if usados >= quota_da_imagem:
            raise HTTPException(
                403,
                f"cota de construções da imagem esgotada ({usados}/{quota_da_imagem}); peça ao administrador",
            )
    else:
        _exigir_cota_do_dono(p)

    nome = str(body.get("name", "")).strip()
    if not NAME_RE.match(nome):
        raise HTTPException(400, "nome inválido para a camada")
    pacotes = _validate_packages(body.get("packages"))

    job = {
        "id": secrets.token_hex(6),
        "name": nome,
        "model": info.get("model", ""),
        "packages": pacotes,
        "requested_by": f"image:{image}" if p.kind == "image" else p.name,
        "created_at": time.time(),
        "image": image,
        "attach_to": [image],  # anexa sozinho ao terminar
    }
    if p.kind != "image":
        job["owner"] = p.owner
    fsdb.write_json(layerbuilds.pasta("queue") / f"{job['id']}.json", job)
    return {**job, "quota": quota_da_imagem}


@router.get("/site-images/{image}/layerbuilds")
async def list_builds_for_image(
    image: str,
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    p = _acesso_a_imagem(image, request, authorization)
    info = store.get_site_image(image)
    if info is None:
        raise HTTPException(404, "imagem não existe")

    builds = []
    for estado, job in layerbuilds.todos():
        if job.get("image") == image or image in (job.get("attach_to") or []):
            builds.append({"id": job.get("id"), "name": job.get("name"),
                           "packages": job.get("packages"), "state": estado,
                           "output": job.get("output"), "error": job.get("error")})
    quota = int(info.get("build_quota", 0))
    return {"builds": builds, "used": len(builds), "quota": quota if p.kind == "image" else None}


def _imagens_por_arquivo(p) -> dict[str, list[str]]:
    """Arquivo → imagens (visíveis a quem pergunta) que têm a camada entre as
    próprias. Montado uma vez por requisição: a lista de construções pergunta
    isso para cada linha."""
    imagens = store.list_site_images() if p.kind == "admin" else store.list_site_images(owner=p.owner)
    por_arquivo: dict[str, list[str]] = {}
    for img in imagens:
        extras = fsdb.read_json(store.site_image_dir(img["id"]) / "layers-extra.json", []) or []
        for c in extras:
            por_arquivo.setdefault(str(c.get("file", "")), []).append(img["id"])
    return por_arquivo


@router.get("/layerbuilds")
async def list_builds(p=Depends(auth.require_console)) -> dict:
    por_arquivo = _imagens_por_arquivo(p)
    do_modelo: dict[str, set[str]] = {}
    out = []
    for estado, job in layerbuilds.todos():
        if not layerbuilds.visivel(p, job):
            continue
        item = {**job, "state": estado}
        saida = job.get("output") or {}
        if estado == "done" and saida.get("file"):
            modelo = str(job.get("model", ""))
            if modelo not in do_modelo:
                tpl = store.get_model(modelo) or {}
                do_modelo[modelo] = {str(c.get("file", "")) for c in tpl.get("layers", [])}
            item["attached"] = {
                "images": sorted(por_arquivo.get(saida["file"], [])),
                "model": saida["file"] in do_modelo[modelo],
            }
            item["available"] = layerbuilds.disponivel(saida)
        out.append(item)
    out.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return {"builds": out}


@router.get("/layerbuilds/{job_id}")
async def get_build(job_id: str, p=Depends(auth.require_console)) -> dict:
    estado, job = layerbuilds.achar(job_id)
    if job is None or not layerbuilds.visivel(p, job):
        raise HTTPException(404, "job não existe")
    log = layerbuilds.pasta(estado) / f"{job_id}.log"
    return {
        **job,
        "state": estado,
        "log": log.read_text()[-8000:] if log.is_file() else "",
    }


@router.post("/layerbuilds/{job_id}/attach")
async def attach(job_id: str, body: dict, p=Depends(auth.require_console)) -> dict:
    """Anexa a camada pronta às imagens indicadas (`image_ids`) e/ou ao modelo
    da construção (`model: true`). As camadas extras vão na frente do manifest,
    então têm prioridade sobre a imagem base.

    O modelo é SEMPRE o da construção: o worker instala os pacotes em cima das
    camadas daquele modelo, e a camada leva o `dpkg/status` dele. Em outro
    modelo, com outra base, ela sobreporia o estado do apt com o de uma base
    alheia.
    """
    estado, job = layerbuilds.achar(job_id)
    if job is None or not layerbuilds.visivel(p, job):
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
    if not layerbuilds.disponivel(saida):
        raise HTTPException(
            409, "a camada não tem mais de onde ser baixada (o arquivo saiu do disco e não foi publicado)"
        )

    imagens = [str(i) for i in (body.get("image_ids") or [])]
    no_modelo = bool(body.get("model"))
    if not imagens and not no_modelo:
        # corpo vazio: o destino que a construção já pedia
        imagens = [str(i) for i in (job.get("attach_to") or [])]
    if not imagens and not no_modelo:
        raise HTTPException(400, "informe image_ids ou model")

    # todas as permissões antes de gravar qualquer coisa: uma imagem alheia no
    # meio da lista não pode deixar as anteriores anexadas e as seguintes não
    for image_id in imagens:
        if not ownership.can_manage_site_image(p, image_id):
            raise HTTPException(404, f"imagem '{image_id}' não existe")
    modelo = None
    if no_modelo:
        modelo = str(job.get("model", ""))
        if not modelo or not ownership.can_manage_model(p, modelo):
            raise HTTPException(404, "modelo não existe")

    camada = {
        "md5": saida["md5"],
        "file": saida["file"],
        # se a camada já foi publicada no servidor de arquivos, é de lá que as
        # máquinas baixam; senão, a própria máquina de gestão serve
        "cdn_url": layerbuilds.url_da_camada(saida),
        "size": saida.get("size"),
        "from_build": job_id,
    }
    for image_id in imagens:
        d = store.site_image_dir(image_id)
        with fsdb.locked(d):
            extras = fsdb.read_json(d / "layers-extra.json", []) or []
            extras = [c for c in extras if c.get("file") != camada["file"]]
            extras.insert(0, {**camada, "role": "extra"})
            fsdb.write_json(d / "layers-extra.json", extras)
    if modelo:
        store.add_model_layer(modelo, {**camada, "role": "extra"}, 0)
    return {"ok": True, "layer": camada, "images": imagens, "model": modelo}


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
        extras.insert(0, {**camada, "role": "extra"})
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


def _acesso_a_imagem(image: str, request: Request, authorization: str | None) -> auth.Principal:
    """Quem pode pedir construção desta imagem: admin, o sub-admin dono dela,
    ou o próprio token da imagem (é o que o configureitor usa). A cota é
    decidida por quem chama, pelo `kind` devolvido.

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
        return p
    if p.kind == "image" and p.name == image:
        return p
    raise HTTPException(401, "credencial inválida")
