import pytest
from fastapi import HTTPException

from server.app import auth, fsdb


def test_identify_admin(admin_key):
    p = auth.identify(admin_key)
    assert p and p.kind == "admin"
    assert p.can_see_image("qualquer")


def test_identify_rejects_unknown(data_root):
    assert auth.identify("nb3a_" + "0" * 32) is None
    assert auth.identify(None) is None
    assert auth.identify("") is None


def test_identify_image_token(image_testes3):
    p = auth.identify(image_testes3["token"], image_id="testes3")
    assert p and p.kind == "image" and p.name == "testes3"
    assert p.can_see_image("testes3")
    assert not p.can_see_image("outra")
    # token de imagem não vale sem contexto de imagem
    assert auth.identify(image_testes3["token"]) is None


def test_identify_machine_key(image_testes3):
    p = auth.identify_machine(image_testes3["machine_key"], "testes3")
    assert p and p.kind == "machine"
    assert auth.identify_machine("nb3m_errada", "testes3") is None


def test_service_scopes_and_globs(data_root):
    key = auth.new_key("nb3s")
    fsdb.write_json(
        data_root / "keys" / "services.json",
        {"moj": {"sha256": auth.key_hash(key), "scopes": ["machines:read"], "images": ["26*"]}},
    )
    p = auth.identify(key)
    assert p and p.kind == "service" and p.name == "moj"
    assert "machines:read" in p.scopes
    assert p.can_see_image("26mineira")
    assert not p.can_see_image("25brbr")


@pytest.mark.anyio
async def test_require_admin_rejects(data_root):
    with pytest.raises(HTTPException) as exc:
        await auth.require_admin(authorization="Bearer nb3a_falsa")
    assert exc.value.status_code == 401


@pytest.mark.anyio
async def test_require_image_access(image_testes3, admin_key):
    dep = auth.require_image_access()
    p = await dep(image="testes3", authorization=f"Bearer {image_testes3['token']}", x_nb_machine_key=None)
    assert p.kind == "image"
    p = await dep(image="testes3", authorization=f"Bearer {admin_key}", x_nb_machine_key=None)
    assert p.kind == "admin"
    with pytest.raises(HTTPException) as exc:
        await dep(image="inexistente", authorization=f"Bearer {admin_key}", x_nb_machine_key=None)
    assert exc.value.status_code == 404


@pytest.fixture
def anyio_backend():
    return "asyncio"
