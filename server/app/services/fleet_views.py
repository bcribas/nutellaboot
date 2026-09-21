"""A visão da frota: o que cada um quer ver no dashboard e nos laboratórios.

A administração enxerga tudo, e o dashboard dela virou a soma das sedes da
competição com os laboratórios de todo mundo que entrou por convite. A visão é
o recorte, guardado NO SERVIDOR por dono (vale em qualquer navegador e no
telão):

    mine    só as imagens de quem olha (o padrão)
    all     tudo o que ele pode ver
    owners  as imagens destes donos (só a administração)
    custom  estas imagens, escolhidas à mão

Três regras:

- a visão só ESTREITA. O teto continua sendo `ownership.visible_site_images`
  (para o sub-admin, as dele) e `dashboard_hidden` segue exclusão dura;
- imagem criada depois de um `custom` salvo fica FORA até ser escolhida (o
  laboratório novo de alguém não pode pular para o telão sozinho). `mine` e
  `owners` pegam as novas daqueles donos;
- uma chave `labs:read` pode SEGUIR a visão da administração (`follow`), e o
  glob dela continua sendo o teto: o link compartilhado mostra o que o admin
  escolheu, sem poder alargar-se sozinho.
"""

from __future__ import annotations

import time

from .. import fsdb
from ..settings import settings
from . import ownership, store

MODOS = ("mine", "all", "owners", "custom")
PADRAO = {"mode": "mine", "owners": [], "images": []}
NOVAS_NO_AVISO = 20


def _caminho():
    return settings.data_root / "fleet-views.json"


def _todas() -> dict:
    return fsdb.read_json(_caminho(), {}) or {}


def get(owner: str) -> dict:
    return {**PADRAO, **(_todas().get(owner) or {})}


def put(owner: str, visao: dict, by: str = "") -> dict:
    nova = {
        "mode": visao["mode"],
        "owners": list(visao.get("owners") or []),
        "images": list(visao.get("images") or []),
        "updated_at": int(time.time()),
        "updated_by": by,
    }
    with fsdb.locked(settings.data_root / "fleet-views.d"):
        todas = _todas()
        todas[owner] = nova
        fsdb.write_json(_caminho(), todas, mode=0o600)
    return nova


def purge_image(image_id: str) -> None:
    """Imagem apagada sai de toda seleção: senão um id recriado por outra
    pessoa entraria calado no telão de quem tinha escolhido o antigo."""
    with fsdb.locked(settings.data_root / "fleet-views.d"):
        todas = _todas()
        mudou = False
        for visao in todas.values():
            if image_id in (visao.get("images") or []):
                visao["images"] = [i for i in visao["images"] if i != image_id]
                mudou = True
        if mudou:
            fsdb.write_json(_caminho(), todas, mode=0o600)


def _dono(info: dict) -> str:
    return str(info.get("owner") or "admin")


def validar(p, visao: dict) -> dict:
    """Devolve a visão normalizada ou levanta ValueError com a frase do 400."""
    modo = visao.get("mode")
    if modo not in MODOS:
        raise ValueError(f"mode é um de: {', '.join(MODOS)}")
    visiveis = ownership.visible_site_images(p)
    out = {"mode": modo, "owners": [], "images": []}
    if modo == "owners":
        if not ownership.is_admin(p):
            raise ValueError("só a administração filtra por dono")
        refs = {ownership.owner_ref(_dono(i)) if _dono(i) != "admin" else "admin" for i in visiveis}
        pedidos = [str(o) for o in visao.get("owners") or []]
        ruins = [o for o in pedidos if o not in refs]
        if ruins:
            raise ValueError(f"donos desconhecidos: {', '.join(ruins)}")
        out["owners"] = pedidos
    if modo == "custom":
        ids = {i["id"] for i in visiveis}
        pedidas = [str(i) for i in visao.get("images") or []]
        # o que é de outro dono é "desconhecido", como no resto do console
        ruins = [i for i in pedidas if i not in ids]
        if ruins:
            raise ValueError(f"imagens desconhecidas: {', '.join(ruins)}")
        out["images"] = pedidas
    return out


def _ref_do_dono(info: dict) -> str:
    dono = _dono(info)
    return "admin" if dono == "admin" else ownership.owner_ref(dono)


def _filtra(visao: dict, base: list[dict], dono_de_quem_olha: str) -> list[dict]:
    modo = visao.get("mode", "mine")
    if modo == "all":
        return base
    if modo == "owners":
        quer = set(visao.get("owners") or [])
        return [i for i in base if _ref_do_dono(i) in quer]
    if modo == "custom":
        quer = set(visao.get("images") or [])
        return [i for i in base if i["id"] in quer]
    return [i for i in base if _dono(i) == dono_de_quem_olha]


def resolver(p, *, view: str = "", owner: str = "") -> tuple[list[dict], dict]:
    """As imagens que `p` vê na frota AGORA, e o resumo do recorte.

    `view` (`all`|`mine`) e `owner` (um `owner_ref`) são a olhada sem salvar;
    valem só para o console. Chave de serviço os ignora: um link compartilhado
    não pode se alargar sozinho."""
    base = [i for i in ownership.visible_site_images(p) if store.site_image_visivel_na_frota(i)]
    if p.kind == "service":
        seguido = getattr(p, "follow", "")
        if not seguido:
            return base, {}
        return _filtra(get(seguido), base, seguido), {"following": True}

    salva = get(p.owner)
    visao = salva
    if owner and ownership.is_admin(p):
        visao = {"mode": "owners", "owners": [owner]}
    elif view in ("all", "mine"):
        visao = {"mode": view}
    escolhidas = _filtra(visao, base, p.owner)
    dentro = {i["id"] for i in escolhidas}
    desde = salva.get("updated_at") or 0
    novas = [
        i["id"] for i in base
        if i["id"] not in dentro and salva.get("mode") == "custom" and (i.get("created_at") or 0) > desde
    ]
    meta = {
        "mode": visao.get("mode", "mine"),
        "saved_mode": salva.get("mode", "mine"),
        "owners": visao.get("owners") or [],
        "shown": len(escolhidas),
        "total": len(base),
        "outside": len(base) - len(escolhidas),
        "new_outside": novas[:NOVAS_NO_AVISO],
        "updated_at": salva.get("updated_at"),
    }
    return escolhidas, meta


def donos(p) -> list[dict]:
    """Para o seletor da administração: cada dono com quantas imagens tem."""
    contagem: dict[str, dict] = {}
    for i in ownership.visible_site_images(p):
        if not store.site_image_visivel_na_frota(i):
            continue
        ref = _ref_do_dono(i)
        if ref not in contagem:
            contagem[ref] = {**ownership.owner_publico(_dono(i)), "images": 0}
        contagem[ref]["images"] += 1
    return sorted(contagem.values(), key=lambda d: (d["owner_kind"] != "admin", d["owner_label"].lower()))
