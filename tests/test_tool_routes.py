"""As rotas que as ferramentas de linha de comando chamam precisam existir.

`tools/nb3-gerar-squash` ficou chamando `/api/v1/templates/…` depois da
renomeação e ninguém percebeu: o erro só apareceria no dia de gerar a camada
base da temporada, que é uma vez por ano e sob pressão. Este teste compara o
que as ferramentas chamam com o OpenAPI de verdade.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"

# O que for interpolado no caminho vira {param}: variável de shell ($X, ${X}),
# expressão de f-string ({args.model}, {f}) e %s de format.
INTERPOLACAO = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\{[^{}]+\}|%s")


def rotas_da_api() -> set[str]:
    from server.app.main import app

    return set(app.openapi()["paths"])


def normaliza(caminho: str) -> str:
    """`/api/v1/site-images/$IMAGEM/layers` -> `/api/v1/site-images/{p}/layers`"""
    return INTERPOLACAO.sub("{p}", caminho.rstrip("/"))


def chamadas_das_ferramentas() -> list[tuple[str, str]]:
    achadas = []
    for p in sorted(TOOLS.iterdir()):
        if not p.is_file():
            continue
        texto = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(/api/v1/[A-Za-z0-9_${}/.\-]*)", texto):
            achadas.append((p.name, m.group(1)))
    return achadas


@pytest.mark.parametrize("ferramenta,rota", chamadas_das_ferramentas(), ids=lambda v: str(v))
def test_rota_chamada_pela_ferramenta_existe(ferramenta, rota):
    # a ferramenta de migração cita caminhos antigos de propósito, na descrição
    if ferramenta == "nb3-migrate-names":
        pytest.skip("a migração documenta os caminhos antigos")

    alvo = normaliza(rota)
    padroes = {re.sub(r"\{[^}]+\}", "{p}", r.rstrip("/")) for r in rotas_da_api()}
    # o alias legado não aparece no OpenAPI (tem uma rota só), mas responde
    padroes |= {r.replace("/api/v1/site-images", "/api/v1/images") for r in padroes}
    assert alvo in padroes, f"{ferramenta} chama {rota}, que não é uma rota da API"
