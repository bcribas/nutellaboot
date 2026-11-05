"""Roster, vínculo usuário↔máquina, dados da tela de bloqueio e SSE."""


import base64

import pytest

from server.app import fsdb

MAC = "52-54-00-12-34-56"

ROSTER = [
    {
        "user_id": "team-001",
        "name": "Os Batatinhas",
        "display_name": "UnB — Os Batatinhas",
        "organization": {"id": "unb", "name": "Universidade de Brasília"},
        "country": "BRA",
        "seat": "012",
    },
    {"user_id": "team-002", "name": "Segundos", "organization": {"id": "usp"}, "country": "BRA"},
]


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


@pytest.fixture
def hi(img):
    return {"Authorization": f"Bearer {img['token']}"}


@pytest.fixture
def hm(img):
    return {"X-NB-Machine-Key": img["machine_key"]}


def test_roster_upload_and_read(client, img, hi):
    r = client.put("/api/v1/site-images/testes3/roster", json={"roster": ROSTER}, headers=hi)
    assert r.status_code == 200
    assert r.json()["entries"] == 2
    assert len(client.get("/api/v1/site-images/testes3/roster", headers=hi).json()["roster"]) == 2


def test_roster_requires_user_id(client, img, hi):
    r = client.put("/api/v1/site-images/testes3/roster", json={"roster": [{"name": "x"}]}, headers=hi)
    assert r.status_code == 400


def test_logo_upload_and_serve(client, img, hi):
    client.put("/api/v1/site-images/testes3/roster", json={"roster": ROSTER}, headers=hi)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    r = client.put(
        "/api/v1/site-images/testes3/roster/logos/unb",
        files={"file": ("unb.svg", svg, "image/svg+xml")},
        headers=hi,
    )
    assert r.status_code == 200 and r.json()["format"] == "svg"

    r = client.get("/boot/v3/testes3/roster/logos/unb")
    assert r.status_code == 200
    assert r.content == svg


def test_logo_rejects_arbitrary_file(client, img, hi):
    r = client.put(
        "/api/v1/site-images/testes3/roster/logos/unb",
        files={"file": ("x.svg", b"#!/bin/sh\nrm -rf /", "image/svg+xml")},
        headers=hi,
    )
    assert r.status_code == 400


def test_logo_path_traversal_blocked(client, img, hi):
    """O CGI de registro do nb2 interpolava parâmetros do usuário direto em
    `rm` e `ln -s`. Aqui identificadores com caminho são recusados."""
    from fastapi import HTTPException

    from server.app.routers.roster import logo_response

    r = client.put(
        "/api/v1/site-images/testes3/roster/logos/..%2F..%2Fetc",
        files={"file": ("x.png", b"\x89PNG1234", "image/png")},
        headers=hi,
    )
    assert r.status_code >= 400

    for maldoso in ("../../etc/passwd", "a/b", ".."):
        with pytest.raises(HTTPException):
            logo_response("testes3", maldoso)


