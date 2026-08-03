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

from fastapi import Header, HTTPException, Request

from . import fsdb
from .settings import settings


def new_key(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class Principal:
    kind: str  # "admin" | "subadmin" | "service" | "image" | "machine"
    name: str = ""
    scopes: set[str] = field(default_factory=set)
    images: list[str] = field(default_factory=list)  # globs (serviço)

    @property
    def owner(self) -> str:
        """Identidade usada no campo `owner` de modelos e site-images."""
        if self.kind == "admin":
            return "admin"
        if self.kind == "subadmin":
            return self.name
        return ""

    def can_see_image(self, image_id: str) -> bool:
        if self.kind == "admin":
            return True
        if self.kind == "service":
            return not self.images or any(
                fnmatch.fnmatch(image_id, pat) for pat in self.images
            )
        if self.kind == "subadmin":
            from .services import store

            return store.site_image_owner(image_id) == self.name
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

    return identify_subadmin(token)


def identify_subadmin(token: str | None) -> Principal | None:
    """O próprio código do convite é a credencial do sub-admin — sem cadastro
    separado, sem senha para esquecer. Quem revoga o convite tira o acesso."""
    from .services import invites, owners

    if not token or not invites.looks_like_code(token):
        return None
    code = invites.normalize(token)
    ok, _ = invites.is_valid_for_console(code)
    if not ok:
        return None
    oid = owners.owner_id(code)
    if owners.disabled(oid):
        return None
    owners.ensure(code)
    return Principal("subadmin", oid)


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


# Cabeçalho que a autenticação por COOKIE exige. Um <form> de outro site não
# consegue definir cabeçalho, e um fetch cross-site com cabeçalho custom
# dispara preflight (não há CORS configurado, então morre ali). É esta linha
# que segura o CSRF que o cookie introduziria — em especial nos POST sem corpo
# obrigatório (lock_all, rotate_token, disable_owner...), os únicos que um
# formulário simples conseguiria disparar.
HEADER_CONSOLE = "x-nb-console"


def principal(request: Request | None, authorization: str | None, image_id: str | None = None):
    """A credencial, de onde ela vier — num ponto só.

    Ordem: `Authorization: Bearer` primeiro (ferramentas, MOJ, máquinas — nada
    mudou para elas), cookie de sessão depois. O cookie só vale com o cabeçalho
    de console.

    É pública porque rota que não usa `Depends` (as de camada por imagem, que
    misturam credencial de console com token da imagem) precisa chamá-la. Ler
    `Authorization` na mão fora daqui já custou caro: as rotas de layerbuild
    faziam isso e ficaram 401 para o console inteiro quando a sessão por cookie
    entrou.
    """
    p = identify(_bearer(authorization), image_id=image_id)
    if p is not None:
        return p
    if request is None:
        return None
    if request.headers.get(HEADER_CONSOLE) is None:
        return None

    from .services import sessions

    return sessions.resolve(request.cookies.get(sessions.COOKIE, ""))


async def require_admin(
    request: Request = None, authorization: str | None = Header(None)
) -> Principal:
    p = principal(request, authorization)
    if not p or p.kind != "admin":
        raise _unauthorized()
    return p


async def require_console(
    request: Request, authorization: str | None = Header(None)
) -> Principal:
    """Console de administração: chave de admin ou código de convite.

    O código de convite é curto o bastante para ser digitado à mão, então o
    erro é limitado por IP — sem isso, adivinhar um código seria só uma
    questão de tempo de CPU alheio.
    """
    from .services import ratelimit

    p = principal(request, authorization)
    if p and p.kind in ("admin", "subadmin"):
        return p
    ip = ratelimit.client_ip(request)
    if not ratelimit.allow(f"console:{ip}", rate=0.2, burst=10):
        raise HTTPException(429, "muitas tentativas; tente de novo em instantes")
    raise _unauthorized()


def require_image_access(*, service_scope: str | None = None, allow_machine: bool = False):
    """Dependência para rotas /images/{image}: aceita admin, token da própria
    imagem e, se `service_scope`, serviço com o escopo; `allow_machine` aceita
    a chave de máquina da imagem (header X-NB-Machine-Key)."""

    async def dep(
        image: str,
        request: Request = None,
        authorization: str | None = Header(None),
        x_nb_machine_key: str | None = Header(None),
    ) -> Principal:
        if allow_machine:
            p = identify_machine(x_nb_machine_key, image)
            if p:
                return p
        # a credencial vem ANTES da existência: conferir o diretório primeiro
        # deixava um anônimo separar "imagem existe" (401) de "não existe"
        # (404) sem credencial nenhuma
        p = principal(request, authorization, image_id=image)
        if not p:
            raise _unauthorized()
        if p.kind == "service":
            # serviço é credencial que a administração emitiu (o MOJ): erro
            # claro vale mais que sigilo, e quem integra precisa distinguir
            # "faltou escopo" de "essa sala não é sua"
            if service_scope is None or service_scope not in p.scopes:
                raise HTTPException(403, "escopo insuficiente")
            if not _site_image_dir(image).is_dir():
                raise HTTPException(404, "imagem não existe")
            if not p.can_see_image(image):
                raise HTTPException(403, "sem acesso a esta imagem")
            return p
        # invariante 11: para quem entra pelo console (ou com token de outra
        # imagem), o que não é seu não existe. Um 403 aqui viraria oráculo de
        # nomes de sala — e são ~26 rotas herdando esta dependência.
        if not _site_image_dir(image).is_dir() or not p.can_see_image(image):
            raise HTTPException(404, "imagem não existe")
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
