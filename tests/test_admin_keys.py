"""Chaves de administração pela API (e pela tela): ver, criar, revogar.

Só existia o `tools/nb3-init` no servidor: não havia como saber quantas chaves
de admin existiam, nem revogar uma que vazou sem editar arquivo na produção.
"""

import pytest

from server.app import fsdb
from server.app.services import audit, keys, ratelimit

CONSOLE = {"X-NB-Console": "1"}


@pytest.fixture
def client(data_root, admin_key):
    """https: o cookie de sessão é `Secure` e o cliente http o descartaria."""
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture(autouse=True)
def _limpo():
    ratelimit.reset()
    yield
    ratelimit.reset()


def _entrar(client, chave):
    r = client.post("/api/v1/session", json={"key": chave}, headers=CONSOLE)
    assert r.status_code == 200, r.text


def test_listar_diz_qual_e_a_desta_requisicao(client, ha):
    chaves = client.get("/api/v1/admin-keys", headers=ha).json()["keys"]
    assert len(chaves) == 1
    c = chaves[0]
    assert c["current"] is True and len(c["fp"]) == 8 and isinstance(c["last_used"], int)
    assert "sha256" not in c and "key" not in c


def test_por_bearer_a_posse_ja_esta_provada(client, ha, admin_key):
    r = client.post("/api/v1/admin-keys", json={"id": "camila"}, headers=ha)
    assert r.status_code == 201, r.text
    nova = r.json()
    assert nova["key"].startswith("nb3a_") and nova["id"] == "camila"
    # a chave nova entra, e é outra identidade na lista
    hn = {"Authorization": f"Bearer {nova['key']}"}
    lista = client.get("/api/v1/admin-keys", headers=hn).json()["keys"]
    assert {c["id"]: c["current"] for c in lista} == {"test": False, "camila": True}
    assert next(c for c in lista if c["id"] == "camila")["created_by"] == "test"
    assert client.post("/api/v1/admin-keys", json={"id": "camila"}, headers=ha).json()["code"] == "key_exists"
    assert client.post("/api/v1/admin-keys", json={"id": "Com Espaço"}, headers=ha).json()["code"] == "invalid_key_id"


def test_pela_sessao_precisa_redigitar_a_propria_chave(client, admin_key):
    """O cookie prova que alguém entrou neste navegador, não que é essa pessoa
    clicando agora; e uma chave cunhada sobrevive à sessão que a cunhou."""
    _entrar(client, admin_key)
    r = client.post("/api/v1/admin-keys", json={"id": "nova"}, headers=CONSOLE)
    assert r.status_code == 403 and r.json()["code"] == "reauth_required", "403, não 401: a sessão não morreu"
    r = client.post("/api/v1/admin-keys", json={"id": "nova", "current_key": "nb3a_" + "0" * 32}, headers=CONSOLE)
    assert r.status_code == 403
    r = client.post("/api/v1/admin-keys", json={"id": "nova", "current_key": admin_key}, headers=CONSOLE)
    assert r.status_code == 201, r.text
    # a chave de OUTRO admin não serve para confirmar a minha sessão
    outra = r.json()["key"]
    r = client.post("/api/v1/admin-keys", json={"id": "terceira", "current_key": outra}, headers=CONSOLE)
    assert r.status_code == 403
    atos = [e["action"] for e in audit.ler()]
    assert atos.count("reauth.failed") == 3 and "admin_key.created" in atos
    assert admin_key not in str(audit.ler()) and outra not in str(audit.ler())


def test_tentativas_de_reauth_tem_limite(client, admin_key):
    _entrar(client, admin_key)
    ultimo = None
    for _ in range(8):
        ultimo = client.post("/api/v1/admin-keys", json={"id": "x", "current_key": "errada"}, headers=CONSOLE)
    assert ultimo.status_code == 429 and ultimo.headers["Retry-After"]


