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
        data_root / "models" / "generico" / "model.json", {"layers": [], "public": True}
    )
    fsdb.write_json(
        data_root / "models" / "prova" / "model.json", {"layers": [], "public": False}
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
    code = client.post("/api/v1/invites", json={"model": "generico"}, headers=ha).json()[
        "invites"
    ][0]["code"]
    r = client.post(
        "/api/v1/public/site-images",
        json={"code": code, "id": "faculdadex", "fullname": "Faculdade X"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("nb3i_")
    assert body["boot_key"].startswith("nb3b_")
    assert "configureitor_url" in body
    # marca de auto-atendimento e cota de build herdada
    info = store.get_site_image("faculdadex")
    assert info["self_service"] is True
    assert info["build_quota"] == invites.DEFAULT_BUILD_QUOTA


def test_sem_codigo_nao_cria(client, base):
    r = client.post("/api/v1/public/site-images", json={"id": "semcodigo", "model": "generico"})
    assert r.status_code == 403


def test_codigo_invalido_recusado(client, base):
    r = client.post(
        "/api/v1/public/site-images",
        json={"code": "NB3-XXXX-XXXX", "id": "x", "model": "generico"},
    )
    assert r.status_code == 403


def test_codigo_respeita_cota(client, base, ha):
    code = client.post(
        "/api/v1/invites", json={"model": "generico", "max_images": 1}, headers=ha
    ).json()["invites"][0]["code"]
    assert client.post("/api/v1/public/site-images", json={"code": code, "id": "img1"}).status_code == 201
    # segunda com o mesmo código estoura a cota
    r = client.post("/api/v1/public/site-images", json={"code": code, "id": "img2"})
    assert r.status_code == 403
    assert "limite" in r.json()["detail"]


def test_codigo_expirado_recusado(client, base, data_root):
    invites.create(model="generico", expires_at=time.time() - 10)
    code = invites.list_all()[0]["code"]
    r = client.post("/api/v1/public/site-images", json={"code": code, "id": "img"})
    assert r.status_code == 403
    assert "expirado" in r.json()["detail"]


def test_nome_reservado_barrado(client, base, ha):
    code = client.post("/api/v1/invites", json={"model": "generico"}, headers=ha).json()[
        "invites"
    ][0]["code"]
    # nomes começando por dígito são da administração (ano da maratona)
    r = client.post("/api/v1/public/site-images", json={"code": code, "id": "26brbr"})
    assert r.status_code == 403
    assert "reservado" in r.json()["detail"]


def test_template_privado_barrado(client, base, ha):
    # código sem template fixo, pessoa tenta usar o template de prova (privado)
    code = client.post("/api/v1/invites", json={}, headers=ha).json()["invites"][0]["code"]
    r = client.post(
        "/api/v1/public/site-images", json={"code": code, "id": "abusox", "model": "prova"}
    )
    assert r.status_code == 400


def test_public_templates_so_publicos(client, base):
    nomes = [t["name"] for t in client.get("/api/v1/public/models").json()["models"]]
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
        "/api/v1/invites", json={"model": "generico", "build_quota": 2}, headers=ha
    ).json()["invites"][0]["code"]
    img = client.post("/api/v1/public/site-images", json={"code": code, "id": "labz"}).json()
    howner = {"Authorization": f"Bearer {img['token']}"}

    for i in range(2):
        r = client.post(
            "/api/v1/site-images/labz/layerbuilds",
            json={"name": f"camada{i}", "packages": ["htop"]},
            headers=howner,
        )
        assert r.status_code == 201, r.text
        # o build é anexado só a esta imagem
        assert r.json()["attach_to"] == ["labz"]

    # terceira estoura a cota
    r = client.post(
        "/api/v1/site-images/labz/layerbuilds",
        json={"name": "camada3", "packages": ["htop"]},
        headers=howner,
    )
    assert r.status_code == 403
    assert "cota" in r.json()["detail"]


def test_admin_nao_tem_cota_de_build(client, base, ha, data_root):
    code = client.post(
        "/api/v1/invites", json={"model": "generico", "build_quota": 0}, headers=ha
    ).json()["invites"][0]["code"]
    client.post("/api/v1/public/site-images", json={"code": code, "id": "labq"})
    # dono não consegue (cota 0), admin sim
    hbad = {"Authorization": "Bearer nb3i_errado"}
    assert client.post(
        "/api/v1/site-images/labq/layerbuilds", json={"name": "cc", "packages": ["htop"]}, headers=hbad
    ).status_code == 401
    r = client.post(
        "/api/v1/site-images/labq/layerbuilds", json={"name": "cc", "packages": ["htop"]}, headers=ha
    )
    assert r.status_code == 201


def test_so_o_admin_ajusta_a_cota_de_build_da_imagem(client, base, ha):
    """O campo existia no armazenamento e não no modelo do PATCH: o Pydantic
    descartava em silêncio, e não havia caminho nenhum de API para aumentar a
    cota de uma imagem já criada. Ajustar a própria cota, obviamente, não pode
    ser do dono — cota que o interessado aumenta não é cota."""
    code = client.post(
        "/api/v1/invites", json={"model": "generico", "build_quota": 0}, headers=ha
    ).json()["invites"][0]["code"]
    img = client.post("/api/v1/public/site-images", json={"code": code, "id": "labcota"}).json()
    hdono = {"Authorization": f"Bearer {img['token']}"}

    assert client.patch(
        "/api/v1/site-images/labcota", json={"build_quota": 9}, headers=hdono
    ).status_code == 401  # token de imagem nem entra no console

    r = client.patch("/api/v1/site-images/labcota", json={"build_quota": 2}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["build_quota"] == 2

    # e a cota nova vale de verdade
    r = client.post(
        "/api/v1/site-images/labcota/layerbuilds",
        json={"name": "cc", "packages": ["htop"]},
        headers=hdono,
    )
    assert r.status_code == 201, r.text


def test_subadmin_dono_nao_aumenta_a_propria_cota(client, base, ha):
    code = client.post(
        "/api/v1/invites", json={"model": "generico", "build_quota": 0}, headers=ha
    ).json()["invites"][0]["code"]
    client.post("/api/v1/public/site-images", json={"code": code, "id": "labsub"})
    r = client.patch(
        "/api/v1/site-images/labsub",
        json={"build_quota": 99},
        headers={"Authorization": f"Bearer {code}"},
    )
    assert r.status_code == 403
    assert "cota" in r.json()["detail"]


def test_pacote_invalido_no_build_por_imagem(client, base, ha):
    code = client.post("/api/v1/invites", json={"model": "generico"}, headers=ha).json()[
        "invites"
    ][0]["code"]
    img = client.post("/api/v1/public/site-images", json={"code": code, "id": "labp"}).json()
    r = client.post(
        "/api/v1/site-images/labp/layerbuilds",
        json={"name": "cc", "packages": ["htop; rm -rf /"]},
        headers={"Authorization": f"Bearer {img['token']}"},
    )
    assert r.status_code == 400


# --- perfil da imagem: Oficial (travada) vs Livre (tudo liberado) ---


@pytest.fixture
def base_com_schema(data_root, admin_key):
    """Template público com um campo travado (MINRAM), como o da maratona."""
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(
        data_root / "models" / "generico" / "model.json", {"layers": [], "public": True}
    )
    fsdb.write_json(data_root / "models" / "generico" / "schema.json", build_default_schema())
    return admin_key


def _cria_por_convite(client, ha, image_id, **invite_kwargs):
    code = client.post(
        "/api/v1/invites", json={"model": "generico", **invite_kwargs}, headers=ha
    ).json()["invites"][0]["code"]
    return client.post("/api/v1/public/site-images", json={"code": code, "id": image_id}).json()


def test_autoatendimento_nasce_livre_e_dono_edita_campo_travado(client, base_com_schema, ha):
    """O ponto central: quem cria a própria imagem manda nela inteira —
    inclusive nos campos que são obrigatórios nas imagens oficiais."""
    img = _cria_por_convite(client, ha, "labrivre")
    assert store.get_site_image("labrivre")["unlocked"] is True

    howner = {"Authorization": f"Bearer {img['token']}"}
    # MINRAM, DISABLE_FIREWALL, ALLOWUSBMOUNT e DEFAULTBROWSERURL são locked no
    # schema padrão — na imagem Livre o dono muda todos
    r = client.put(
        "/api/v1/site-images/labrivre/config",
        json={
            "values": {
                "MINRAM": "4096",
                "DISABLE_FIREWALL": True,
                "ALLOWUSBMOUNT": True,
                "DEFAULTBROWSERURL": "https://meujuiz.exemplo",
            }
        },
        headers=howner,
    )
    assert r.status_code == 200, r.text
    vals = r.json()["values"]
    assert vals["MINRAM"] == "4096"
    assert vals["DISABLE_FIREWALL"] is True
    assert vals["ALLOWUSBMOUNT"] is True
    assert vals["DEFAULTBROWSERURL"] == "https://meujuiz.exemplo"
    # e o configureitor libera a edição na tela
    assert client.get("/api/v1/site-images/labrivre/config", headers=howner).json()["can_edit_locked"] is True


def test_convite_oficial_gera_imagem_travada(client, base_com_schema, ha):
    img = _cria_por_convite(client, ha, "laboficial", unlocked=False)
    assert store.get_site_image("laboficial")["unlocked"] is False

    howner = {"Authorization": f"Bearer {img['token']}"}
    r = client.put(
        "/api/v1/site-images/laboficial/config", json={"values": {"MINRAM": "4096"}}, headers=howner
    )
    assert r.status_code == 400
    assert "bloqueado" in r.json()["detail"]
    assert client.get("/api/v1/site-images/laboficial/config", headers=howner).json()["can_edit_locked"] is False

    # o admin continua podendo
    assert client.put(
        "/api/v1/site-images/laboficial/config", json={"values": {"MINRAM": "4096"}}, headers=ha
    ).status_code == 200


def test_admin_alterna_perfil_da_imagem(client, base_com_schema, ha):
    """Voltar uma imagem para 'tudo liberado' (e vice-versa) com um clique."""
    r = client.post(
        "/api/v1/site-images",
        json={"id": "oficialx", "fullname": "Oficial X", "model": "generico"},
        headers=ha,
    )
    token = r.json()["token"]
    howner = {"Authorization": f"Bearer {token}"}
    # nasce Oficial: dono não mexe no firewall
    assert client.put(
        "/api/v1/site-images/oficialx/config", json={"values": {"DISABLE_FIREWALL": True}}, headers=howner
    ).status_code == 400

    # admin libera tudo
    assert client.patch("/api/v1/site-images/oficialx", json={"unlocked": True}, headers=ha).status_code == 200
    assert client.put(
        "/api/v1/site-images/oficialx/config", json={"values": {"DISABLE_FIREWALL": True}}, headers=howner
    ).status_code == 200

    # e consegue travar de volta
    client.patch("/api/v1/site-images/oficialx", json={"unlocked": False}, headers=ha)
    assert client.put(
        "/api/v1/site-images/oficialx/config", json={"values": {"MINRAM": "0"}}, headers=howner
    ).status_code == 400


def test_imagem_oficial_da_maratona_continua_travada(client, base_com_schema, ha):
    """Sedes criadas pelo admin (namespace reservado) não podem mexer nos
    campos obrigatórios — é o comportamento que a maratona depende."""
    r = client.post(
        "/api/v1/site-images",
        json={"id": "26brbr", "fullname": "Finals", "model": "generico"},
        headers=ha,
    )
    assert r.json()["namespace"] == "contest"
    howner = {"Authorization": f"Bearer {r.json()['token']}"}
    for campo, valor in (
        ("MINRAM", "0"),
        ("DISABLE_FIREWALL", True),
        ("ALLOWUSBMOUNT", True),
        ("DEFAULTBROWSERURL", "https://qualquer"),
    ):
        resp = client.put(
            "/api/v1/site-images/26brbr/config", json={"values": {campo: valor}}, headers=howner
        )
        assert resp.status_code == 400, f"{campo} deveria estar travado"


def test_convite_mostra_o_perfil_na_listagem(client, base_com_schema, ha):
    client.post("/api/v1/invites", json={"unlocked": False, "note": "sub-sede"}, headers=ha)
    inv = client.get("/api/v1/invites", headers=ha).json()["invites"][0]
    assert inv["unlocked"] is False
