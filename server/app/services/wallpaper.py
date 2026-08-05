"""Papel de parede: o da sede, o do modelo, e quem manda.

Antes isto vivia só em `routers/config.py`, e só existia para a site-image. A
organização precisa do contrário: definir o papel de parede uma vez no modelo e
que TODA sede dele use aquele, sem poder trocar.

**A herança é por consulta, não por cópia.** A sede que não tem papel de parede
próprio usa o do modelo, resolvido na hora de servir. Copiar na criação seria
mais simples e estaria errado: trocar o papel de parede do modelo na véspera
não chegaria a nenhuma sede já criada, que é justamente quando isso acontece.

São três consumidores, e todos passam por aqui — errar um deles dá o pior tipo
de defeito, o parcial: `stuffgen` (o md5, que é o que faz a máquina baixar),
`/boot/v3/{img}/wallpaper` (o download do boot) e a prévia do configureitor.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import fsdb
from . import store

MAX_BYTES = 12 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

ARQUIVO = "wallpaper.png"
META = "wallpaper.json"


class WallpaperError(ValueError):
    pass


def validar(data: bytes) -> str:
    """Devolve o content-type, ou levanta com a explicação para a tela.

    Pelo NÚMERO MÁGICO e não pela extensão: o arquivo vai para o disco de toda
    máquina da sala, e a extensão é o que o navegador mandou.
    """
    if not data:
        raise WallpaperError("arquivo vazio")
    if len(data) > MAX_BYTES:
        raise WallpaperError(f"arquivo maior que {MAX_BYTES // 2**20} MB")
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    raise WallpaperError("formato não reconhecido: envie PNG ou JPEG")


def gravar(d: Path, data: bytes, filename: str = "") -> dict:
    tipo = validar(data)
    meta = {
        "md5": hashlib.md5(data).hexdigest(),
        "size": len(data),
        "filename": filename,
        "content_type": tipo,
    }
    with fsdb.locked(d):
        (d / ARQUIVO).write_bytes(data)
        fsdb.write_json(d / META, meta)
    return meta


def apagar(d: Path) -> None:
    with fsdb.locked(d):
        (d / ARQUIVO).unlink(missing_ok=True)
        (d / META).unlink(missing_ok=True)


def _em(d: Path) -> tuple[Path, dict] | None:
    meta = fsdb.read_json(d / META)
    if not meta or not (d / ARQUIVO).is_file():
        return None
    return d / ARQUIVO, meta


def do_modelo(model: str) -> tuple[Path, dict] | None:
    return _em(store.model_dir(model)) if model else None


def efetivo(image_id: str) -> tuple[Path, dict] | None:
    """O que esta sede realmente usa: o dela, ou o do modelo.

    Devolve `(caminho, meta)` ou None. O `meta` ganha `origin` (`"image"` ou
    `"model"`) porque a tela precisa dizer de onde veio — um papel de parede que
    a pessoa não reconhece e não consegue trocar, sem explicação, vira chamado.
    """
    proprio = _em(store.site_image_dir(image_id))
    if proprio:
        return proprio[0], {**proprio[1], "origin": "image"}
    info = store.get_site_image(image_id) or {}
    do_mod = do_modelo(info.get("model", ""))
    if do_mod:
        return do_mod[0], {**do_mod[1], "origin": "model"}
    return None


def travado(image_id: str) -> bool:
    """Travado pelo modelo OU pela própria sede.

    O do modelo vale para todas e não se contorna sede a sede — é o que
    "o modelo manda" quer dizer. O da sede continua existindo porque os
    convites já o emitem por imagem.

    A ordem das três checagens é o contrato inteiro:

    1. trava DA PRÓPRIA imagem vale sempre — é fixada de propósito pelo
       convite em sedes Livres (wallpaper de patrocinador numa imagem que no
       resto é `unlocked`), então o `unlocked` NÃO a desliga;
    2. imagem `unlocked` escapa da trava DO MODELO — a mesma cláusula dos
       campos de schema (`config.pode_editar`: locked e não admin e não
       unlocked). Era o que faltava: a sede liberada continuava presa à trava
       do modelo, com a tela obedecendo o servidor errado;
    3. senão, vale o modelo.
    """
    info = store.get_site_image(image_id) or {}
    if info.get("wallpaper_locked"):
        return True
    if info.get("unlocked"):
        return False
    modelo = fsdb.read_json(store.model_dir(info.get("model", "")) / "model.json", {}) or {}
    return bool(modelo.get("wallpaper_locked"))
