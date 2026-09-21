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

# Renovação deslizante: a sessão vale DURACAO a partir do último uso, com
# granularidade de um dia — sessions.json é reescrito no máximo uma vez por
# dia por sessão. Só requisição de console renova (ver auth.principal): é a
# única que pode levar o cookie novo de volta, e sem cookie novo o navegador
# apaga o antigo no fim do Max-Age original, com a renovação em disco valendo
# nada.
RENOVA_A_CADA = 24 * 3600

# Só quem entra pelo console tem sessão. Chave de serviço (MOJ), token de
# imagem e chave de máquina continuam só no Bearer: são credenciais de
# programa, não de navegador.
TIPOS = ("admin", "subadmin")


def _path():
    return settings.data_root / "sessions.json"


def _load() -> dict:
    return fsdb.read_json(_path(), {}) or {}


def create(kind: str, name: str, *, ip: str = "", key_fp: str = "") -> dict:
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
        "renewed_at": agora,
        "ip": ip[:45],
    }
    if key_fp:
        # a sessão de admin pertence a UMA chave: revogá-la derruba a sessão
        # mesmo que exista outra chave com o mesmo id
        registro["key_fp"] = key_fp
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


def _renovar(sid: str, registro: dict, agora: float) -> bool:
    """Empurra expires_at para agora+DURACAO se a última renovação tem mais de
    um dia. Devolve True se escreveu (o chamador reemite o cookie)."""
    ultima = registro.get("renewed_at") or registro.get("created_at", 0)
    if agora - ultima < RENOVA_A_CADA:
        return False
    with fsdb.locked(settings.data_root):
        dados = _load()
        atual = dados.get(sid)
        # sumiu (logout concorrente) ou venceu enquanto esperávamos o lock
        if atual is None or atual.get("expires_at", 0) <= agora:
            return False
        atual["expires_at"] = agora + DURACAO
        atual["renewed_at"] = agora
        # já que vai escrever, aproveita e poda as vencidas (como create())
        dados = {k: v for k, v in dados.items() if v.get("expires_at", 0) > agora}
        fsdb.write_json(_path(), dados, mode=0o600)
    return True


def resolve(sid: str, *, renovar: bool = True):
    """Devolve o Principal da sessão, revalidando a identidade.

    É esta revalidação que mantém o comportamento de sempre: trocar a chave de
    administração, revogar o convite ou suspender o sub-admin derruba o acesso
    na hora, mesmo com a sessão ainda dentro da validade.

    Com `renovar`, estende a validade (ver _renovar) e marca
    `p.sessao_renovada` para auth.principal reemitir o cookie. A renovação vem
    DEPOIS da revalidação: sessão de chave trocada ou convite revogado não
    ganha sobrevida.
    """
    from .. import auth

    registro = get(sid)
    if registro is None:
        return None

    kind, name = registro.get("kind"), registro.get("name", "")
    p = None
    if kind == "admin":
        chaves = fsdb.read_json(settings.data_root / "keys" / "admin.json", {"keys": []})
        fp = registro.get("key_fp", "")
        # sessão antiga (sem fp) continua valendo pelo id, como sempre
        if any(
            e.get("id", "admin") == name and (not fp or str(e.get("sha256", ""))[:8] == fp)
            for e in chaves.get("keys", [])
        ):
            p = auth.Principal("admin", name, key_fp=fp)
    elif kind == "subadmin":
        from . import invites, owners

        code = owners.code_of(name)
        ok, _ = invites.is_valid_for_console(code)
        if ok and not owners.disabled(name):
            p = auth.Principal("subadmin", name)
    if p is None:
        return None
    if renovar and _renovar(sid, registro, time.time()):
        p.sessao_renovada = True
    return p


def set_cookie(resp, sid: str) -> None:
    """O Set-Cookie do login e da renovação — um lugar só."""
    resp.set_cookie(
        COOKIE,
        sid,
        max_age=DURACAO,
        httponly=True,
        # quem termina TLS é o nginx; o backend só fala HTTP no loopback
        secure=True,
        # o console não é linkado de fora, então Strict não custa nada e já
        # barra requisição vinda de outro site
        samesite="strict",
        path="/",
    )


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


def delete_da_chave(name: str, key_fp: str) -> int:
    """Encerra as sessões abertas com UMA chave de admin (a que foi revogada).
    Sessão antiga, sem impressão digital, cai junto: não dá para saber de qual
    chave veio, e na dúvida cai."""
    with fsdb.locked(settings.data_root):
        dados = _load()
        alvo = [
            k for k, v in dados.items()
            if v.get("kind") == "admin" and v.get("name") == name and v.get("key_fp", key_fp) == key_fp
        ]
        for k in alvo:
            del dados[k]
        if alvo:
            fsdb.write_json(_path(), dados, mode=0o600)
    return len(alvo)


def contar_da_chave(name: str, key_fp: str) -> int:
    agora = time.time()
    return sum(
        1 for v in _load().values()
        if v.get("kind") == "admin" and v.get("name") == name and v.get("expires_at", 0) > agora
        and v.get("key_fp", key_fp) == key_fp
    )


def list_for(name: str) -> list[dict]:
    agora = time.time()
    return [
        {"id": k[:8] + "…", "created_at": v.get("created_at"), "expires_at": v.get("expires_at"), "ip": v.get("ip", "")}
        for k, v in sorted(_load().items(), key=lambda kv: -kv[1].get("created_at", 0))
        if v.get("name") == name and v.get("expires_at", 0) > agora
    ]
