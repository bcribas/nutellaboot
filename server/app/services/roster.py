"""O roster de uma imagem: os times que a sede espera.

Vivia dentro da rota, com um único jeito de escrever (o PUT da lista inteira)
e sem lock. Dois problemas de quem integra: acrescentar UM time era ler,
modificar e regravar tudo, em corrida com qualquer outro escritor (a tela, o
MOJ de outra sede); e o roster vazio fazia todo vínculo do login voltar 404.

Aqui toda escrita segura o mesmo lock, há upsert e remoção de uma entrada, e
uma regra que atravessa tudo: **escrever o roster nunca apaga um vínculo**. A
entrada criada a reboque de um vínculo leva `source: "binding"`; o roster
oficial a sobrescreve à vontade (e ela perde a marca), mas se ele OMITIR um
time que está vinculado a uma máquina, a entrada fica, marcada.
"""

from __future__ import annotations

import re

from .. import fsdb
from . import bindings, store

ARQUIVO = "roster.json"
CAMPOS = ("user_id", "name", "display_name", "organization", "country", "seat")
_PAIS = re.compile(r"^[A-Za-z]{2,3}$")


def _caminho(image: str):
    return store.site_image_dir(image) / ARQUIVO


def trava(image: str):
    return fsdb.locked(store.site_image_dir(image) / "roster")


def ler(image: str) -> list[dict]:
    return fsdb.read_json(_caminho(image), []) or []


def normaliza(entry) -> dict:
    if not isinstance(entry, dict) or not entry.get("user_id"):
        raise ValueError("cada entrada precisa de user_id")
    org = entry.get("organization")
    pais = str(entry.get("country", "")).strip()
    return {
        "user_id": str(entry["user_id"]),
        "name": str(entry.get("name", "")),
        "display_name": str(entry.get("display_name", "")),
        "organization": org if isinstance(org, dict) else {},
        # alpha-2 ("BR") é o recomendado e alpha-3 passa; só uniformiza a caixa.
        # Nada aqui é recusado: o campo é rótulo, ninguém decide por ele.
        "country": pais.upper() if _PAIS.match(pais) else pais,
        "seat": str(entry.get("seat", "")),
    }


def achar(lista: list[dict], user_id: str) -> dict | None:
    return next((e for e in lista if e.get("user_id") == str(user_id)), None)


def upsert(image: str, entry: dict) -> tuple[dict, bool]:
    nova = normaliza(entry)
    with trava(image):
        lista = ler(image)
        atual = achar(lista, nova["user_id"])
        if atual is None:
            lista.append(nova)
        else:
            lista[lista.index(atual)] = nova  # oficial: perde a marca `source`
        fsdb.write_json(_caminho(image), lista)
    return nova, atual is None


def substituir(image: str, entradas: list) -> tuple[int, list[str]]:
    limpo = [normaliza(e) for e in entradas]
    enviados = {e["user_id"] for e in limpo}
    with trava(image):
        vinculados = bindings.user_ids_vinculados(image)
        mantidos = []
        for e in ler(image):
            if e.get("user_id") in vinculados and e["user_id"] not in enviados:
                mantidos.append({**e, "source": "binding"})
        fsdb.write_json(_caminho(image), limpo + mantidos)
    return len(limpo), [e["user_id"] for e in mantidos]


def remover(image: str, user_id: str) -> bool:
    with trava(image):
        lista = ler(image)
        atual = achar(lista, user_id)
        if atual is None:
            return False
        lista.remove(atual)
        fsdb.write_json(_caminho(image), lista)
    return True


def garantir(lista: list[dict], entry: dict) -> tuple[dict, bool]:
    """Para o vínculo com `create_roster_entry`: devolve a entrada do time,
    criando-a (marcada) se faltar. Mexe na lista recebida; quem chama segura o
    lock e grava."""
    atual = achar(lista, entry.get("user_id", ""))
    if atual is not None:
        return atual, False
    nova = {**normaliza(entry), "source": "binding"}
    lista.append(nova)
    return nova, True


def gravar(image: str, lista: list[dict]) -> None:
    fsdb.write_json(_caminho(image), lista)


def logos(image: str) -> list[str]:
    d = store.site_image_dir(image) / "roster" / "logos"
    return sorted({f.stem for f in d.iterdir() if f.is_file()}) if d.is_dir() else []
