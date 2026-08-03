"""O papel de cada camada — em um lugar só.

Trocar a base entre temporadas casa por `role`, nunca por nome de arquivo: o
nome muda todo ano (`icpc-latam2025` → `maratonalinux2026`) e casar por nome
deixa as DUAS no modelo, com a máquina baixando duas raízes e montando uma
sobre a outra sem erro nenhum (invariante 13).

Isso só funciona se toda camada tiver papel. Camada gravada direto em disco por
ferramenta de importação nascia sem — e aí `replace_role="base"` não achava o
alvo, inseria a nova ao lado da velha, e a trava que conta bases achava 1
porque a antiga não contava. O incidente voltava inteiro, por outra porta.

A dedução é boa, mas é dedução: a base é a **última da lista** (a ordem é a
prioridade no overlay, e a base tem que perder para todas). Por isso as
ferramentas que a usam mostram o antes/depois.
"""

from __future__ import annotations

import re

PAPEIS = ("base", "telemetry", "wifi", "extra")

# Cada regra é (padrão no nome do arquivo, papel). A ordem importa: a primeira
# que casar vence.
REGRAS = [
    (re.compile(r"^telemetria-|^log\d*\.squash|^mlog"), "telemetry"),
    (re.compile(r"^wifis?\b|^wifi"), "wifi"),
]


def papel_de(camada: dict, *, e_ultima: bool) -> str:
    ja = camada.get("role")
    if ja in PAPEIS:
        return ja
    arquivo = str(camada.get("file", ""))
    for padrao, papel in REGRAS:
        if padrao.search(arquivo):
            return papel
    # a última da lista é a de menor prioridade no overlay: a base
    return "base" if e_ultima else "extra"


def marcar(camadas: list[dict]) -> list[dict]:
    """A lista com todo mundo com papel, preservando os que já tinham."""
    n = len(camadas)
    return [{**c, "role": papel_de(c, e_ultima=(i == n - 1))} for i, c in enumerate(camadas)]


def sem_papel(camadas: list[dict]) -> list[str]:
    """Os arquivos das camadas que não têm papel válido — o que faz o
    `replace_role` errar o alvo em silêncio."""
    return [str(c.get("file", "?")) for c in camadas if c.get("role") not in PAPEIS]