def test_revogar_derruba_as_sessoes_daquela_chave_e_so_dela(client, ha, admin_key):
    from fastapi.testclient import TestClient

    nova = client.post("/api/v1/admin-keys", json={"id": "camila"}, headers=ha).json()
    dela = TestClient(client.app, base_url="https://testserver")
    _entrar(dela, nova["key"])
    _entrar(client, admin_key)
    assert dela.get("/api/v1/whoami", headers=CONSOLE).status_code == 200

    r = client.post("/api/v1/admin-keys/camila/revoke", json={}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json() == {"revoked": "camila", "fp": nova["fp"], "sessions_ended": 1, "remaining": 1}
    assert dela.get("/api/v1/whoami", headers=CONSOLE).status_code == 401
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 200, "derrubou a sessão errada"
    assert client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {nova['key']}"}).status_code == 401


def test_recriar_o_mesmo_id_nao_revive_a_sessao_antiga(client, ha):
    """A sessão revalidava só pelo id: revogar e recriar "camila" devolvia o
    acesso a quem tinha a sessão da chave revogada."""
    from fastapi.testclient import TestClient

    velha = client.post("/api/v1/admin-keys", json={"id": "camila"}, headers=ha).json()
    dela = TestClient(client.app, base_url="https://testserver")
    _entrar(dela, velha["key"])
    # tira a revogação do caminho "limpo": apaga a entrada, mas deixa a sessão no disco
    keys.admin_revogar("camila")
    client.post("/api/v1/admin-keys", json={"id": "camila"}, headers=ha)
    assert dela.get("/api/v1/whoami", headers=CONSOLE).status_code == 401


def test_nunca_a_ultima_e_a_propria_so_com_confirmacao(client, ha, admin_key):
    r = client.post("/api/v1/admin-keys/test/revoke", json={"confirm": "test"}, headers=ha)
    assert r.status_code == 409 and r.json()["code"] == "last_admin_key"
    client.post("/api/v1/admin-keys", json={"id": "reserva"}, headers=ha)
    r = client.post("/api/v1/admin-keys/test/revoke", json={}, headers=ha)
    assert r.status_code == 409 and r.json()["code"] == "confirm_required"
    r = client.post("/api/v1/admin-keys/test/revoke", json={"confirm": "test"}, headers=ha)
    assert r.status_code == 200
    assert client.get("/api/v1/whoami", headers=ha).status_code == 401
    assert client.post("/api/v1/admin-keys/naoexiste/revoke", json={}, headers=ha).status_code == 401


def test_dois_ids_iguais_herdados_so_a_impressao_digital_desempata(client, ha, data_root):
    from server.app import auth

    arq = data_root / "keys" / "admin.json"
    dados = fsdb.read_json(arq)
    gemea = auth.new_key("nb3a")
    dados["keys"] += [{"id": "dup", "sha256": auth.key_hash(gemea)},
                      {"id": "dup", "sha256": auth.key_hash(auth.new_key("nb3a"))}]
    fsdb.write_json(arq, dados)
    r = client.post("/api/v1/admin-keys/dup/revoke", json={}, headers=ha)
    assert r.status_code == 409 and r.json()["code"] == "key_ambiguous"
    fp = auth.key_hash(gemea)[:8]
    assert client.post("/api/v1/admin-keys/dup/revoke", json={"fp": fp}, headers=ha).status_code == 200
    assert [c["id"] for c in client.get("/api/v1/admin-keys", headers=ha).json()["keys"]] == ["test", "dup"]


def test_so_a_administracao(client, ha):
    code = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    hs = {"Authorization": f"Bearer {code}"}
    for metodo, rota in (("get", "/api/v1/admin-keys"), ("post", "/api/v1/admin-keys"),
                         ("post", "/api/v1/admin-keys/test/revoke"), ("get", "/api/v1/audit")):
        r = getattr(client, metodo)(rota, headers=hs, **({"json": {}} if metodo == "post" else {}))
        assert r.status_code == 401, rota


def test_auditoria_sem_segredo_nenhum(client, ha):
    nova = client.post("/api/v1/admin-keys", json={"id": "camila"}, headers=ha).json()
    client.post("/api/v1/admin-keys/camila/revoke", json={}, headers=ha)
    entradas = client.get("/api/v1/audit", headers=ha).json()["entries"]
    assert [e["action"] for e in entradas][:2] == ["admin_key.revoked", "admin_key.created"]
    assert entradas[0]["actor"] == "test" and entradas[0]["target"] == "camila" and isinstance(entradas[0]["at"], int)
    assert nova["key"] not in str(entradas)
