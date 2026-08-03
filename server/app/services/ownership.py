"""Quem pode ver e mexer em quê.

Uma regra atravessa tudo aqui: para um sub-admin, o que é de outro dono
**não existe** — as rotas respondem 404, não 403. Um 403 confirmaria que o
nome está tomado e por quem, e nomes são livres por ordem de chegada; virar
oráculo de existência é dar um mapa de graça.

A exceção deliberada são os modelos públicos: o sub-admin precisa enxergá-los
para derivar site-images deles, mas só de leitura.
"""

from __future__ import annotations

from .. import auth
from . import owners, store


def is_admin(p: auth.Principal) -> bool:
    return p.kind == "admin"


def quota(p: auth.Principal, recurso: str) -> int | None:
    """Teto do principal para `models` | `site_images` | `builds`. None = sem
    limite (é o caso do admin)."""
    if is_admin(p):
        return None
    return owners.quotas(p.owner).get(recurso)


# --- modelos ---


def can_use_model(p: auth.Principal, name: str) -> bool:
    """Ver o modelo e derivar site-images dele."""
    if not store.model_exists(name):
        return False
    if is_admin(p):
        return True
    return store.model_owner(name) == p.owner or store.model_is_public(name)


def can_manage_model(p: auth.Principal, name: str) -> bool:
    """Alterar camadas, formulário e cadeados — só o dono. Modelo público de
    outro dono é leitura: se o sub-admin pudesse editá-lo, uma trava de imagem
    Oficial cairia por tabela em todas as sedes que usam o mesmo modelo."""
    if not store.model_exists(name):
        return False
    if is_admin(p):
        return True
    return store.model_owner(name) == p.owner


def visible_models(p: auth.Principal) -> list[dict]:
    nomes = store.list_models() if is_admin(p) else _nomes_visiveis(p)
    out = []
    for n in nomes:
        tpl = store.get_model(n) or {}
        dono = store.model_owner(n)
        out.append(
            {
                "name": n,
                "description": tpl.get("description", ""),
                "public": bool(tpl.get("public")),
                "owner": dono,
                "mine": dono == p.owner,
                "layers": len(tpl.get("layers", [])),
                "used_by": len(store.models_using(n)),
                "can_manage": can_manage_model(p, n),
            }
        )
    return out


def _nomes_visiveis(p: auth.Principal) -> list[str]:
    meus = set(store.list_models(owner=p.owner))
    publicos = {n for n in store.list_models() if store.model_is_public(n)}
    return sorted(meus | publicos)


# --- site-images ---


def can_see_site_image(p: auth.Principal, image_id: str) -> bool:
    if not store.site_image_exists(image_id):
        return False
    return is_admin(p) or store.site_image_owner(image_id) == p.owner


can_manage_site_image = can_see_site_image


def visible_site_images(p: auth.Principal, prefix: str = "") -> list[dict]:
    if is_admin(p):
        return store.list_site_images(prefix)
    return store.list_site_images(prefix, owner=p.owner)


# --- criação ---


def check_can_create(p: auth.Principal, recurso: str, nome: str) -> str | None:
    """Devolve a mensagem do erro, ou None se pode criar. Vale para modelo e
    site-image — as duas têm as mesmas duas barreiras: nome reservado e cota."""
    if is_admin(p):
        return None
    if store.name_is_reserved(nome):
        return "esse nome é reservado à administração; escolha outro"
    limite = quota(p, recurso)
    if limite is None:
        return None
    usados = owners.usage(p.owner).get(recurso, 0)
    if usados >= limite:
        return f"cota esgotada ({usados}/{limite}); peça mais à administração"
    return None


def whoami(p: auth.Principal) -> dict:
    """O que a tela precisa para se adaptar sozinha, sem adivinhar pelo 403."""
    if is_admin(p):
        return {
            "kind": "admin",
            "label": p.name or "administração",
            "owner": "admin",
            "can_create_reserved": True,
            "can_publish_models": True,
            "can_manage_invites": True,
            "quotas": {"models": None, "site_images": None, "builds": None},
            "usage": {
                "models": len(store.list_models()),
                "site_images": len(store.list_site_images()),
            },
        }
    rec = owners.get(p.owner) or {}
    return {
        "kind": "subadmin",
        "label": rec.get("label") or "sub-administração",
        "owner": p.owner,
        "can_create_reserved": False,
        "can_publish_models": False,
        "can_manage_invites": False,
        "quotas": owners.quotas(p.owner),
        "usage": owners.usage(p.owner),
    }
