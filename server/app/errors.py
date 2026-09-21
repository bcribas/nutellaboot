"""Erros com código legível por máquina.

O corpo de erro sempre foi `{"detail": "<frase em português>"}`. Quem integra
(o MOJ) acabava decidindo pelo STATUS: todo 404 do vínculo virava "time fora do
roster", inclusive o de imagem inexistente. Agora todo erro leva também `code`,
que é o que o cliente deve ler: a frase pode mudar, o código não.

`erro(status, code, detail)` é o jeito de levantar; `HTTPException` comum
continua funcionando e ganha o código padrão do status (tabela abaixo).
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

PADRAO_POR_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}

# O catálogo é contrato: `GET /api/v1/events/types` o publica e um teste exige
# que todo código levantado no servidor esteja aqui (e vice-versa).
CODIGOS = {
    "bad_request": "pedido malformado",
    "unauthorized": "credencial ausente ou inválida",
    "forbidden": "credencial válida, sem permissão para isto",
    "not_found": "o recurso não existe",
    "method_not_allowed": "a rota não aceita este método",
    "conflict": "o estado atual não permite a operação",
    "payload_too_large": "corpo grande demais",
    "validation_error": "o corpo ou os parâmetros não passaram na validação",
    "rate_limited": "muitas tentativas; veja o cabeçalho Retry-After",
    "insufficient_scope": "a chave de serviço não tem o escopo que a rota pede",
    "image_out_of_scope": "a imagem existe, mas está fora dos globs da chave de serviço",
    "console_only": "rota do console: chave de serviço não entra, com escopo nenhum",
    "image_not_found": "a site-image não existe (ou é de outro dono)",
    "invalid_roster_entry": "entrada do roster sem user_id, ou malformada",
    "invalid_mac": "MAC fora do formato aa-bb-cc-dd-ee-ff",
    "user_not_in_roster": "o user_id do vínculo não está no roster da imagem",
    "command_not_found": "o comando não existe, é anterior ao registro ou já foi podado",
    "command_not_allowed": "o comando não está na lista de comandos aceitos",
    "command_blocked": "o comando está bloqueado pelo cadeado do modelo",
    "webhook_not_found": "o webhook não existe (ou é de outro dono)",
    "webhook_url_forbidden": "chave de serviço só aponta webhook para https público, ou destino liberado",
    "webhook_limit": "teto de webhooks por chave de serviço nesta imagem",
    "invalid_url": "a url não é http(s)",
    "invalid_event": "evento fora do catálogo",
    "invalid_secret": "segredo ausente, curto demais ou igual à máscara",
    "no_target": "nenhuma máquina alvo (ou `target` malformado)",
}


class ErroAPI(HTTPException):
    def __init__(self, status_code: int, code: str, detail, headers: dict | None = None):
        super().__init__(status_code, detail, headers)
        self.code = code


def erro(status_code: int, code: str, detail, headers: dict | None = None) -> ErroAPI:
    return ErroAPI(status_code, code, detail, headers)


def codigo_de(exc) -> str:
    return getattr(exc, "code", None) or PADRAO_POR_STATUS.get(exc.status_code, "error")


async def _http(request: Request, exc: StarletteHTTPException) -> Response:
    cabecalhos = getattr(exc, "headers", None)
    if exc.status_code in (204, 304) or exc.status_code < 200:
        return Response(status_code=exc.status_code, headers=cabecalhos)
    return JSONResponse(
        {"detail": exc.detail, "code": codigo_de(exc)},
        status_code=exc.status_code,
        headers=cabecalhos,
    )


async def _validacao(request: Request, exc: RequestValidationError) -> Response:
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(
        {"detail": jsonable_encoder(exc.errors()), "code": "validation_error"}, status_code=422
    )


def instalar(app) -> None:
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _validacao)
