"""Autenticação por classes de credencial.

Prefixos de chave: nb3a_ (admin), nb3s_ (serviço/MOJ), nb3i_ (token de
imagem), nb3m_ (chave de máquina). Só hashes sha256 ficam em disco
(exceto token/machine.key por imagem, que são o segredo distribuído).
"""

from __future__ import annotations

import fnmatch
import hashlib
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Header, HTTPException

from . import fsdb
from .settings import settings


def new_key(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class Principal:
    kind: str  # "admin" | "service" | "image" | "machine"
    name: str = ""
    scopes: set[str] = field(default_factory=set)
    images: list[str] = field(default_factory=list)  # globs (serviço)

    def can_see_image(self, image_id: str) -> bool:
        if self.kind == "admin":
            return True
        if self.kind == "service":
            return not self.images or any(
                fnmatch.fnmatch(image_id, pat) for pat in self.images
            )
        return self.name == image_id


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return None


def _site_image_dir(image_id: str) -> Path:
    return settings.data_root / "site-images" / image_id


def identify(token: str | None, image_id: str | None = None) -> Principal | None:
    """Resolve uma credencial Bearer para um Principal, ou None."""
    if not token:
        return None
    th = key_hash(token)

    admin = fsdb.read_json(settings.data_root / "keys" / "admin.json", {"keys": []})
    for entry in admin.get("keys", []):
        if secrets.compare_digest(th, entry.get("sha256", "")):
            return Principal("admin", entry.get("id", "admin"))

    services = fsdb.read_json(settings.data_root / "keys" / "services.json", {})
    for name, entry in services.items():
        if secrets.compare_digest(th, entry.get("sha256", "")):
            return Principal(
                "service",
                name,
                scopes=set(entry.get("scopes", [])),
                images=list(entry.get("images", [])),
            )

    if image_id:
        stored = (fsdb.read_text(_site_image_dir(image_id) / "token") or "").strip()
        if stored and secrets.compare_digest(token, stored):
            return Principal("image", image_id)
    return None


def identify_machine(machine_key: str | None, image_id: str) -> Principal | None:
    if not machine_key:
        return None
    stored = (fsdb.read_text(_site_image_dir(image_id) / "machine.key") or "").strip()
    if stored and secrets.compare_digest(machine_key.strip(), stored):
        return Principal("machine", image_id)
    return None


def image_owner(image_id: str, token: str | None) -> bool:
    """True se o token é o da própria imagem (dono). Usado para deixar o dono
    disparar build de camada da SUA imagem, sem chave de admin."""
    if not token:
        return False
    stored = (fsdb.read_text(_site_image_dir(image_id) / "token") or "").strip()
    return bool(stored) and secrets.compare_digest(token.strip(), stored)


def boot_key_required(image_id: str) -> bool:
    """A imagem exige chave de boot? (existe boot.key no diretório dela)

    Imagens criadas pelo nutellaboot3 sempre têm. Apagar o arquivo torna a
    imagem aberta de novo — útil só para depuração, e está documentado.
    """
    return (_site_image_dir(image_id) / "boot.key").is_file()


def check_boot_key(image_id: str, key: str | None) -> bool:
    """Confere a chave que o pendrive carrega no nutellaboot.conf.

    Ela também vale como chave de máquina: a máquina que bootou com o
    pendrive certo é a mesma que reporta telemetria e semeia a imagem.
    """
    stored = (fsdb.read_text(_site_image_dir(image_id) / "boot.key") or "").strip()
    if not stored:
        return not boot_key_required(image_id)
    if not key:
        return False
    return secrets.compare_digest(key.strip(), stored)


def _unauthorized() -> HTTPException:
    return HTTPException(401, "credencial ausente ou inválida")


async def require_admin(authorization: str | None = Header(None)) -> Principal:
    p = identify(_bearer(authorization))
    if not p or p.kind != "admin":
        raise _unauthorized()
    return p


def require_image_access(*, service_scope: str | None = None, allow_machine: bool = False):
    """Dependência para rotas /images/{image}: aceita admin, token da própria
    imagem e, se `service_scope`, serviço com o escopo; `allow_machine` aceita
    a chave de máquina da imagem (header X-NB-Machine-Key)."""

    async def dep(
        image: str,
        authorization: str | None = Header(None),
        x_nb_machine_key: str | None = Header(None),
    ) -> Principal:
        if not _site_image_dir(image).is_dir():
            raise HTTPException(404, "imagem não existe")
        if allow_machine:
            p = identify_machine(x_nb_machine_key, image)
            if p:
                return p
        p = identify(_bearer(authorization), image_id=image)
        if not p:
            raise _unauthorized()
        if p.kind == "service":
            if service_scope is None or service_scope not in p.scopes:
                raise HTTPException(403, "escopo insuficiente")
        if not p.can_see_image(image):
            raise HTTPException(403, "sem acesso a esta imagem")
        return p

    return dep


def require_machine(image: str, x_nb_machine_key: str | None) -> Principal:
    """Só a chave de máquina da imagem (telemetria/fila)."""
    if not _site_image_dir(image).is_dir():
        raise HTTPException(404, "imagem não existe")
    p = identify_machine(x_nb_machine_key, image)
    if not p:
        raise _unauthorized()
    return p
