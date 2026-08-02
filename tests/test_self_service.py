"""Auto-atendimento: convites, criação por código, pedidos, quota de camada.

Cobre a contenção de abuso: sem código não cria, código tem cota, nomes
reservados (dígito) barrados, template não-público barrado, e a quota de
build de camada por imagem.
"""

import time

import pytest

from server.app import fsdb
from server.app.services import invites, ratelimit, store


@pytest.fixture(autouse=True)
def _reset_rate():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def base(data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    # template público (auto-atendimento) e um privado (prova)
    fsdb.write_json(
        data_root / "templates" / "generico" / "template.json", {"layers": [], "public": True}
    )
    fsdb.write_json(
        data_root / "templates" / "prova" / "template.json", {"layers": [], "public": False}
    )
    return admin_key


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


# --- convites (admin) ---


def test_admin_gera_e_lista_convites(client, base, ha):
    r = client.post("/api/v1/invites", json={"count": 3, "max_images": 2}, headers=ha)
    assert r.status_code == 201
    codigos = [i["code"] for i in r.json()["invites"]]
    assert len(codigos) == 3
    assert all(c.startswith("NB3-") for c in codigos)

    lst = client.get("/api/v1/invites", headers=ha).json()["invites"]
    assert len(lst) == 3
    assert lst[0]["remaining"] == 2


def test_convite_exige_admin(client, base):
    assert client.post("/api/v1/invites", json={}).status_code == 401


# --- criação por auto-atendimento ---


def test_cria_imagem_com_codigo(client, base, ha):
    code = client.post("/api/v1/invites", json={"template": "generico"}, headers=ha).json()[
        "invites"
    ][0]["code"]
    r = client.post(
        "/api/v1/public/images",
        json={"code": code, "id": "faculdadex", "fullname": "Faculdade X"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("nb3i_")
    assert body["boot_key"].startswith("nb3b_")
    assert "configureitor_url" in body
    # marca de auto-atendimento e cota de build herdada
    info = store.get_image("faculdadex")
    assert info["self_service"] is True
    assert info["build_quota"] == invites.DEFAULT_BUILD_QUOTA


def test_sem_codigo_nao_cria(client, base):
    r = client.post("/api/v1/public/images", json={"id": "semcodigo", "template": "generico"})
    assert r.status_code == 403


def test_codigo_invalido_recusado(client, base):
    r = client.post(
        "/api/v1/public/images",
        json={"code": "NB3-XXXX-XXXX", "id": "x", "template": "generico"},
    )
    assert r.status_code == 403


def test_codigo_respeita_cota(client, base, ha):
    code = client.post(
        "/api/v1/invites", json={"template": "generico", "max_images": 1}, headers=ha
    ).json()["invites"][0]["code"]
    assert client.post("/api/v1/public/images", json={"code": code, "id": "img1"}).status_code == 201
    # segunda com o mesmo código estoura a cota
    r = client.post("/api/v1/public/images", json={"code": code, "id": "img2"})
    assert r.status_code == 403
    assert "limite" in r.json()["detail"]


def test_codigo_expirado_recusado(client, base, data_root):
    invites.create(template="generico", expires_at=time.time() - 10)
    code = invites.list_all()[0]["code"]
    r = client.post("/api/v1/public/images", json={"code": code, "id": "img"})
    assert r.status_code == 403
    assert "expirado" in r.json()["detail"]


def test_nome_reservado_barrado(client, base, ha):
    code = client.post("/api/v1/invites", json={"template": "generico"}, headers=ha).json()[
        "invites"
    ][0]["code"]
    # nomes começando por dígito são da administração (ano da maratona)
    r = client.post("/api/v1/public/images", json={"code": code, "id": "26brbr"})
    assert r.status_code == 403
    assert "reservado" in r.json()["detail"]


def test_template_privado_barrado(client, base, ha):
    # código sem template fixo, pessoa tenta usar o template de prova (privado)
    code = client.post("/api/v1/invites", json={}, headers=ha).json()["invites"][0]["code"]
    r = client.post(
        "/api/v1/public/images", json={"code": code, "id": "abusox", "template": "prova"}
    )
    assert r.status_code == 400


def test_public_templates_so_publicos(client, base):
    nomes = [t["name"] for t in client.get("/api/v1/public/templates").json()["templates"]]
    assert "generico" in nomes
    assert "prova" not in nomes


# --- fila de pedidos ---


def test_pedido_e_aprovacao(client, base, ha):
    r = client.post(
        "/api/v1/public/requests",
        json={"wanted_name": "Escola Y", "contact": "y@example.org", "note": "quero uma imagem"},
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    pend = client.get("/api/v1/requests", headers=ha).json()["requests"]
    assert any(p["id"] == rid for p in pend)

    # admin aprova emitindo um código
    r = client.post(
        f"/api/v1/requests/{rid}/approve", json={"action": "issue_code"}, headers=ha
    )
    assert r.status_code == 200
    assert r.json()["issued"]["code"].startswith("NB3-")

    # o pedido some da lista de pendentes
    apos = client.get("/api/v1/requests", headers=ha).json()["requests"]
    assert [p for p in apos if p["id"] == rid][0]["status"] == "approved"


def test_pedido_exige_nome_e_contato(client, base):
    assert client.post("/api/v1/public/requests", json={"wanted_name": "x"}).status_code == 400


# --- quota de build de camada ---


def test_dono_da_imagem_faz_build_dentro_da_cota(client, base, ha, data_root):
    code = client.post(
        "/api/v1/invites", json={"template": "generico", "build_quota": 2}, headers=ha
    ).json()["invites"][0]["code"]
    img = client.post("/api/v1/public/images", json={"code": code, "id": "labz"}).json()
    howner = {"Authorization": f"Bearer {img['token']}"}

    for i in range(2):
        r = client.post(
            "/api/v1/images/labz/layerbuilds",
            json={"name": f"camada{i}", "packages": ["htop"]},
            headers=howner,
        )
        assert r.status_code == 201, r.text
        # o build é anexado só a esta imagem
        assert r.json()["attach_to"] == ["labz"]

    # terceira estoura a cota
    r = client.post(
        "/api/v1/images/labz/layerbuilds",
        json={"name": "camada3", "packages": ["htop"]},
        headers=howner,
    )
    assert r.status_code == 403
    assert "cota" in r.json()["detail"]


def test_admin_nao_tem_cota_de_build(client, base, ha, data_root):
    code = client.post(
        "/api/v1/invites", json={"template": "generico", "build_quota": 0}, headers=ha
    ).json()["invites"][0]["code"]
    client.post("/api/v1/public/images", json={"code": code, "id": "labq"})
    # dono não consegue (cota 0), admin sim
    hbad = {"Authorization": "Bearer nb3i_errado"}
    assert client.post(
        "/api/v1/images/labq/layerbuilds", json={"name": "cc", "packages": ["htop"]}, headers=hbad
    ).status_code == 401
    r = client.post(
        "/api/v1/images/labq/layerbuilds", json={"name": "cc", "packages": ["htop"]}, headers=ha
    )
    assert r.status_code == 201


def test_pacote_invalido_no_build_por_imagem(client, base, ha):
    code = client.post("/api/v1/invites", json={"template": "generico"}, headers=ha).json()[
        "invites"
    ][0]["code"]
    img = client.post("/api/v1/public/images", json={"code": code, "id": "labp"}).json()
    r = client.post(
        "/api/v1/images/labp/layerbuilds",
        json={"name": "cc", "packages": ["htop; rm -rf /"]},
        headers={"Authorization": f"Bearer {img['token']}"},
    )
    assert r.status_code == 400
