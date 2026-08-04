"""Modelos: o que se configura uma vez e serve de base para as site-images.

Um modelo reúne as camadas (sistema base, telemetria, wifi, pacotes) e o
formulário que as sedes preenchem (schema.json, com os cadeados por campo).
Antes isto se chamava "template" e só nascia à mão no disco.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import auth
from ..models import ModelLayers
from ..services import layer_roles, ownership, store
from ..services import wallpaper as wp
from ..settings import settings

router = APIRouter(prefix="/api/v1")

# O que cada camada é. Serve para trocar a certa: o nome do arquivo da base
# muda a cada temporada (icpc-latam2025 → maratonalinux2026), então casar por
# nome deixa as duas no modelo e a máquina monta duas raízes sobrepostas.
#   base       o sistema operacional inteiro (a maior, sempre por último)
#   telemetry  o agente, a tela de bloqueio e a regra de USB
#   wifi       perfis de rede sem fio
#   extra      qualquer personalização (pacotes, navegador, licenças)
ROLES = set(layer_roles.PAPEIS)


@router.post("/models", status_code=201)
async def create_model(body: dict, p=Depends(auth.require_console)) -> dict:
    nome = str(body.get("name", "")).strip()
    if not store.MODEL_NAME_RE.match(nome):
        raise HTTPException(400, "nome inválido para o modelo")

    erro = ownership.check_can_create(p, "models", nome)
    if erro:
        raise HTTPException(403, erro)

    origem = body.get("from")
    if origem and not ownership.can_use_model(p, origem):
        raise HTTPException(404, "modelo de origem não existe")

    try:
        modelo = store.create_model(
            nome,
            description=str(body.get("description", "")),
            # publicar um modelo para todo mundo é decisão da administração
            public=bool(body.get("public")) if p.kind == "admin" else False,
            owner=p.owner,
            from_model=origem,
        )
    except store.ImageError as e:
        raise HTTPException(400, str(e))

    if not modelo.get("layers"):
        modelo["warning"] = "modelo sem camadas: uma site-image derivada dele não vai bootar"
    return modelo


@router.post("/models/{name}/duplicate", status_code=201)
async def duplicate_model(name: str, body: dict, p=Depends(auth.require_console)) -> dict:
    """Copia camadas e formulário — o caminho normal para 'quero um modelo
    novo já com telemetria e wifi'."""
    if not ownership.can_use_model(p, name):
        raise HTTPException(404, "modelo não existe")
    return await create_model({**body, "from": name}, p)


@router.get("/models")
async def list_models(p=Depends(auth.require_console)) -> dict:
    return {"models": ownership.visible_models(p)}


@router.get("/models/{name}")
async def get_model(name: str, p=Depends(auth.require_console)) -> dict:
    if not ownership.can_use_model(p, name):
        raise HTTPException(404, "modelo não existe")
    return store.get_model(name) or {}


@router.patch("/models/{name}")
async def patch_model(name: str, body: dict, p=Depends(auth.require_console)) -> dict:
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    if body.get("public") is not None and p.kind != "admin":
        raise HTTPException(403, "só a administração publica um modelo")
    store.set_model_meta(
        name,
        public=body.get("public"),
        description=body.get("description"),
        wallpaper_locked=body.get("wallpaper_locked"),
    )
    return store.get_model(name) or {}


@router.delete("/models/{name}", status_code=204)
async def delete_model(name: str, p=Depends(auth.require_console)) -> None:
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    try:
        store.delete_model(name)
    except store.ImageError as e:
        raise HTTPException(409, str(e))


# --- papel de parede do modelo ---
#
# Definido uma vez pela organização e herdado por TODA sede do modelo, sem
# cópia: `services/wallpaper.efetivo()` resolve na hora de servir, para que
# trocar aqui na véspera chegue às sedes já criadas. Com `wallpaper_locked` no
# modelo, nenhuma delas troca.


@router.get("/models/{name}/wallpaper")
async def get_model_wallpaper(name: str, p=Depends(auth.require_console)):
    if not ownership.can_use_model(p, name):
        raise HTTPException(404, "modelo não existe")
    achado = wp.do_modelo(name)
    if not achado:
        raise HTTPException(404, "sem wallpaper")
    caminho, meta = achado
    return FileResponse(
        caminho,
        media_type=meta.get("content_type", "image/png"),
        headers={"ETag": f'"{meta["md5"]}"'},
    )


@router.put("/models/{name}/wallpaper")
async def put_model_wallpaper(
    name: str, file: UploadFile = File(...), p=Depends(auth.require_console)
) -> dict:
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    data = await file.read(wp.MAX_BYTES + 1)
    try:
        return wp.gravar(store.model_dir(name), data, file.filename or "")
    except wp.WallpaperError as e:
        raise HTTPException(413 if "maior que" in str(e) else 400, str(e))


@router.delete("/models/{name}/wallpaper", status_code=204)
async def delete_model_wallpaper(name: str, p=Depends(auth.require_console)) -> None:
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    wp.apagar(store.model_dir(name))


# --- camadas do modelo ---


@router.post("/models/{name}/layers")
async def add_model_layer(name: str, body: dict, p=Depends(auth.require_console)) -> dict:
    """Acrescenta (ou substitui) uma camada.

    `replace_role: "base"` troca a camada que tem aquele papel, mantendo a
    posição dela. É o caminho de trocar a base entre temporadas — casar por
    nome de arquivo não serve, porque o nome muda todo ano.
    """
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    camada = _camada_valida(body)
    trocar = body.get("replace_role")
    if trocar is not None and trocar not in ROLES:
        raise HTTPException(400, f"replace_role invalido: {trocar}")
    layers = store.add_model_layer(
        name, camada, int(body.get("position", 0)), replace_role=trocar
    )
    return {"layers": layers}


