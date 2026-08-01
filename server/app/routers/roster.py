"""Lista de times/usuários (roster) e vínculo usuário↔máquina.

O MOJ envia o roster com os dados que a tela de bloqueio exibe (nome do time,
organização, país) e os logotipos como blob. O vínculo aponta para uma entrada
do roster.

No nb2 isso era um grafo de symlinks em times-maquina/ criado por um CGI SEM
autenticação nenhuma, que interpolava parâmetros do usuário direto em `rm` e
`ln -s`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import auth, fsdb
from ..services import machines as m
from ..services import store
from ..services.notify import notify

router = APIRouter(prefix="/api/v1")

LOGO_MAX = 2 * 1024 * 1024
LOGO_TYPES = {
    b"<svg": ("svg", "image/svg+xml"),
    b"<?xm": ("svg", "image/svg+xml"),
    b"\x89PNG": ("png", "image/png"),
}


def _roster(image: str) -> list[dict]:
    return fsdb.read_json(store.image_dir(image) / "roster.json", []) or []


@router.get("/images/{image}/roster")
async def get_roster(
    image: str, p=Depends(auth.require_image_access(service_scope="roster:read"))
) -> dict:
    return {"roster": _roster(image)}


@router.put("/images/{image}/roster")
async def put_roster(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="roster:write"))
) -> dict:
    roster = body.get("roster", body if isinstance(body, list) else None)
    if not isinstance(roster, list):
        raise HTTPException(400, "esperava {roster: [...]}")
    limpo = []
    for entry in roster:
        if not isinstance(entry, dict) or not entry.get("user_id"):
            raise HTTPException(400, "cada entrada precisa de user_id")
        limpo.append(
            {
                "user_id": str(entry["user_id"]),
                "name": str(entry.get("name", "")),
                "display_name": str(entry.get("display_name", "")),
                "organization": entry.get("organization") or {},
                "country": str(entry.get("country", "")),
                "seat": str(entry.get("seat", "")),
            }
        )
    fsdb.write_json(store.image_dir(image) / "roster.json", limpo)
    return {"ok": True, "entries": len(limpo)}


@router.put("/images/{image}/roster/logos/{org_id}")
async def put_logo(
    image: str,
    org_id: str,
    file: UploadFile = File(...),
    p=Depends(auth.require_image_access(service_scope="roster:write")),
) -> dict:
    if "/" in org_id or ".." in org_id:
        raise HTTPException(400, "identificador de organização inválido")
    data = await file.read(LOGO_MAX + 1)
    if len(data) > LOGO_MAX:
        raise HTTPException(413, "logotipo grande demais")
    head = data[:4]
    kind = next((v for k, v in LOGO_TYPES.items() if head.startswith(k)), None)
    if kind is None:
        raise HTTPException(400, "envie SVG ou PNG")
    ext, _ = kind
    d = store.image_dir(image) / "roster" / "logos"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{org_id}.*"):
        old.unlink()
    (d / f"{org_id}.{ext}").write_bytes(data)
    return {"ok": True, "org_id": org_id, "format": ext, "size": len(data)}


@router.put("/images/{image}/machines/{mac}/binding")
async def put_binding(
    image: str, mac: str, body: dict, p=Depends(auth.require_image_access(service_scope="bindings:write"))
) -> dict:
    mac = m.normalize_mac(mac)
    if not m.valid_mac(mac):
        raise HTTPException(400, "MAC inválido")
    user_id = body.get("user_id")
    binding = {"bound_at": __import__("time").time(), "by": p.name}
    if user_id:
        entry = next((e for e in _roster(image) if e["user_id"] == str(user_id)), None)
        if entry is None:
            raise HTTPException(404, f"user_id {user_id} não está no roster desta imagem")
        binding.update({"user_id": entry["user_id"], "seat": body.get("seat", entry.get("seat", ""))})
    else:
        binding.update(
            {
                "name": str(body.get("name", "")),
                "seat": str(body.get("seat", "")),
            }
        )
    d = m.machine_dir(image, mac)
    d.mkdir(parents=True, exist_ok=True)
    fsdb.write_json(d / "binding.json", binding)
    notify.publish(image, {"event": "machine.bound", "data": {"mac": mac}, "at": 0})
    return binding


@router.delete("/images/{image}/machines/{mac}/binding", status_code=204)
async def delete_binding(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope="bindings:write"))
) -> None:
    mac = m.normalize_mac(mac)
    (m.machine_dir(image, mac) / "binding.json").unlink(missing_ok=True)
    notify.publish(image, {"event": "machine.unbound", "data": {"mac": mac}, "at": 0})


@router.get("/images/{image}/bindings")
async def list_bindings(
    image: str, p=Depends(auth.require_image_access(service_scope="machines:read"))
) -> dict:
    out = []
    for mac in m.list_macs(image):
        b = fsdb.read_json(m.machine_dir(image, mac) / "binding.json")
        if b:
            out.append({"mac": mac, **b})
    return {"bindings": out}


# --- consumido pela tela de bloqueio (sem autenticação, como o resto do boot) ---


def lockinfo(image: str, mac: str) -> dict:
    info = store.get_image(image) or {}
    binding = fsdb.read_json(m.machine_dir(image, mac) / "binding.json") or {}
    entry = {}
    if binding.get("user_id"):
        entry = next(
            (e for e in _roster(image) if e["user_id"] == binding["user_id"]), {}
        )
    org = entry.get("organization") or {}
    org_id = str(org.get("id", ""))
    logo_url = ""
    if org_id:
        d = store.image_dir(image) / "roster" / "logos"
        if any(d.glob(f"{org_id}.*")) if d.is_dir() else False:
            logo_url = f"/boot/v3/{image}/roster/logos/{org_id}"
    return {
        "site": info.get("fullname", image),
        "image": image,
        "mac": mac,
        "seat": binding.get("seat", ""),
        "team": {
            "name": entry.get("name", binding.get("name", "")),
            "display_name": entry.get("display_name", ""),
        },
        "organization": {"id": org_id, "name": org.get("name", ""), "logo_url": logo_url},
        "country": entry.get("country", ""),
    }


def logo_response(image: str, org_id: str) -> FileResponse:
    if "/" in org_id or ".." in org_id:
        raise HTTPException(400, "identificador inválido")
    d = store.image_dir(image) / "roster" / "logos"
    for ext, media in (("svg", "image/svg+xml"), ("png", "image/png")):
        f = d / f"{org_id}.{ext}"
        if f.is_file():
            return FileResponse(f, media_type=media)
    raise HTTPException(404, "sem logotipo")
