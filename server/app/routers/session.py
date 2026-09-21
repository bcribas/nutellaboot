"""Entrar e sair do console.

A chave (de administração ou o código de convite) é trocada uma vez por um
cookie de sessão. Depois disso o navegador não guarda credencial nenhuma — o
que resolve o incômodo de redigitar a chave e, de quebra, tira a credencial do
alcance de qualquer script da página.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from .. import auth
from ..services import ownership, ratelimit, sessions

router = APIRouter(prefix="/api/v1")


@router.post("/session")
async def login(body: dict, request: Request, response: Response) -> dict:
    """Troca a chave por um cookie de sessão."""
    chave = str(body.get("key", "")).strip()
    ip = ratelimit.client_ip(request)

    p = auth.identify(chave) if chave else None
    if p is not None and p.kind == "service":
        # chave válida, porta errada: não é tentativa de adivinhar código
        raise auth.recusa_de_console(p)
    if p is None or p.kind not in sessions.TIPOS:
        # mesmo limitador da autenticação por cabeçalho: um código de convite é
        # curto o bastante para ser tentado na força bruta
        ratelimit.exigir(f"console:{ip}", rate=0.2, burst=10)
        raise HTTPException(401, "chave ou código inválido")

    sessao = sessions.create(p.kind, p.name, ip=ip, key_fp=p.key_fp)
    sessions.set_cookie(response, sessao["id"])
    return {"ok": True, "expires_at": sessao["expires_at"], **ownership.whoami(p)}


def _sid(request: Request) -> str:
    """O cookie só vale com o cabeçalho de console, aqui como em toda rota.

    `SameSite=Strict` já barraria a requisição de outro site, mas isto é a
    segunda camada: sem ela, `DELETE /session?all=true` seria a única escrita
    do console sem defesa própria contra CSRF no dia em que o `SameSite`
    precisasse afrouxar.
    """
    if request.headers.get(auth.HEADER_CONSOLE) is None:
        raise HTTPException(401, "credencial ausente ou inválida")
    return request.cookies.get(sessions.COOKIE, "")


@router.get("/session")
async def current(request: Request) -> dict:
    """Quem está logado nesta sessão e até quando."""
    sid = _sid(request)
    # resolver ANTES de ler o registro: se esta requisição renovou a sessão,
    # o expires_at que volta já é o novo
    p = sessions.resolve(sid)
    registro = sessions.get(sid) if p else None
    if p is None or registro is None:
        raise HTTPException(401, "sem sessão")
    return {
        "expires_at": registro["expires_at"],
        "created_at": registro["created_at"],
        "sessions": sessions.list_for(p.name),
        **ownership.whoami(p),
    }


@router.delete("/session")
async def logout(request: Request, response: Response, all: bool = False) -> dict:
    """Encerra esta sessão, ou todas as desta identidade com `?all=true`
    (o "sair de todos os dispositivos", para quando uma máquina se perde)."""
    sid = _sid(request)
    # ler o dono ANTES de apagar: depois não há mais como saber de quem era
    registro = sessions.get(sid)
    quantas = 0
    if all and registro:
        quantas = sessions.delete_all(registro["name"])
    else:
        quantas = 1 if sessions.delete(sid) else 0
    response.delete_cookie(sessions.COOKIE, path="/")
    return {"ok": True, "ended": quantas}
