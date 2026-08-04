"""A documentação da API não pode ficar para trás da API.

Ficou: quando escrevi este teste, `docs/api.md` não mencionava 13 das 89 rotas
— o auto-atendimento inteiro (`/public/*`), os pedidos, os convites como
endpoint, o relatório, os builds por imagem e as duas rotas de pendrive
criadas na mesma semana. Quem integra lê o documento, não o código.

O `/api/v1/docs` (OpenAPI navegável) existe e é sempre exato, mas responde
"quais campos" e nunca "por quê" — e é o porquê que evita a chamada errada.

Rota que não deve ser documentada entra em SILENCIOSAS **com o motivo
escrito**: o custo de esconder passa a ser uma linha justificada, e não o
esquecimento.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "api.md"

# Rotas deliberadamente fora do documento, e por quê.
SILENCIOSAS = {
    # a sessão do console tem seção em prosa própria, com o desenho do cookie
    # e o porquê do X-NB-Console — tabela não daria conta
    "/api/v1/session": "documentada na seção 'Sessão do console'",
}

# Servidas pelo próprio FastAPI, então não aparecem no `openapi()["paths"]`.
# O documento as cita, e citar está certo.
FORA_DO_OPENAPI = {"/api/v1/docs", "/api/v1/openapi.json"}


def _paths_reais() -> set[str]:
    from server.app.main import create_app

    return {
        p
        for p in create_app().openapi()["paths"]
        if p.startswith(("/api/v1", "/boot/v3"))
    }


def _metodos_reais() -> set[tuple[str, str]]:
    """(MÉTODO, caminho normalizado) de tudo que a API expõe."""
    from server.app.main import create_app

    fora = set()
    for caminho, ops in create_app().openapi()["paths"].items():
        if not caminho.startswith(("/api/v1", "/boot/v3")) or caminho in SILENCIOSAS:
            continue
        for metodo in ops:
            if metodo.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                fora.add((metodo.upper(), _normaliza(caminho)))
    return fora


def _metodos_citados() -> set[tuple[str, str]]:
    """O que as TABELAS do documento prometem, linha a linha.

    Comparar só caminhos deixava passar método novo em rota já documentada — foi
    assim que o `GET /commands` entrou sem ninguém notar, ao lado de um `POST`
    que já estava lá."""
    fora = set()
    for linha in DOC.read_text(encoding="utf-8").splitlines():
        if not linha.startswith("|"):
            continue
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        if len(celulas) < 2:
            continue
        metodos = re.findall(r"\b(GET|POST|PUT|PATCH|DELETE)\b", celulas[0])
        if not metodos:
            continue
        for caminho in re.findall(r"`(/(?:api/v1|boot/v3)[^`]*)`", celulas[1]):
            for m in metodos:
                fora.add((m, _normaliza(caminho.split("?")[0])))
    return fora


def _paths_citados() -> set[str]:
    """Os caminhos que o documento menciona, com os placeholders normalizados.

    O documento usa `{img}` e exemplos concretos (`26brbr`); o OpenAPI usa
    `{image}`. Comparar sem normalizar acusaria tudo."""
    texto = DOC.read_text(encoding="utf-8")
    achados = set(re.findall(r"/(?:api/v1|boot/v3)[A-Za-z0-9_{}./*-]*", texto))
    return {_normaliza(p) for p in achados}


# nomes de sede e MACs de exemplo que aparecem nos trechos de curl
_EXEMPLO = re.compile(
    r"/(?:2[0-9][a-z]{2,}[a-z0-9]*|[0-9a-f]{2}(?:-[0-9a-f]{2}){5}|unb|moj|team-[0-9]+)(?=/|$)",
    re.I,
)


def _normaliza(p: str) -> str:
    p = p.rstrip("/")
    p = _EXEMPLO.sub("/{X}", p)
    return re.sub(r"\{[a-z_]+\}", "{X}", p)


def test_toda_rota_esta_no_documento():
    reais = _paths_reais()
    citados = _paths_citados()
    faltando = sorted(
        p for p in reais if p not in SILENCIOSAS and _normaliza(p) not in citados
    )
    assert not faltando, (
        "rotas fora do docs/api.md (documente, ou explique em SILENCIOSAS):\n  "
        + "\n  ".join(faltando)
    )


def test_todo_metodo_esta_no_documento():
    """Rota já documentada que ganha um método novo é a mesma omissão: quem lê
    o documento não descobre que ela passou a responder também a outro verbo."""
    faltando = sorted(_metodos_reais() - _metodos_citados())
    assert not faltando, (
        "métodos fora do docs/api.md:\n  "
        + "\n  ".join(f"{m} {c}" for m, c in faltando)
    )


def test_as_silenciosas_ainda_existem():
    """Lista de exceção que sobrevive à rota é lixo que esconde a próxima."""
    reais = _paths_reais()
    orfas = sorted(p for p in SILENCIOSAS if p not in reais)
    assert not orfas, f"rotas em SILENCIOSAS que não existem mais: {orfas}"


def test_o_documento_nao_cita_rota_que_nao_existe():
    """Documentação que promete rota inexistente é pior que documentação
    faltando: quem integra escreve o código e só descobre no 404."""
    reais = {_normaliza(p) for p in _paths_reais()} | FORA_DO_OPENAPI
    # prefixos usados em prosa ("as rotas /api/v1/...") não são promessa
    citados = {
        p
        for p in _paths_citados()
        if p.count("/") > 2 and not p.endswith(("...", "…", "/*"))
    }
    fantasmas = sorted(p for p in citados if p not in reais)
    assert not fantasmas, f"caminhos citados que não existem: {fantasmas}"
