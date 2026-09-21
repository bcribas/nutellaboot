"""A chave de serviço se enxergando (achado 9 do relatório do MOJ).

Ela levava 401 em `/whoami` e na lista de imagens e 403 em `GET
/site-images/{i}` com escopo nenhum servindo: o integrador não tinha como
provar que a chave valia, nem descobrir o que o glob cobria. E o 401 de uma
chave VÁLIDA fazia o preflight concluir "chave inválida", além de gastar o
limitador do console (dez perguntas e vinha 429).
"""

import pytest

from server.app import fsdb
from server.app.services import ratelimit, store


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def sedes(data_root, client, ha):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    for i, nome in (("26brspsp", "SP, São Paulo"), ("26bolapa", "La Paz"), ("labdoze", "Lab Doze")):
        r = client.post("/api/v1/site-images", json={"id": i, "fullname": nome, "model": "t"}, headers=ha)
        assert r.status_code == 201, r.text
    chave = store.machine_key("26brspsp")
    client.post(
        "/api/v1/site-images/26brspsp/machines/52-54-00-00-00-01/status",
        json={}, headers={"X-NB-Machine-Key": chave},
    )


def _chave(client, ha, scopes, images, nome="moj"):
    r = client.post("/api/v1/service-keys", json={"name": nome, "scopes": scopes, "images": images}, headers=ha)
    return {"Authorization": f"Bearer {r.json()['key']}"}


def test_whoami_da_chave_de_servico(client, sedes, ha):
    hs = _chave(client, ha, ["roster:write", "machines:read"], ["26br*"])
    r = client.get("/api/v1/whoami", headers=hs)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "kind": "service",
        "name": "moj",
        "label": "moj",
        "scopes": ["machines:read", "roster:write"],
        "image_globs": ["26br*"],
        "images": ["26brspsp"],
    }
    # o admin continua como era
    assert client.get("/api/v1/whoami", headers=ha).json()["kind"] == "admin"


def test_glob_vazio_cobre_tudo_e_sede_nova_entra_sozinha(client, sedes, ha):
    hs = _chave(client, ha, ["roster:read"], [])
    assert client.get("/api/v1/whoami", headers=hs).json()["images"] == ["26bolapa", "26brspsp", "labdoze"]


def test_lista_de_imagens_pelo_glob_sem_nada_de_console(client, sedes, ha):
    hs = _chave(client, ha, ["roster:read"], ["26*"])
    corpo = client.get("/api/v1/site-images", headers=hs).json()["images"]
    assert corpo == [
        {"id": "26bolapa", "fullname": "La Paz", "country": "BO", "machines_total": 0},
        {"id": "26brspsp", "fullname": "SP, São Paulo", "country": "BR", "machines_total": 1},
    ]
    # o contrato do admin não muda: o image.json, com o dono
    admin = client.get("/api/v1/site-images", headers=ha).json()["images"]
    assert {"id", "fullname", "owner", "model"} <= set(admin[0])


def test_imagem_pessoal_sem_pais_nao_inventa_um(client, sedes, ha):
    hs = _chave(client, ha, ["roster:read"], [])
    lab = next(i for i in client.get("/api/v1/site-images", headers=hs).json()["images"] if i["id"] == "labdoze")
    assert "country" not in lab
    r = client.patch("/api/v1/site-images/labdoze", json={"country": "MX"}, headers=ha)
    assert r.status_code == 200, r.text
    lab = next(i for i in client.get("/api/v1/site-images", headers=hs).json()["images"] if i["id"] == "labdoze")
    assert lab["country"] == "MX"
    assert client.patch("/api/v1/site-images/labdoze", json={"country": "mex"}, headers=ha).status_code == 422


def test_uma_imagem_dentro_do_glob_e_fora(client, sedes, ha):
    hs = _chave(client, ha, ["roster:read"], ["26br*"])  # sem machines:read, de propósito
    r = client.get("/api/v1/site-images/26brspsp", headers=hs)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["id"] == "26brspsp" and corpo["country"] == "BR" and corpo["machines_total"] == 1
    assert not {"owner", "token", "build_quota", "dashboard_hidden"} & set(corpo)

    fora = client.get("/api/v1/site-images/26bolapa", headers=hs)
    assert fora.status_code == 403 and fora.json()["code"] == "image_out_of_scope"
    nada = client.get("/api/v1/site-images/naoexiste", headers=hs)
    assert nada.status_code == 404 and nada.json()["code"] == "image_not_found"


def test_chave_valida_em_rota_de_console_e_403_e_nao_gasta_o_limitador(client, sedes, ha):
    ratelimit.reset()
    hs = {**_chave(client, ha, ["machines:read"], []), "X-Forwarded-For": "198.51.100.20"}
    for _ in range(25):
        r = client.get("/api/v1/models", headers=hs)
        assert r.status_code == 403 and r.json()["code"] == "console_only"
    r = client.post("/api/v1/commands", json={"command": "mlreboot", "targets": {}}, headers=hs)
    assert r.status_code == 403 and r.json()["code"] == "console_only"
    r = client.get("/api/v1/service-keys", headers=hs)
    assert r.status_code == 403 and r.json()["code"] == "console_only"
    # do mesmo IP, uma chave de admin ERRADA ainda é 401 (o balde está cheio)
    errada = {"Authorization": "Bearer nb3a_" + "0" * 32, "X-Forwarded-For": "198.51.100.20"}
    assert client.get("/api/v1/models", headers=errada).status_code == 401
    ratelimit.reset()


def test_credencial_que_nao_vale_continua_401(client, sedes):
    for h in ({}, {"Authorization": "Bearer nb3s_" + "0" * 32}):
        assert client.get("/api/v1/whoami", headers=h).status_code == 401
        assert client.get("/api/v1/site-images", headers=h).status_code == 401


def test_alerts_write_dispensa_sem_poder_comandar(client, sedes, ha):
    base = "/api/v1/site-images/26brspsp"
    mac = "52-54-00-00-00-01"
    so_alerta = _chave(client, ha, ["alerts:write"], [], nome="fiscal")
    legado = _chave(client, ha, ["commands:write"], [], nome="legado")
    leitor = _chave(client, ha, ["machines:read"], [], nome="leitor")

    assert client.post(f"{base}/machines/{mac}/alerts/dismiss-all", headers=so_alerta).status_code == 200
    assert client.post(f"{base}/machines/{mac}/alerts/dismiss-all", headers=legado).status_code == 200
    r = client.post(f"{base}/machines/{mac}/alerts/dismiss-all", headers=leitor)
    assert r.status_code == 403 and r.json()["code"] == "insufficient_scope"
    # quem só dispensa não manda desligar
    r = client.post(f"{base}/commands", json={"command": "mlpoweroff", "target": "all"}, headers=so_alerta)
    assert r.status_code == 403 and r.json()["code"] == "insufficient_scope"
