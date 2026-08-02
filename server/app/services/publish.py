"""Publicação de arquivos grandes no servidor de arquivos (files.mdp).

A máquina de gestão não deve servir camadas de vários GB nem imagens de
pendrive: elas são enviadas por SSH para o servidor de arquivos, e o manifest
passa a apontar para a URL pública de lá. Trocar por uma CDN no futuro é
editar `publish` no data/server.json — nada no código sabe o nome do host.

Estado por arquivo em `data/publish/<arquivo>.json`, que é o que alimenta o
botão de reenviar quando o envio falha (servidor fora do ar, rede caindo).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from .. import fsdb
from ..settings import settings

DEFAULT = {
    "enabled": False,
    "host": "files.mdp.naquadah.com.br",
    "user": "root",
    "paths": {
        "layers": "/var/www/html/maratonalinux",
        "usb": "/var/www/html/mlbootimages",
    },
    "base_urls": {
        "layers": "https://files.mdp.naquadah.com.br/maratonalinux",
        "usb": "https://files.mdp.naquadah.com.br/mlbootimages",
    },
    "timeout": 3600,
}


def conf() -> dict:
    server = fsdb.read_json(settings.data_root / "server.json", {}) or {}
    c = {**DEFAULT, **(server.get("publish") or {})}
    c["paths"] = {**DEFAULT["paths"], **(c.get("paths") or {})}
    c["base_urls"] = {**DEFAULT["base_urls"], **(c.get("base_urls") or {})}
    return c


def enabled() -> bool:
    return bool(conf().get("enabled"))


def public_url(filename: str, kind: str = "layers") -> str:
    return f"{conf()['base_urls'][kind].rstrip('/')}/{filename}"


def _state_path(filename: str) -> Path:
    return settings.data_root / "publish" / f"{filename}.json"


def state(filename: str) -> dict | None:
    return fsdb.read_json(_state_path(filename))


def list_state() -> list[dict]:
    d = settings.data_root / "publish"
    if not d.is_dir():
        return []
    out = [fsdb.read_json(f) for f in sorted(d.glob("*.json"))]
    return sorted(
        [s for s in out if s], key=lambda s: -(s.get("updated_at") or 0)
    )


def _record(filename: str, **fields) -> dict:
    entry = {"file": filename, "updated_at": time.time(), **fields}
    fsdb.write_json(_state_path(filename), entry)
    return entry


def publish_file(local: Path | str, kind: str = "layers") -> dict:
    """Envia o arquivo e devolve o estado resultante.

    Nunca levanta exceção: falha vira `status: "failed"` com a mensagem, para
    quem chamou seguir em frente (o boot continua com a URL local) e o
    operador reenviar pelo /admin/.
    """
    local = Path(local)
    filename = local.name
    c = conf()

    if not local.is_file():
        return _record(filename, kind=kind, status="failed", error="arquivo local não existe")
    if not c.get("enabled"):
        return _record(
            filename, kind=kind, status="disabled", error="publicação desligada em server.json"
        )

    destino = f"{c['user']}@{c['host']}:{c['paths'][kind].rstrip('/')}/"
    # NB3_PUBLISH_CMD permite trocar o transporte (e testar sem rede)
    base = os.environ.get("NB3_PUBLISH_CMD")
    if base:
        cmd = [*shlex.split(base), str(local), destino]
    else:
        cmd = [
            "rsync",
            "-a",
            "--partial",
            "--chmod=F644",
            "-e",
            "ssh -o BatchMode=yes -o ConnectTimeout=15",
            str(local),
            destino,
        ]

    _record(filename, kind=kind, status="sending", error="")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=int(c.get("timeout", 3600))
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return _record(filename, kind=kind, status="failed", error=str(e))

    if proc.returncode != 0:
        erro = (proc.stderr or proc.stdout or f"código {proc.returncode}").strip()[-500:]
        return _record(filename, kind=kind, status="failed", error=erro)

    return _record(
        filename,
        kind=kind,
        status="done",
        url=public_url(filename, kind),
        size=local.stat().st_size,
        published_at=time.time(),
        error="",
    )


def local_path(filename: str, kind: str) -> Path:
    """Onde o arquivo mora na máquina de gestão (para reenviar)."""
    if kind == "usb":
        return settings.data_root / "usb" / filename
    return settings.data_root / "blobs" / filename


def retry_failed() -> list[dict]:
    """Reenvia tudo que não está `done`."""
    out = []
    for s in list_state():
        if s.get("status") == "done":
            continue
        out.append(publish_file(local_path(s["file"], s.get("kind", "layers")), s.get("kind", "layers")))
    return out
