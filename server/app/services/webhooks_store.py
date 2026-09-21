"""Os webhooks de uma imagem, entrada por entrada.

O arquivo (`webhooks.json`, lista pura) nasceu sem id e sem dono, e só existia
o PUT da lista inteira: dois consumidores na mesma sede não conviviam, porque
quem instalava o seu apagava o do outro (o GET mascara o segredo, então nem dava
para reenviar o alheio). Cada entrada agora tem `id`, `owner` (`admin` ou
`service:<nome>`) e `created_at`. Arquivo antigo é migrado EM MEMÓRIA, com id
determinístico, e só vai para o disco na primeira escrita.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from contextlib import contextmanager

from .. import fsdb
from . import store

ARQUIVO = "webhooks.json"
MASCARA = "***"
TETO_POR_SERVICO = 5
SEGREDO_MINIMO = 16


def _caminho(image: str):
    return store.site_image_dir(image) / ARQUIVO


def _normaliza(conf: list) -> list[dict]:
    out = []
    for i, w in enumerate(conf or []):
        if not isinstance(w, dict) or not w.get("url"):
            continue
        dono = w.get("owner") or "admin"
        wid = w.get("id") or "wh_" + hashlib.sha256(f"{dono}\n{w['url']}\n{i}".encode()).hexdigest()[:12]
        out.append(
            {
                "id": wid,
                "url": str(w["url"]),
                "secret": str(w.get("secret", "")),
                "events": list(w.get("events") or []),
                "owner": dono,
                "created_at": int(w.get("created_at") or 0),
            }
        )
    return out


def carregar(image: str) -> list[dict]:
    return _normaliza(fsdb.read_json(_caminho(image), []) or [])


@contextmanager
def editar(image: str):
    """Lê, entrega a lista para mexer e grava, tudo sob o mesmo lock (o MOJ e
    a tela escrevem no mesmo arquivo)."""
    with fsdb.locked(store.site_image_dir(image) / "webhooks.d"):
        lista = carregar(image)
        yield lista
        fsdb.write_json(_caminho(image), lista, mode=0o600)


def novo_id() -> str:
    return "wh_" + secrets.token_hex(6)


def nova(url: str, secret: str, events: list, owner: str) -> dict:
    return {
        "id": novo_id(),
        "url": url,
        "secret": secret,
        "events": list(events),
        "owner": owner,
        "created_at": int(time.time()),
    }


def publica(w: dict) -> dict:
    """Como a entrada sai pela API: o segredo nunca volta em claro."""
    return {**w, "secret": MASCARA if w.get("secret") else ""}
