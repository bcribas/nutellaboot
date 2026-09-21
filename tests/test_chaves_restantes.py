"""O que faltava do ciclo de vida das credenciais: convite que se ajusta e se
revoga sem destruir, e a chave de máquina, que era a única sem rotação."""

import time

import pytest

from server.app import fsdb
from server.app.services import audit, invites, owners, store

MAC = "52-54-00-12-34-56"


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def base(data_root, client, ha):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    client.post("/api/v1/models", json={"name": "oficial", "public": True}, headers=ha)
    client.post("/api/v1/models/oficial/layers", json={"file": "b.squashfs", "md5": "0" * 32}, headers=ha)


def _convite(client, ha, **kw):
    return client.post("/api/v1/invites", json={"count": 1, "max_images": 2, **kw}, headers=ha).json()["invites"][0]["code"]


def _cria(client, code, ident):
    return client.post(
        "/api/v1/public/site-images",
        json={"code": code, "id": ident, "fullname": ident, "model": "oficial"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )


def test_revogar_sem_destruir_e_voltar_atras(client, base, ha):
    code = _convite(client, ha, label="Lab A")
    assert _cria(client, code, "laba").status_code == 201
    hs = {"Authorization": f"Bearer {code}"}
    assert client.get("/api/v1/whoami", headers=hs).status_code == 200

    r = client.patch(f"/api/v1/invites/{code}", json={"revoked": True}, headers=ha)
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert client.get("/api/v1/whoami", headers=hs).status_code == 401
    assert _cria(client, code, "labb").status_code in (400, 403)
    # nada ficou órfão: a imagem continua sendo do mesmo dono
    assert store.site_image_owner("laba") == owners.owner_id(code)

    client.patch(f"/api/v1/invites/{code}", json={"revoked": False}, headers=ha)
    assert client.get("/api/v1/whoami", headers=hs).status_code == 200


def test_ajustes_do_convite_e_o_rotulo_acompanha(client, base, ha):
    code = _convite(client, ha, label="Lab A")
    _cria(client, code, "laba")
    vence = int(time.time()) + 3600
    r = client.patch(f"/api/v1/invites/{code}", json={"label": "UFABC - GRUB", "max_images": 5, "expires_at": vence}, headers=ha)
    assert r.status_code == 200, r.text
    assert (r.json()["label"], r.json()["max_images"], r.json()["expires_at"]) == ("UFABC - GRUB", 5, vence)
    lista = client.get("/api/v1/site-images", headers=ha).json()["images"]
    assert next(i for i in lista if i["id"] == "laba")["owner_label"] == "UFABC - GRUB"
    assert client.patch(f"/api/v1/invites/{code}", json={"expires_at": None}, headers=ha).json()["expires_at"] is None

    for ruim in ({"max_images": -1}, {"max_images": "5"}, {"revoked": "sim"}, {"expires_at": "amanhã"},
                 {"model": "naoexiste"}, {}):
        assert client.patch(f"/api/v1/invites/{code}", json=ruim, headers=ha).status_code == 400, ruim
    assert client.patch("/api/v1/invites/NB3-XXXX-YYYY-ZZZZ", json={"label": "x"}, headers=ha).status_code == 404
    # o código é credencial: na auditoria vai a referência, não ele
    assert code not in str(audit.ler())
    assert client.patch(f"/api/v1/invites/{code}", json={"label": "x"}, headers={"Authorization": f"Bearer {code}"}).status_code == 401


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


def _reporta(client, chave):
    return client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers={"X-NB-Machine-Key": chave})


def test_rotacao_da_chave_de_maquina_com_carencia(client, img, ha, data_root):
    antiga = img["machine_key"]
    assert _reporta(client, antiga).status_code == 200
    r = client.post("/api/v1/site-images/testes3/machine-key/rotate", json={}, headers=ha)
    assert r.status_code == 200, r.text
    d = r.json()
    nova = d["machine_key"]
    assert nova.startswith("nb3m_") and nova != antiga and d["online"] == 1 and d["locked"] == 0
    assert d["previous_valid_until"] > time.time() + 11 * 3600
    # a máquina ligada só troca de chave no boot: a antiga segue valendo, a nova já vale
    assert _reporta(client, antiga).status_code == 200
    assert _reporta(client, nova).status_code == 200
    # passada a carência, a antiga morre
    prev = data_root / "site-images" / "testes3" / "machine.key.prev"
    fsdb.write_json(prev, {**fsdb.read_json(prev), "valid_until": time.time() - 1})
    assert _reporta(client, antiga).status_code == 401
    assert client.get("/api/v1/site-images/testes3/credentials", headers=ha).json()["machine_key"] == nova


def test_sem_carencia_com_maquina_travada_so_a_forca(client, img, ha):
    """Rotação seca deixa a máquina travada sem receber o destravar."""
    _reporta(client, img["machine_key"])
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/lock", headers=ha)
    r = client.post("/api/v1/site-images/testes3/machine-key/rotate", json={"grace_hours": 0}, headers=ha)
    assert r.status_code == 409
    r = client.post("/api/v1/site-images/testes3/machine-key/rotate", json={"grace_hours": 0, "force": True}, headers=ha)
    assert r.status_code == 200 and r.json()["previous_valid_until"] is None and r.json()["locked"] == 1
    assert _reporta(client, img["machine_key"]).status_code == 401
    assert client.post("/api/v1/site-images/testes3/machine-key/rotate", json={"grace_hours": 100}, headers=ha).status_code == 400


def test_rotacao_e_do_console_dono(client, img, ha):
    r = client.post("/api/v1/site-images/testes3/machine-key/rotate", json={}, headers={"Authorization": f"Bearer {img['token']}"})
    assert r.status_code == 401
    assert client.post("/api/v1/site-images/naoexiste/machine-key/rotate", json={}, headers=ha).status_code == 404
