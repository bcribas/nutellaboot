"""Chaves de serviço com ciclo de vida: data, último uso, rotação, e sem
sobrescrever calado."""

import pytest

from server.app import fsdb
from server.app.services import keyusage


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def _criar(client, ha, nome="moj", **extra):
    corpo = {"name": nome, "scopes": ["machines:read"], "images": ["26*"], **extra}
    return client.post("/api/v1/service-keys", json=corpo, headers=ha)


def test_nome_repetido_e_erro_e_nao_sobrescrita(client, ha):
    """Recriar "moj" pela tela trocava a credencial do MOJ sem aviso."""
    primeira = _criar(client, ha).json()["key"]
    r = _criar(client, ha)
    assert r.status_code == 409 and r.json()["code"] == "key_exists"
    assert client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {primeira}"}).status_code == 200


def test_a_lista_traz_todas_com_data_quem_criou_e_ultimo_uso(client, ha):
    chave = _criar(client, ha).json()["key"]
    _criar(client, ha, nome="dashboard-x", scopes=["labs:read"], images=[])
    lista = {k["name"]: k for k in client.get("/api/v1/service-keys", headers=ha).json()["service_keys"]}
    assert set(lista) == {"moj", "dashboard-x"}
    moj = lista["moj"]
    assert isinstance(moj["created_at"], int) and moj["created_by"] == "test" and moj["last_used"] is None
    assert "sha256" not in moj and "key" not in moj
    client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {chave}"})
    lista = {k["name"]: k for k in client.get("/api/v1/service-keys", headers=ha).json()["service_keys"]}
    assert isinstance(lista["moj"]["last_used"], int)


def test_rotacionar_mantem_nome_escopos_e_globs_e_mata_a_antiga(client, ha):
    antiga = _criar(client, ha).json()["key"]
    r = client.post("/api/v1/service-keys/moj/rotate", headers=ha)
    assert r.status_code == 200, r.text
    nova = r.json()
    assert nova["key"] != antiga and nova["scopes"] == ["machines:read"] and nova["images"] == ["26*"]
    assert isinstance(nova["rotated_at"], int)
    assert client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {antiga}"}).status_code == 401
    assert client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {nova['key']}"}).json()["name"] == "moj"
    assert client.post("/api/v1/service-keys/naoexiste/rotate", headers=ha).json()["code"] == "key_not_found"


def test_alterar_escopos_e_globs_sem_trocar_a_chave(client, ha):
    chave = _criar(client, ha).json()["key"]
    r = client.patch("/api/v1/service-keys/moj", json={"scopes": ["machines:read", "roster:write"], "images": []}, headers=ha)
    assert r.status_code == 200 and r.json()["scopes"] == ["machines:read", "roster:write"]
    eu = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {chave}"}).json()
    assert eu["scopes"] == ["machines:read", "roster:write"] and eu["image_globs"] == []
    assert client.patch("/api/v1/service-keys/moj", json={"scopes": ["voar"]}, headers=ha).status_code == 400


def test_follow_so_com_labs_read_e_so_a_administracao(client, ha):
    assert _criar(client, ha, nome="a", follow="admin").status_code == 400
    assert _criar(client, ha, nome="b", scopes=["labs:read"], follow="outro").status_code == 400
    r = _criar(client, ha, nome="telao", scopes=["labs:read"], images=[], follow="admin")
    assert r.status_code == 200 and r.json()["follow"] == "admin"
    assert client.patch("/api/v1/service-keys/telao", json={"follow": ""}, headers=ha).json()["follow"] == ""
    # tirar o labs:read de uma chave que segue é incoerente
    client.patch("/api/v1/service-keys/telao", json={"follow": "admin"}, headers=ha)
    assert client.patch("/api/v1/service-keys/telao", json={"scopes": ["machines:read"]}, headers=ha).status_code == 400


def test_ultimo_uso_nao_escreve_em_disco_por_requisicao(client, ha, data_root):
    """Dezenas de requisições por segundo num worker só: o instante fica na
    memória e vai ao disco no máximo uma vez por minuto, num arquivo que NÃO é
    o admin.json."""
    keyusage.reset()
    arq = data_root / "keys" / "last-used.json"
    chave = _criar(client, ha).json()["key"]
    antes = (data_root / "keys" / "admin.json").read_bytes()
    for _ in range(30):
        client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {chave}"})
    assert not arq.exists(), "escreveu por requisição"
    assert keyusage.despejar() is True
    assert keyusage.despejar() is False, "sem uso novo não há o que gravar"
    gravado = fsdb.read_json(arq)
    assert "service:moj" in gravado and any(k.startswith("admin:") for k in gravado)
    assert (data_root / "keys" / "admin.json").read_bytes() == antes
    # sobrevive a um restart (a memória some, o disco fica)
    keyusage.reset()
    assert isinstance(keyusage.ultimo("service", "moj"), int)


def test_revogar_e_so_a_administracao(client, ha):
    _criar(client, ha)
    assert client.delete("/api/v1/service-keys/moj", headers=ha).status_code == 204
    assert client.get("/api/v1/service-keys", headers=ha).json()["service_keys"] == []
    code = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    assert _criar(client, {"Authorization": f"Bearer {code}"}).status_code == 401
