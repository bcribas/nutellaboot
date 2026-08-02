"""Acesso ao banco-filesystem de imagens e templates.

Todo o resto do servidor fala com o disco através deste módulo.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .. import auth, fsdb
from ..settings import settings

IMAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


def server_conf() -> dict:
    return fsdb.read_json(settings.data_root / "server.json", {}) or {}


def reserved_re() -> re.Pattern:
    return re.compile(server_conf().get("reserved_prefix_regex", "^[0-9]"))


# --- templates ---


def template_dir(name: str) -> Path:
    return settings.data_root / "templates" / name


def template_exists(name: str) -> bool:
    return (template_dir(name) / "template.json").is_file()


def list_templates() -> list[str]:
    base = settings.data_root / "templates"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "template.json").is_file())


def template_is_public(name: str) -> bool:
    """Templates marcados `public: true` são os únicos que a criação por
    convite pode usar — protege os templates bloqueados de prova."""
    tpl = fsdb.read_json(template_dir(name) / "template.json", {}) or {}
    return bool(tpl.get("public"))


def list_public_templates() -> list[dict]:
    out = []
    for name in list_templates():
        if template_is_public(name):
            tpl = fsdb.read_json(template_dir(name) / "template.json", {}) or {}
            out.append({"name": name, "description": tpl.get("description", "")})
    return out


def get_template(name: str) -> dict | None:
    tpl = fsdb.read_json(template_dir(name) / "template.json")
    if tpl is None:
        return None
    tpl["name"] = name
    tpl["schema"] = fsdb.read_json(template_dir(name) / "schema.json", {})
    return tpl


def set_template_layers(name: str, layers: list[dict]) -> None:
    with fsdb.locked(template_dir(name)):
        tpl = fsdb.read_json(template_dir(name) / "template.json", {}) or {}
        tpl["layers"] = layers
        fsdb.write_json(template_dir(name) / "template.json", tpl)


def get_schema(name: str) -> dict:
    return fsdb.read_json(template_dir(name) / "schema.json", {"fields": []}) or {"fields": []}


def set_schema_locks(name: str, locks: dict) -> dict:
    """Liga/desliga o cadeado de campos do template.

    Só mexe na chave `locked` de cada campo — o resto do schema (tipos,
    opções, rótulos) fica intacto. Vale para todas as imagens Oficiais que
    usam este template; imagens Livres continuam ignorando as travas.
    """
    d = template_dir(name)
    with fsdb.locked(d):
        schema = fsdb.read_json(d / "schema.json", {"fields": []}) or {"fields": []}
        conhecidos = {f["key"] for f in schema.get("fields", [])}
        desconhecidos = set(locks) - conhecidos
        if desconhecidos:
            raise ImageError(f"campos que não existem no template: {', '.join(sorted(desconhecidos))}")
        for field in schema.get("fields", []):
            if field["key"] in locks:
                field["locked"] = bool(locks[field["key"]])
        fsdb.write_json(d / "schema.json", schema)
    return schema


def set_template_meta(name: str, *, public: bool | None = None, description: str | None = None) -> None:
    with fsdb.locked(template_dir(name)):
        tpl = fsdb.read_json(template_dir(name) / "template.json", {}) or {}
        if public is not None:
            tpl["public"] = bool(public)
        if description is not None:
            tpl["description"] = str(description)
        fsdb.write_json(template_dir(name) / "template.json", tpl)


# --- imagens ---


def image_dir(image_id: str) -> Path:
    return settings.data_root / "images" / image_id


def image_exists(image_id: str) -> bool:
    return (image_dir(image_id) / "image.json").is_file()


def get_image(image_id: str) -> dict | None:
    return fsdb.read_json(image_dir(image_id) / "image.json")


def list_images(prefix: str = "") -> list[dict]:
    base = settings.data_root / "images"
    out = []
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if prefix and not p.name.startswith(prefix):
            continue
        info = fsdb.read_json(p / "image.json")
        if info:
            out.append(info)
    return out


class ImageError(ValueError):
    pass


def create_image(
    image_id: str,
    fullname: str,
    template: str,
    *,
    unlocked: bool = False,
    extra: dict | None = None,
) -> dict:
    """Cria a imagem e devolve dict com credenciais em claro (única vez).

    `extra` mescla campos adicionais no image.json (ex.: self_service,
    build_quota, criada por auto-atendimento)."""
    if not IMAGE_ID_RE.match(image_id):
        raise ImageError(
            "id inválido: use 2-32 caracteres [a-z0-9._-], começando por letra ou dígito"
        )
    if not template_exists(template):
        raise ImageError(f"template '{template}' não existe")
    if image_exists(image_id):
        raise ImageError(f"imagem '{image_id}' já existe")

    namespace = "contest" if reserved_re().match(image_id) else "personal"
    token = auth.new_key("nb3i")
    machine_key = auth.new_key("nb3m")
    boot_key = auth.new_key("nb3b")
    d = image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_json(
            d / "image.json",
            {
                "id": image_id,
                "fullname": fullname,
                "template": template,
                "namespace": namespace,
                "unlocked": bool(unlocked),
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
        "template": template,
        "namespace": namespace,
        "unlocked": bool(unlocked),
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
    token = (fsdb.read_text(image_dir(image_id) / "token") or "").strip()
    info = get_image(image_id) or {}
    return {
        "id": image_id,
        "fullname": info.get("fullname", ""),
        "token": token,
        "machine_key": machine_key(image_id),
        "boot_key": boot_key(image_id),
        **_links(image_id, token),
    }


def boot_key(image_id: str) -> str:
    return (fsdb.read_text(image_dir(image_id) / "boot.key") or "").strip()


def rotate_boot_key(image_id: str) -> str:
    """Gera nova chave de boot. Atenção: todo pendrive daquela imagem precisa
    ter o nutellaboot.conf atualizado depois disso."""
    chave = auth.new_key("nb3b")
    d = image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_text(d / "boot.key", chave + "\n", mode=0o600)
    return chave


def patch_image(image_id: str, fields: dict) -> dict:
    d = image_dir(image_id)
    with fsdb.locked(d):
        info = fsdb.read_json(d / "image.json") or {}
        for k in ("fullname", "unlocked", "template", "wallpaper_locked", "build_quota"):
            if k in fields and fields[k] is not None:
                if k == "template" and not template_exists(fields[k]):
                    raise ImageError(f"template '{fields[k]}' não existe")
                info[k] = fields[k]
        fsdb.write_json(d / "image.json", info)
    return info


def delete_image(image_id: str) -> None:
    d = image_dir(image_id)
    if d.is_dir():
        shutil.rmtree(d)


def rotate_token(image_id: str) -> str:
    token = auth.new_key("nb3i")
    d = image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_text(d / "token", token + "\n", mode=0o600)
    return token


def image_layers(image_id: str) -> list[dict]:
    """Camadas extras da imagem primeiro (prioridade no overlay), depois as do
    template — mesma semântica do nb2 (template.extra antes do template)."""
    info = get_image(image_id) or {}
    extra = fsdb.read_json(image_dir(image_id) / "layers-extra.json", []) or []
    tpl = fsdb.read_json(template_dir(info.get("template", "")) / "template.json", {}) or {}
    return list(extra) + list(tpl.get("layers", []))


def config_values(image_id: str) -> dict:
    conf = fsdb.read_json(image_dir(image_id) / "config.json", {}) or {}
    return conf.get("values", {})


def machine_key(image_id: str) -> str:
    return (fsdb.read_text(image_dir(image_id) / "machine.key") or "").strip()
