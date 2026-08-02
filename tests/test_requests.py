"""Fila de pedidos (para quem não tem código de convite)."""

import pytest

from server.app import fsdb
from server.app.services import ratelimit, store


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def base(data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "generico" / "model.json", {"layers": [], "public": True})
    return admin_key


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def test_lista_pedidos_exige_admin(client, base):
    assert client.get("/api/v1/requests").status_code == 401


def test_aprovar_criando_imagem_direto(client, base, ha):
    rid = client.post(
        "/api/v1/public/requests", json={"wanted_name": "lab novo", "contact": "a@b.c"}
    ).json()["id"]
    r = client.post(
        f"/api/v1/requests/{rid}/approve",
        json={"id": "labaprovado", "model": "generico", "fullname": "Lab Aprovado"},
        headers=ha,
    )
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert created["id"] == "labaprovado"
    assert store.site_image_exists("labaprovado")
    # a imagem aprovada nasce marcada como auto-atendimento
    assert store.get_site_image("labaprovado")["self_service"] is True


def test_aprovar_direto_sem_template_valido(client, base, ha):
    rid = client.post(
        "/api/v1/public/requests", json={"wanted_name": "x", "contact": "a@b.c"}
    ).json()["id"]
    r = client.post(f"/api/v1/requests/{rid}/approve", json={"id": "semtpl"}, headers=ha)
    assert r.status_code == 400


def test_recusar_pedido(client, base, ha):
    rid = client.post(
        "/api/v1/public/requests", json={"wanted_name": "x", "contact": "a@b.c"}
    ).json()["id"]
    r = client.post(f"/api/v1/requests/{rid}/reject", json={"reason": "fora do escopo"}, headers=ha)
    assert r.status_code == 200
    pend = [p for p in client.get("/api/v1/requests", headers=ha).json()["requests"] if p["id"] == rid]
    assert pend[0]["status"] == "rejected"
    assert pend[0]["reason"] == "fora do escopo"


def test_aprovar_pedido_inexistente(client, base, ha):
    assert client.post("/api/v1/requests/naoexiste/approve", json={}, headers=ha).status_code == 404


def test_campos_do_pedido_sao_truncados(client, base, data_root):
    from server.app.services import requests as req_svc

    req_svc.submit("n" * 500, "c" * 500, "z" * 5000)
    p = req_svc.list_all()[0]
    assert len(p["wanted_name"]) == 64
    assert len(p["contact"]) == 200
    assert len(p["note"]) == 1000
