"""Append em arquivos JSONL com teto de tamanho.

O nb2 acumulava o trace `set -x` de TODA requisição num log por sede que nunca
rotacionava — havia arquivos de 11 MB no repositório. Aqui todo append passa
por um teto: ao estourar, mantém-se a cauda.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CAP = 1 * 1024 * 1024


def append_capped(path: Path | str, line: str, cap: int = DEFAULT_CAP) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")
    try:
        if path.stat().st_size <= cap:
            return
    except FileNotFoundError:
        return

    # mantém a metade final e recomeça o arquivo de forma atômica
    with open(path, "rb") as fh:
        fh.seek(-cap // 2, os.SEEK_END)
        fh.readline()  # descarta a linha parcial
        tail = fh.read()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(tail)
    os.replace(tmp, path)