def test_binding_and_lockinfo(client, img, hi, hm):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.put("/api/v1/site-images/testes3/roster", json={"roster": ROSTER}, headers=hi)
    svg = b"<svg/>"
    client.put(
        "/api/v1/site-images/testes3/roster/logos/unb",
        files={"file": ("unb.svg", svg, "image/svg+xml")},
        headers=hi,
    )

    r = client.put(
        f"/api/v1/site-images/testes3/machines/{MAC}/binding",
        json={"user_id": "team-001"},
        headers=hi,
    )
    assert r.status_code == 200

    # é isto que a tela de bloqueio consome (equivalente ao gradiente8 do nb2)
    info = client.get(f"/boot/v3/testes3/lockinfo/{MAC}").json()
    assert info["team"]["display_name"] == "UnB — Os Batatinhas"
    assert info["organization"]["name"] == "Universidade de Brasília"
    # embutido: o tema é file://, um caminho relativo nunca chegaria ao servidor
    assert info["organization"]["logo_url"] == (
        "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    )
    assert info["country"] == "BRA"
    assert info["seat"] == "012"

    assert client.get("/api/v1/site-images/testes3/bindings", headers=hi).json()["bindings"][0]["mac"] == MAC

    assert client.delete(f"/api/v1/site-images/testes3/machines/{MAC}/binding", headers=hi).status_code == 204
    assert client.get(f"/boot/v3/testes3/lockinfo/{MAC}").json()["team"]["name"] == ""


def test_logo_acima_do_teto_nao_vai_embutido(client, img, hi, hm, monkeypatch):
    """O lockinfo inteiro vai na query string do tema: logo acima do teto volta
    como caminho (que a tela não mostra), e o lockinfo continua pequeno."""
    from server.app.routers import roster

    monkeypatch.setattr(roster, "LOGO_EMBUTIDO_MAX", 16)
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.put("/api/v1/site-images/testes3/roster", json={"roster": ROSTER}, headers=hi)
    client.put(
        "/api/v1/site-images/testes3/roster/logos/unb",
        files={"file": ("unb.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml")},
        headers=hi,
    )
    client.put(
        f"/api/v1/site-images/testes3/machines/{MAC}/binding",
        json={"user_id": "team-001"},
        headers=hi,
    )
    info = client.get(f"/boot/v3/testes3/lockinfo/{MAC}").json()
    assert info["organization"]["logo_url"] == "/boot/v3/testes3/roster/logos/unb"


def test_logo_embutido_recusa_org_com_caminho(img):
    """O id da organização vem do roster: com barra ou `..`, o lockinfo leria
    um .svg ou .png fora da pasta dos logos."""
    from server.app.routers.roster import _logo_url

    for maldoso in ("../../etc/passwd", "a/b", "..", ""):
        assert _logo_url("testes3", maldoso) == ""


def test_binding_rejects_unknown_user(client, img, hi, hm):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.put("/api/v1/site-images/testes3/roster", json={"roster": ROSTER}, headers=hi)
    r = client.put(
        f"/api/v1/site-images/testes3/machines/{MAC}/binding",
        json={"user_id": "nao-existe"},
        headers=hi,
    )
    assert r.status_code == 404


def test_binding_requires_auth(client, img, hm):
    """No nb2 o registro time↔máquina era um CGI sem autenticação nenhuma."""
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    r = client.put(f"/api/v1/site-images/testes3/machines/{MAC}/binding", json={"name": "x"})
    assert r.status_code == 401


def test_lockinfo_has_no_secrets(client, img, hi, hm):
    """A tela de bloqueio é servida sem autenticação: só pode conter o que
    já seria visível na sala."""
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    texto = client.get(f"/boot/v3/testes3/lockinfo/{MAC}").text
    assert "nb3i_" not in texto and "nb3m_" not in texto and "HASH" not in texto


def test_sse_requires_valid_token(client, img):
    with client.stream("GET", "/api/v1/site-images/testes3/events?tk=errado") as r:
        assert r.status_code == 401


@pytest.mark.parametrize("escopos", [["labs:read"], ["commands:write", "webhooks:write"]])
def test_sse_recusa_chave_de_servico_sem_escopo_de_leitura(client, img, escopos):
    """O fluxo leva MAC, status e comando de cada máquina. A chave do telão
    (`labs:read`, só agregados) entrava nele com escopo nenhum. O lado que abre
    (`machines:read` ou `roster:read`) está em `test_live_server.py`: o
    TestClient não termina um fluxo que não termina."""
    from server.app.services import keys

    chave = keys.servico_criar("telao", escopos, [], "admin" if escopos == ["labs:read"] else "")["key"]
    with client.stream("GET", f"/api/v1/site-images/testes3/events?tk={chave}") as r:
        assert r.status_code == 403
        r.read()
        assert r.json()["code"] == "insufficient_scope"
