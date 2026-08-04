"""Travas por campo (no template) e wallpaper travado (na imagem)."""

import pytest

from server.app import fsdb
from server.app.services import config as cfg
from server.app.services import store
from server.app.services.default_schema import build_default_schema

PNG = b"\x89PNG\r\n\x1a\n" + b"conteudo"


@pytest.fixture
def base(data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": [], "public": True})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    return admin_key


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def _cria(client, ha, image_id, **kw):
    return client.post(
        "/api/v1/site-images",
        json={"id": image_id, "fullname": image_id, "model": "t", **kw},
        headers=ha,
    ).json()


# --- travas por campo ---


def test_lista_campos_com_cadeado(client, base, ha):
    r = client.get("/api/v1/models/t/schema", headers=ha)
    assert r.status_code == 200
    campos = {f["key"]: f for f in r.json()["fields"]}
    # o padrão da maratona já trava estes
    assert campos["MINRAM"]["locked"] is True
    assert campos["DISABLE_FIREWALL"]["locked"] is True
    assert campos["TIMEZONE"]["locked"] is False
    # rótulo trilíngue vai junto, para a tela mostrar
    assert set(campos["MINRAM"]["label"]) == {"pt", "en", "es"}


def test_destravar_campo_libera_o_dono(client, base, ha):
    """O caso: 'nesta temporada as sedes podem escolher o fuso e a RAM'."""
    img = _cria(client, ha, "sede1")
    howner = {"Authorization": f"Bearer {img['token']}"}
    assert client.put(
        "/api/v1/site-images/sede1/config", json={"values": {"MINRAM": "4096"}}, headers=howner
    ).status_code == 400

    r = client.put(
        "/api/v1/models/t/schema/locks", json={"locks": {"MINRAM": False}}, headers=ha
    )
    assert r.status_code == 200
    assert {f["key"]: f["locked"] for f in r.json()["fields"]}["MINRAM"] is False

    assert client.put(
        "/api/v1/site-images/sede1/config", json={"values": {"MINRAM": "4096"}}, headers=howner
    ).status_code == 200


def test_travar_campo_novo_bloqueia_o_dono(client, base, ha):
    img = _cria(client, ha, "sede2")
    howner = {"Authorization": f"Bearer {img['token']}"}
    assert client.put(
        "/api/v1/site-images/sede2/config", json={"values": {"TIMEZONE": "America/Santiago"}}, headers=howner
    ).status_code == 200

    client.put("/api/v1/models/t/schema/locks", json={"locks": {"TIMEZONE": True}}, headers=ha)
    assert client.put(
        "/api/v1/site-images/sede2/config", json={"values": {"TIMEZONE": "America/Bogota"}}, headers=howner
    ).status_code == 400
    # e o valor efetivo volta ao padrão do template
    assert cfg.effective_values("sede2")["TIMEZONE"] == "America/Sao_Paulo"


def test_locks_preserva_o_resto_do_schema(client, base, ha):
    antes = store.get_schema("t")
    client.put("/api/v1/models/t/schema/locks", json={"locks": {"MINRAM": False}}, headers=ha)
    depois = store.get_schema("t")
    assert len(antes["fields"]) == len(depois["fields"])
    for a, d in zip(antes["fields"], depois["fields"]):
        assert a["key"] == d["key"] and a.get("type") == d.get("type")
        assert a.get("options") == d.get("options")
        assert a.get("label") == d.get("label")


def test_campo_inexistente_recusado(client, base, ha):
    r = client.put(
        "/api/v1/models/t/schema/locks", json={"locks": {"NAO_EXISTE": True}}, headers=ha
    )
    assert r.status_code == 400
    assert "NAO_EXISTE" in r.json()["detail"]


def test_locks_exige_admin(client, base, image_testes3):
    r = client.put(
        "/api/v1/models/t/schema/locks",
        json={"locks": {"MINRAM": False}},
        headers={"Authorization": f"Bearer {image_testes3['token']}"},
    )
    assert r.status_code == 401


def test_imagem_livre_ignora_as_travas(client, base, ha):
    """Perfil Livre continua acima das travas do template."""
    img = _cria(client, ha, "livre1", unlocked=True)
    howner = {"Authorization": f"Bearer {img['token']}"}
    assert client.put(
        "/api/v1/site-images/livre1/config", json={"values": {"MINRAM": "0"}}, headers=howner
    ).status_code == 200


# --- wallpaper travado ---


def test_wallpaper_travado_recusa_o_dono_e_aceita_o_admin(client, base, ha):
    img = _cria(client, ha, "comfundo", wallpaper_locked=True)
    howner = {"Authorization": f"Bearer {img['token']}"}

    r = client.put(
        "/api/v1/site-images/comfundo/wallpaper",
        files={"file": ("f.png", PNG, "image/png")},
        headers=howner,
    )
    assert r.status_code == 400
    assert "organização" in r.json()["detail"]

    # admin troca normalmente
    assert client.put(
        "/api/v1/site-images/comfundo/wallpaper",
        files={"file": ("f.png", PNG, "image/png")},
        headers=ha,
    ).status_code == 200
    # e o dono também não apaga
    assert client.delete("/api/v1/site-images/comfundo/wallpaper", headers=howner).status_code == 400


def test_wallpaper_livre_por_padrao(client, base, ha):
    img = _cria(client, ha, "semtrava")
    howner = {"Authorization": f"Bearer {img['token']}"}
    assert client.put(
        "/api/v1/site-images/semtrava/wallpaper",
        files={"file": ("f.png", PNG, "image/png")},
        headers=howner,
    ).status_code == 200


def test_config_informa_se_pode_trocar_wallpaper(client, base, ha):
    img = _cria(client, ha, "info1", wallpaper_locked=True)
    howner = {"Authorization": f"Bearer {img['token']}"}
    assert client.get("/api/v1/site-images/info1/config", headers=howner).json()["can_edit_wallpaper"] is False
    assert client.get("/api/v1/site-images/info1/config", headers=ha).json()["can_edit_wallpaper"] is True


def test_admin_pode_travar_depois(client, base, ha):
    img = _cria(client, ha, "info2")
    howner = {"Authorization": f"Bearer {img['token']}"}
    client.patch("/api/v1/site-images/info2", json={"wallpaper_locked": True}, headers=ha)
    assert client.put(
        "/api/v1/site-images/info2/wallpaper",
        files={"file": ("f.png", PNG, "image/png")},
        headers=howner,
    ).status_code == 400


def test_convite_pode_fixar_wallpaper_travado(client, base, ha):
    code = client.post(
        "/api/v1/invites", json={"model": "t", "wallpaper_locked": True}, headers=ha
    ).json()["invites"][0]["code"]
    img = client.post("/api/v1/public/site-images", json={"code": code, "id": "labfixo"}).json()
    assert store.get_site_image("labfixo")["wallpaper_locked"] is True
    assert client.put(
        "/api/v1/site-images/labfixo/wallpaper",
        files={"file": ("f.png", PNG, "image/png")},
        headers={"Authorization": f"Bearer {img['token']}"},
    ).status_code == 400


def test_a_rota_do_esquema_devolve_as_opcoes(client, ha, base):
    """Sem `options`, o editor do console montava uma lista VAZIA para todo
    campo `select`: escolher o fuso ou o idioma padrão ficava impossível pela
    tela, e nada dizia por quê."""
    r = client.get("/api/v1/models/t/schema", headers=ha)
    assert r.status_code == 200, r.text
    campos = {f["key"]: f for f in r.json()["fields"]}

    tz = campos["TIMEZONE"]
    assert tz["type"] == "select"
    assert len(tz["options"]) > 100, "as opções de fuso não vieram"
    assert {"value", "label"} <= set(tz["options"][0])
    # o editor usa os dois juntos: a lista para escolher e o default para marcar
    assert tz["default"]

    assert len(campos["LANGUAGE"]["options"]) == 3
    # campo que não é select não inventa opções
    assert campos["FORCE_CLEAN_HOME_ON_BOOT"].get("options") in (None, [])
