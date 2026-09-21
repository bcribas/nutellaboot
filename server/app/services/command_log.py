"""O registro de cada comando: para quem foi e quem confirmou.

Comando era dispare-e-esqueça. `POST …/commands` devolvia `{command_id,
machines}` e o resto se perdia: o arquivo da fila some no ack e na expiração, e
o `acks.log` é por máquina e tem teto. Não havia como responder "quem executou
o precontest?" sem abrir máquina por máquina.

Cada comando ganha `commands/<cid>.json` (o que foi, para quem, até quando
vale) e `commands/<cid>.acks.jsonl` (uma linha por máquina que confirmou ou
deixou caducar). A máquina desligada nunca escreve nada: o estado dela se
DEDUZ, `pending` enquanto o comando vale e `expired` depois.
"""

from __future__ import annotations

import json
import re
import time

from .. import fsdb
from . import store

CID = re.compile(r"^[0-9a-f]{12}$")
GUARDA_DIAS = 7
GUARDA_MAX = 500


def _dir(image: str):
    return store.site_image_dir(image) / "commands"


def valido(cid: str) -> bool:
    # o cid vem da URL (do ack da máquina, inclusive) e vira nome de arquivo
    return bool(CID.match(str(cid)))


def abrir(image: str, cid: str, *, command: str, args: str, by: str,
          created_at: float, not_before: float, ttl: int, targets: list[str]) -> None:
    d = _dir(image)
    d.mkdir(parents=True, exist_ok=True)
    fsdb.write_json(
        d / f"{cid}.json",
        {
            "id": cid,
            "command": command,
            "args": args,
            "by": by,
            "created_at": int(created_at),
            "not_before": int(not_before),
            "ttl": int(ttl),
            "targets": list(targets),
        },
    )
    _podar(d)


def _podar(d) -> None:
    registros = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime)
    limite = time.time() - GUARDA_DIAS * 86400
    velhos = [f for f in registros if f.stat().st_mtime < limite]
    excesso = registros[: max(0, len(registros) - GUARDA_MAX)]
    for f in {*velhos, *excesso}:
        f.unlink(missing_ok=True)
        f.with_name(f.stem + ".acks.jsonl").unlink(missing_ok=True)


def ler(image: str, cid: str) -> dict | None:
    if not valido(cid):
        return None
    return fsdb.read_json(_dir(image) / f"{cid}.json")


def anotar(image: str, cid: str, mac: str, status: str, *, output_bytes: int = 0) -> None:
    """Sem registro (comando de antes desta versão, ou já podado), não anota:
    um ack com cid inventado não pode criar arquivo."""
    if ler(image, cid) is None:
        return
    linha = {"mac": mac, "at": int(time.time()), "status": str(status)[:40], "output_bytes": int(output_bytes)}
    with open(_dir(image) / f"{cid}.acks.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(linha, ensure_ascii=False) + "\n")


def estado(image: str, cid: str, agora: float | None = None) -> dict | None:
    rec = ler(image, cid)
    if rec is None:
        return None
    agora = time.time() if agora is None else agora
    vistos: dict[str, dict] = {}
    arq = _dir(image) / f"{cid}.acks.jsonl"
    if arq.is_file():
        for linha in arq.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                a = json.loads(linha)
            except ValueError:
                continue
            vistos[a.get("mac", "")] = a  # a última linha da máquina vence
    expira = rec["not_before"] + rec["ttl"]
    alvos, resumo = [], {"acked": 0, "pending": 0, "expired": 0}
    for mac in rec["targets"]:
        a = vistos.get(mac)
        if a is None:
            est = {"mac": mac, "state": "expired" if agora > expira else "pending"}
        elif a.get("status") == "expired":
            est = {"mac": mac, "state": "expired", "at": a.get("at")}
        else:
            est = {"mac": mac, "state": "acked", "status": a.get("status"), "at": a.get("at"),
                   "output_bytes": a.get("output_bytes", 0)}
        resumo[est["state"]] += 1
        alvos.append(est)
    return {
        "command_id": cid,
        "command": rec["command"],
        "args": rec["args"],
        "by": rec["by"],
        "created_at": rec["created_at"],
        "not_before": rec["not_before"],
        "expires_at": expira,
        "machines": len(rec["targets"]),
        "summary": resumo,
        "targets": alvos,
    }
