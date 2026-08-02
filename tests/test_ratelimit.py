"""Limite de taxa e templates públicos."""

import pytest

from server.app import fsdb
from server.app.services import ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_token_bucket_bloqueia_rajada():
    # burst 3: as 3 primeiras passam, a 4ª no mesmo instante é barrada
    now = 1000.0
    ok = [ratelimit.allow("k", rate=1, burst=3, now=now) for _ in range(4)]
    assert ok == [True, True, True, False]


def test_token_bucket_recupera_com_o_tempo():
    ratelimit.allow("k", rate=1, burst=1, now=0)  # gasta o único token
    assert ratelimit.allow("k", rate=1, burst=1, now=0.5) is False
    assert ratelimit.allow("k", rate=1, burst=1, now=1.5) is True  # 1s depois, +1 token


def test_chaves_independentes():
    assert ratelimit.allow("a", rate=1, burst=1, now=0) is True
    assert ratelimit.allow("b", rate=1, burst=1, now=0) is True
    assert ratelimit.allow("a", rate=1, burst=1, now=0) is False


def test_client_ip_respeita_xff():
    class Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("C", (), {"host": "127.0.0.1"})()

    assert ratelimit.client_ip(Req()) == "203.0.113.7"


def test_rota_publica_barra_rajada(client, admin_key, data_root):
    """A rota de pedido é rate-limited: uma rajada acaba levando 429."""
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    codigos = [
        client.post(
            "/api/v1/public/requests",
            json={"wanted_name": f"e{i}", "contact": "a@b.c"},
        ).status_code
        for i in range(10)
    ]
    assert 429 in codigos, "esperava algum 429 na rajada"


def test_admin_marca_template_publico(client, admin_key, data_root):
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    h = {"Authorization": f"Bearer {admin_key}"}
    # nasce privado
    assert client.get("/api/v1/public/templates").json()["templates"] == []
    r = client.patch("/api/v1/templates/t", json={"public": True, "description": "genérico"}, headers=h)
    assert r.status_code == 200 and r.json()["public"] is True
    nomes = [t["name"] for t in client.get("/api/v1/public/templates").json()["templates"]]
    assert nomes == ["t"]
