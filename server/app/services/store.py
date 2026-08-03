"""Acesso ao banco-filesystem de modelos e site-images.

Um **modelo** é o que se configura uma vez: as camadas (telemetria, wifi,
pacotes) e o formulário (schema.json, com os cadeados por campo). Uma
**site-image** é derivada de um modelo — uma por sala/sede, com token, chaves
e configuração próprias.

Todo o resto do servidor fala com o disco através deste módulo.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .. import auth, fsdb
from ..settings import settings

IMAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
# nome de modelo vira nome de diretório: validar antes de qualquer escrita
MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}$")


def reserved_names() -> set[str]:
    """Nomes exatos que ninguém além da administração pode tomar. Sem isto,
    'livre por ordem de chegada' significa que o primeiro a chegar leva
    'maratona' ou 'icpc'."""
    padrao = ["admin", "api", "boot", "www", "root", "maratona", "icpc", "sbc", "nutellaboot"]
    return {n.lower() for n in server_conf().get("reserved_names", padrao)}


def name_is_reserved(name: str) -> bool:
    return bool(reserved_re().match(name)) or name.lower() in reserved_names()


def server_conf() -> dict:
    return fsdb.read_json(settings.data_root / "server.json", {}) or {}


def reserved_re() -> re.Pattern:
    return re.compile(server_conf().get("reserved_prefix_regex", "^[0-9]"))


# --- modelos ---


def model_dir(name: str) -> Path:
    return settings.data_root / "models" / name


def model_exists(name: str) -> bool:
    return (model_dir(name) / "model.json").is_file()


def list_models(owner: str | None = None) -> list[str]:
    """Nomes dos modelos. Com `owner`, só os daquele dono — é assim que o
    console de um sub-admin enxerga apenas o que ele criou."""
    base = settings.data_root / "models"
    if not base.is_dir():
        return []
    nomes = sorted(p.name for p in base.iterdir() if (p / "model.json").is_file())
    if owner is None:
        return nomes
    return [n for n in nomes if model_owner(n) == owner]


def model_owner(name: str) -> str:
    """Dono do modelo. Modelos anteriores ao conceito de dono não têm o campo;
    tratá-los como da administração é o certo — foram criados à mão no disco."""
    tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
    return str(tpl.get("owner") or "admin")


def model_is_public(name: str) -> bool:
    """Templates marcados `public: true` são os únicos que a criação por
    convite pode usar — protege os modelos bloqueados de prova."""
    tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
    return bool(tpl.get("public"))


def list_public_models() -> list[dict]:
    out = []
    for name in list_models():
        if model_is_public(name):
            tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
            out.append({"name": name, "description": tpl.get("description", "")})
    return out


def get_model(name: str) -> dict | None:
    tpl = fsdb.read_json(model_dir(name) / "model.json")
    if tpl is None:
        return None
    tpl["name"] = name
    tpl["schema"] = fsdb.read_json(model_dir(name) / "schema.json", {})
    return tpl


def set_model_layers(name: str, layers: list[dict]) -> None:
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        tpl["layers"] = layers
        fsdb.write_json(model_dir(name) / "model.json", tpl)


def get_schema(name: str) -> dict:
    return fsdb.read_json(model_dir(name) / "schema.json", {"fields": []}) or {"fields": []}


def set_schema_locks(name: str, locks: dict) -> dict:
    """Liga/desliga o cadeado de campos do modelo.

    Só mexe na chave `locked` de cada campo — o resto do schema (tipos,
    opções, rótulos) fica intacto. Vale para todas as imagens Oficiais que
    usam este modelo; imagens Livres continuam ignorando as travas.
    """
    d = model_dir(name)
    with fsdb.locked(d):
        schema = fsdb.read_json(d / "schema.json", {"fields": []}) or {"fields": []}
        conhecidos = {f["key"] for f in schema.get("fields", [])}
        desconhecidos = set(locks) - conhecidos
        if desconhecidos:
            raise ImageError(f"campos que não existem no modelo: {', '.join(sorted(desconhecidos))}")
        for field in schema.get("fields", []):
            if field["key"] in locks:
                field["locked"] = bool(locks[field["key"]])
        fsdb.write_json(d / "schema.json", schema)
    return schema


def set_schema_field(name: str, key: str, patch: dict) -> dict:
    """Ajusta um campo já existente do formulário: valor padrão, rótulo, ajuda
    e cadeado. Não cria nem apaga campos — variável nova só teria efeito se
    algum módulo do `stuff` a lesse, e isso é mudança de cliente, não de dados.
    """
    d = model_dir(name)
    with fsdb.locked(d):
        from .config import _com_padroes

        # com os metadados de formato do esquema padrão: o schema.json gravado
        # na criação do modelo não os tem, e sem eles a validação abaixo não
        # sabe o que exigir
        schema = _com_padroes(fsdb.read_json(d / "schema.json", {"fields": []}) or {"fields": []})
        alvo = next((f for f in schema.get("fields", []) if f["key"] == key), None)
        if alvo is None:
            raise ImageError(f"campo '{key}' não existe neste modelo")
        if "default" in patch:
            # Pelo MESMO caminho que valida o que a sede digita. O padrão de um
            # campo `locked` é o que vai para TODA máquina da sala — e daí para
            # o /etc/.nb3, que o agente carrega como root. Sem esta linha,
            # qualquer valor entrava: uma aspa simples no lugar certo virava
            # comando executado como root em toda a sala, e um `None` fazia a
            # comparação de RAM do boot dar erro de aritmética.
            from .config import ConfigError, _coerce

            try:
                alvo["default"] = _coerce(alvo, patch["default"])
            except ConfigError as e:
                raise ImageError(str(e))
        if "locked" in patch:
            alvo["locked"] = bool(patch["locked"])
        for texto in ("label", "help"):
            valor = patch.get(texto)
            if isinstance(valor, dict):
                faltando = {"pt", "en", "es"} - set(valor)
                if faltando:
                    raise ImageError(f"{texto} precisa dos três idiomas (falta: {', '.join(sorted(faltando))})")
                alvo[texto] = {k: str(valor[k]) for k in ("pt", "en", "es")}
        fsdb.write_json(d / "schema.json", schema)
    return schema


def set_model_meta(name: str, *, public: bool | None = None, description: str | None = None) -> None:
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        if public is not None:
            tpl["public"] = bool(public)
        if description is not None:
            tpl["description"] = str(description)
        fsdb.write_json(model_dir(name) / "model.json", tpl)


def models_using(name: str) -> list[str]:
    """Site-images que derivam deste modelo — quem impede de apagá-lo."""
    return [i["id"] for i in list_site_images() if i.get("model") == name]


def create_model(
    name: str,
    *,
    description: str = "",
    public: bool = False,
    owner: str = "admin",
    from_model: str | None = None,
) -> dict:
    """Cria um modelo. Com `from_model`, copia camadas e formulário (inclusive
    os cadeados) — é assim que se faz um modelo novo já com telemetria e wifi,
    partindo de um que já os tem."""
    from .default_schema import build_default_schema

    if not MODEL_NAME_RE.match(name):
        raise ImageError(
            "nome inválido: use 2-49 caracteres [a-z0-9._-], começando por letra ou dígito"
        )
    if model_exists(name):
        raise ImageError(f"modelo '{name}' já existe")

    layers: list[dict] = []
    schema = build_default_schema()
    if from_model:
        if not model_exists(from_model):
            raise ImageError(f"modelo de origem '{from_model}' não existe")
        base = fsdb.read_json(model_dir(from_model) / "model.json", {}) or {}
        layers = list(base.get("layers", []))
        schema = fsdb.read_json(model_dir(from_model) / "schema.json", schema) or schema

    d = model_dir(name)
    with fsdb.locked(d):
        fsdb.write_json(
            d / "model.json",
            {
                "name": name,
                "description": description,
                "owner": owner,
                "public": bool(public),
                "created_at": time.time(),
                "derived_from": from_model,
                "layers": layers,
            },
        )
        fsdb.write_json(d / "schema.json", schema)
    return get_model(name)


def delete_model(name: str) -> None:
    """Recusa se alguma site-image ainda deriva dele — apagar deixaria essas
    máquinas com manifest sem base, ou seja, sem sistema para bootar."""
    em_uso = models_using(name)
    if em_uso:
        raise ImageError("modelo em uso por: " + ", ".join(sorted(em_uso)))
    d = model_dir(name)
    if d.is_dir():
        shutil.rmtree(d)


def add_model_layer(
    name: str, camada: dict, position: int = 0, replace_role: str | None = None
) -> list[dict]:
    """Insere uma camada. A ordem é a prioridade no overlay: posição 0 é a que
    sobrepõe as demais.

    Com `replace_role`, a camada que tiver aquele papel sai e a nova entra **no
    lugar dela**, mantendo a posição. É assim que se troca a base de uma
    temporada para outra: casar por nome de arquivo não funciona, porque o nome
    da base muda todo ano (icpc-latam2025 → maratonalinux2026) e o resultado é
    ficar com duas bases empilhadas — a máquina baixa 13 GB e monta duas raízes
    sobrepostas, em silêncio.
    """
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        atuais = list(tpl.get("layers", []))

        def sai(c: dict) -> bool:
            if c.get("file") == camada["file"]:
                return True
            return bool(replace_role) and c.get("role") == replace_role

        if replace_role:
            # onde estava a camada substituída — a nova entra no mesmo lugar
            alvo = next((i for i, c in enumerate(atuais) if sai(c)), None)
            if alvo is not None:
                position = alvo

        layers = [c for c in atuais if not sai(c)]
        layers.insert(max(0, min(position, len(layers))), camada)
        tpl["layers"] = layers
        fsdb.write_json(model_dir(name) / "model.json", tpl)
    return layers


def remove_model_layer(name: str, file: str) -> list[dict]:
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        tpl["layers"] = [c for c in tpl.get("layers", []) if c.get("file") != file]
        fsdb.write_json(model_dir(name) / "model.json", tpl)
    return tpl["layers"]


def reorder_model_layers(name: str, files: list[str]) -> list[dict]:
    """Reordena pela lista de nomes de arquivo (a primeira ganha no overlay)."""
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        por_arquivo = {c["file"]: c for c in tpl.get("layers", [])}
        novas = [por_arquivo[f] for f in files if f in por_arquivo]
        # o que não veio na lista fica no fim, para nada sumir por engano
        novas += [c for c in tpl.get("layers", []) if c["file"] not in set(files)]
        tpl["layers"] = novas
        fsdb.write_json(model_dir(name) / "model.json", tpl)
    return novas


# --- site-images (as imagens derivadas de um modelo) ---


def site_image_dir(image_id: str) -> Path:
    return settings.data_root / "site-images" / image_id


def site_image_exists(image_id: str) -> bool:
    return (site_image_dir(image_id) / "image.json").is_file()


def get_site_image(image_id: str) -> dict | None:
    return fsdb.read_json(site_image_dir(image_id) / "image.json")


def list_site_images(prefix: str = "", owner: str | None = None) -> list[dict]:
    base = settings.data_root / "site-images"
    out = []
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if prefix and not p.name.startswith(prefix):
            continue
        info = fsdb.read_json(p / "image.json")
        if not info:
            continue
        if owner is not None and str(info.get("owner") or "admin") != owner:
            continue
        out.append(info)
    return out


def site_image_owner(image_id: str) -> str:
    info = get_site_image(image_id) or {}
    return str(info.get("owner") or "admin")


class ImageError(ValueError):
    pass


def create_site_image(
    image_id: str,
    fullname: str,
    model: str,
    *,
    unlocked: bool = False,
    owner: str = "admin",
    extra: dict | None = None,
) -> dict:
    """Cria a imagem e devolve dict com credenciais em claro (única vez).

    `extra` mescla campos adicionais no image.json (ex.: self_service,
    build_quota, criada por auto-atendimento)."""
    if not IMAGE_ID_RE.match(image_id):
        raise ImageError(
            "id inválido: use 2-32 caracteres [a-z0-9._-], começando por letra ou dígito"
        )
    if not model_exists(model):
        raise ImageError(f"modelo '{model}' não existe")
    if site_image_exists(image_id):
        raise ImageError(f"imagem '{image_id}' já existe")

    namespace = "contest" if reserved_re().match(image_id) else "personal"
    token = auth.new_key("nb3i")
    machine_key = auth.new_key("nb3m")
    boot_key = auth.new_key("nb3b")
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_json(
            d / "image.json",
            {
                "id": image_id,
                "fullname": fullname,
                "model": model,
                "namespace": namespace,
                "unlocked": bool(unlocked),
                "owner": owner,
                "created_at": time.time(),
                **(extra or {}),
            },
        )
        fsdb.write_text(d / "token", token + "\n", mode=0o600)
        fsdb.write_text(d / "machine.key", machine_key + "\n", mode=0o600)
        # a chave de boot vai no nutellaboot.conf do pendrive
        fsdb.write_text(d / "boot.key", boot_key + "\n", mode=0o600)
        fsdb.write_json(d / "config.json", {"values": {}})
        fsdb.write_json(d / "layers-extra.json", [])
    return {
        "id": image_id,
        "fullname": fullname,
        "model": model,
        "namespace": namespace,
        "unlocked": bool(unlocked),
        "owner": owner,
        "token": token,
        "machine_key": machine_key,
        "boot_key": boot_key,
        **_links(image_id, token),
    }


def _links(image_id: str, token: str) -> dict:
    """Links prontos para entregar ao coordenador (com o token embutido)."""
    q = f"?id={image_id}&tk={token}"
    return {
        "configureitor_url": f"{settings.base_url}/configureitor/{q}",
        "hotconfig_url": f"{settings.base_url}/hotconfig/{q}",
    }


def credentials(image_id: str) -> dict:
    """Todas as credenciais e links de uma imagem já existente. Só o admin lê
    isto — os segredos ficam em claro no disco (são o que se distribui, não
    hashes), então é seguro devolvê-los para quem tem a chave de admin."""
    token = (fsdb.read_text(site_image_dir(image_id) / "token") or "").strip()
    info = get_site_image(image_id) or {}
    return {
        "id": image_id,
        "fullname": info.get("fullname", ""),
        "token": token,
        "machine_key": machine_key(image_id),
        "boot_key": boot_key(image_id),
        **_links(image_id, token),
    }


def boot_key(image_id: str) -> str:
    return (fsdb.read_text(site_image_dir(image_id) / "boot.key") or "").strip()


def rotate_boot_key(image_id: str) -> str:
    """Gera nova chave de boot. Atenção: todo pendrive daquela imagem precisa
    ter o nutellaboot.conf atualizado depois disso."""
    chave = auth.new_key("nb3b")
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_text(d / "boot.key", chave + "\n", mode=0o600)
    return chave


def patch_site_image(image_id: str, fields: dict) -> dict:
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        info = fsdb.read_json(d / "image.json") or {}
        for k in ("fullname", "unlocked", "model", "wallpaper_locked", "build_quota"):
            if k in fields and fields[k] is not None:
                if k == "model" and not model_exists(fields[k]):
                    raise ImageError(f"modelo '{fields[k]}' não existe")
                info[k] = fields[k]
        fsdb.write_json(d / "image.json", info)
    return info


def delete_site_image(image_id: str) -> None:
    d = site_image_dir(image_id)
    if d.is_dir():
        shutil.rmtree(d)


def rotate_token(image_id: str) -> str:
    token = auth.new_key("nb3i")
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_text(d / "token", token + "\n", mode=0o600)
    return token


def site_image_layers(image_id: str) -> list[dict]:
    """Camadas extras da site-image primeiro (prioridade no overlay), depois
    as do modelo — mesma semântica do nb2 (template.extra antes do template)."""
    info = get_site_image(image_id) or {}
    extra = fsdb.read_json(site_image_dir(image_id) / "layers-extra.json", []) or []
    tpl = fsdb.read_json(model_dir(info.get("model", "")) / "model.json", {}) or {}
    return list(extra) + list(tpl.get("layers", []))


def config_values(image_id: str) -> dict:
    conf = fsdb.read_json(site_image_dir(image_id) / "config.json", {}) or {}
    return conf.get("values", {})


def machine_key(image_id: str) -> str:
    return (fsdb.read_text(site_image_dir(image_id) / "machine.key") or "").strip()