@router.delete("/models/{name}/layers/{file}")
async def remove_model_layer(name: str, file: str, p=Depends(auth.require_console)) -> dict:
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    return {"layers": store.remove_model_layer(name, file)}


@router.put("/models/{name}/layers/order")
async def reorder_model_layers(name: str, body: dict, p=Depends(auth.require_console)) -> dict:
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    files = body.get("files")
    if not isinstance(files, list):
        raise HTTPException(400, "esperava {files: [...]}")
    return {"layers": store.reorder_model_layers(name, [str(f) for f in files])}


@router.put("/models/{name}/layers")
async def put_model_layers(name: str, body: ModelLayers, p=Depends(auth.require_console)) -> dict:
    """Substitui a lista inteira. Use com cuidado: quem chama precisa mandar a
    lista completa, e uma leitura desatualizada apaga o que outro acabou de
    acrescentar. Para uma camada só, prefira o POST (que acrescenta) ou o
    `replace_role` (que troca a base sem tocar no resto).
    """
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    # o retorno era descartado: as camadas iam para o disco como vieram, sem
    # cdn_url padrão, sem size e sem role — e o comentário do _camada_valida
    # prometia o contrário
    normalizadas = [_camada_valida(layer) for layer in body.layers]
    store.set_model_layers(name, normalizadas)
    return {"ok": True, "layers": len(normalizadas)}


@router.get("/layers/catalog")
async def layers_catalog(p=Depends(auth.require_console)) -> dict:
    """Camadas já em uso nos modelos visíveis — a lista de onde se escolhe
    telemetria, wifi e afins ao montar um modelo novo."""
    vistas: dict[str, dict] = {}
    for modelo in ownership.visible_models(p):
        for camada in (store.get_model(modelo["name"]) or {}).get("layers", []):
            chave = f"{camada.get('file')}:{camada.get('md5')}"
            vistas.setdefault(chave, {**camada, "used_by": []})["used_by"].append(modelo["name"])
    return {"layers": sorted(vistas.values(), key=lambda c: c.get("file", ""))}


# --- formulário (schema) ---


@router.get("/models/{name}/schema")
async def get_model_schema(name: str, p=Depends(auth.require_console)) -> dict:
    if not ownership.can_use_model(p, name):
        raise HTTPException(404, "modelo não existe")
    from ..services.config import _com_padroes

    # `_com_padroes` é o mesmo caminho que o `set_schema_field` usa para
    # validar: traz do esquema padrão os metadados de formato que um
    # `schema.json` gravado antes deles não tem.
    schema = _com_padroes(store.get_schema(name))
    return {
        "name": name,
        "fields": [
            {
                "key": f["key"],
                "type": f.get("type"),
                "label": f.get("label"),
                "help": f.get("help"),
                "default": f.get("default"),
                # sem as opções, o editor do console montava uma lista VAZIA
                # para todo campo `select` — e escolher o padrão de fuso ou de
                # idioma ficava impossível pela tela
                "options": f.get("options"),
                "locked": bool(f.get("locked")),
            }
            for f in schema.get("fields", [])
        ],
    }


@router.put("/models/{name}/schema/locks")
async def put_model_schema_locks(name: str, body: dict, p=Depends(auth.require_console)) -> dict:
    """Liga/desliga o cadeado de campos. Vale para as site-images Oficiais
    deste modelo (as Livres continuam editando tudo)."""
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    locks = body.get("locks")
    if not isinstance(locks, dict) or not locks:
        raise HTTPException(400, "esperava {locks: {CAMPO: true|false}}")
    try:
        store.set_schema_locks(name, locks)
    except store.ImageError as e:
        raise HTTPException(400, str(e))
    return await get_model_schema(name, p)


@router.patch("/models/{name}/schema/fields/{key}")
async def patch_model_schema_field(
    name: str, key: str, body: dict, p=Depends(auth.require_console)
) -> dict:
    """Ajusta o padrão e os textos de um campo (não cria nem remove campos:
    variável nova só teria efeito se algum módulo do stuff a lesse)."""
    if not ownership.can_manage_model(p, name):
        raise HTTPException(404, "modelo não existe")
    try:
        store.set_schema_field(name, key, body)
    except store.ImageError as e:
        raise HTTPException(400, str(e))
    return await get_model_schema(name, p)


def _camada_valida(camada: dict) -> dict:
    md5 = str(camada.get("md5", "")).lower()
    arquivo = str(camada.get("file", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise HTTPException(400, "md5 inválido")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", arquivo):
        raise HTTPException(400, "nome de arquivo inválido")

    papel = camada.get("role") or "extra"
    if papel not in ROLES:
        raise HTTPException(400, f"role invalido: {papel} (use {', '.join(sorted(ROLES))})")

    blob = settings.data_root / "blobs" / arquivo
    return {
        "md5": md5,
        "file": arquivo,
        # sem URL a camada sai do manifest sem fonte e o boot morre com 500 na
        # sala inteira; o padrão é a própria máquina de gestão servir o blob
        "cdn_url": camada.get("cdn_url") or f"{settings.base_url}/blobs/{arquivo}",
        "size": camada.get("size") or (blob.stat().st_size if blob.is_file() else None),
        "role": papel,
    }
