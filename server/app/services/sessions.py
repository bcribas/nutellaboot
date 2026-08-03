"""Sessão do console: entrar uma vez e continuar dentro.

Antes disto a chave ficava no `sessionStorage` do navegador e era remontada em
todo `fetch`. Agora ela é trocada uma vez por um identificador opaco que vive
num cookie `HttpOnly` — o JavaScript da página não consegue lê-lo, e ele não
aparece na URL nem no histórico.

**Sessão com estado, não assinada.** Um cookie assinado (o `SessionMiddleware`
do Starlette) seria menos código, mas traria duas perdas que importam com
validade de 30 dias: não haveria como encerrar uma sessão específica, e a
sessão sobreviveria à troca da chave de administração — hoje rotacionar a
chave corta o acesso na hora, e isso não pode piorar. Aqui a identidade é
**revalidada a cada requisição** (`resolve`), então trocar a chave ou suspender
um sub-admin derruba as sessões dele sem precisar caçá-las.

O arquivo é `data/sessions.json`, escrito pelo mesmo `fsdb` do resto.
"""

from __future__ import annotations

import secrets
import time

from .. import fsdb
from ..settings import settings

COOKIE = "nb3_session"
DURACAO = 30 * 24 * 3600  # 30 dias

# Só quem entra pelo console tem sessão. Chave de serviço (MOJ), token de
# imagem e chave de máquina continuam só no Bearer: são credenciais de
# programa, não de navegador.
TIPOS = ("admin", "subadmin")


def _path():
    return settings.data_root / "sessions.json"


def _load() -> dict:
    return fsdb.read_json(_path(), {}) or {}


def create(kind: str, name: str, *, ip: str = "") -> dict:
    """Abre uma sessão e devolve {id, expires_at}."""
    if kind not in TIPOS:
        raise ValueError(f"sessao nao vale para {kind}")
    agora = time.time()
    sid = secrets.token_urlsafe(32)
    registro = {
        "kind": kind,
        "name": name,
        "created_at": agora,
        "expires_at": agora + DURACAO,
        "ip": ip[:45],
    }
    with fsdb.locked(settings.data_root):
        dados = {k: v for k, v in _load().items() if v.get("expires_at", 0) > agora}
        dados[sid] = registro
        fsdb.write_json(_path(), dados, mode=0o600)
    return {"id": sid, **registro}


def get(sid: str) -> dict | None:
    if not sid:
        return None
    registro = _load().get(sid)
    if registro is None or registro.get("expires_at", 0) <= time.time():
        return None
    return registro


def resolve(sid: str):
    """Devolve o Principal da sessão, revalidando a identidade.

    É esta revalidação que mantém o comportamento de sempre: trocar a chave de
    administração, revogar o convite ou suspender o sub-admin derruba o acesso
    na hora, mesmo com a sessão ainda dentro da validade.
    """
    from .. import auth

    registro = get(sid)
    if registro is None:
        return None

    kind, name = registro.get("kind"), registro.get("name", "")
    if kind == "admin":
        chaves = fsdb.read_json(settings.data_root / "keys" / "admin.json", {"keys": []})
        if not any(e.get("id", "admin") == name for e in chaves.get("keys", [])):
            return None
        return auth.Principal("admin", name)

    if kind == "subadmin":
        from . import invites, owners

        code = owners.code_of(name)
        ok, _ = invites.is_valid_for_console(code)
        if not ok or owners.disabled(name):
            return None
        return auth.Principal("subadmin", name)

    return None


def delete(sid: str) -> bool:
    if not sid:
        return False
    with fsdb.locked(settings.data_root):
        dados = _load()
        if sid not in dados:
            return False
        del dados[sid]
        fsdb.write_json(_path(), dados, mode=0o600)
    return True


def delete_all(name: str) -> int:
    """Encerra todas as sessões de uma identidade (sair de todos os
    dispositivos)."""
    with fsdb.locked(settings.data_root):
        dados = _load()
        alvo = [k for k, v in dados.items() if v.get("name") == name]
        for k in alvo:
            del dados[k]
        if alvo:
            fsdb.write_json(_path(), dados, mode=0o600)
    return len(alvo)


def list_for(name: str) -> list[dict]:
    agora = time.time()
    return [
        {"id": k[:8] + "…", "created_at": v.get("created_at"), "expires_at": v.get("expires_at"), "ip": v.get("ip", "")}
        for k, v in sorted(_load().items(), key=lambda kv: -kv[1].get("created_at", 0))
        if v.get("name") == name and v.get("expires_at", 0) > agora
    ]
