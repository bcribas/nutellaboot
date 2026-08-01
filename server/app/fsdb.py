"""Banco-filesystem: escrita atômica, JSON e locks por diretório.

Invariantes (ver docs/architecture.md):
- toda mutação de arquivo passa por tmp no mesmo diretório + os.replace;
- concorrência entre mutações de um mesmo diretório é serializada por
  flock em `<dir>/.lock`;
- leituras nunca precisam de lock (os.replace é atômico).
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def read_json(path: Path | str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def read_text(path: Path | str, default: str | None = None) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return default


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: Path | str, obj: Any, mode: int = 0o644) -> None:
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode() + b"\n"
    _atomic_write(Path(path), data, mode)


def write_text(path: Path | str, text: str, mode: int = 0o644) -> None:
    _atomic_write(Path(path), text.encode(), mode)


@contextmanager
def locked(dirpath: Path | str) -> Iterator[None]:
    """flock exclusivo em <dir>/.lock — serializa mutações do diretório."""
    dirpath = Path(dirpath)
    dirpath.mkdir(parents=True, exist_ok=True)
    with open(dirpath / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
