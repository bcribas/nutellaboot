"""Camada por imagem, pelo caminho do navegador.

`POST`/`GET /site-images/{img}/layerbuilds` liam `Authorization` na mão, sem
passar pelo ponto único de credencial. Quando o console trocou a chave pelo
cookie de sessão, as duas ficaram 401 para admin e para sub-admin: o botão
"gerar camada para esta imagem" só mostrava erro, e o botão "camadas" da lista
não abria painel nenhum (a tela nem trata a exceção).

Nenhum teste pegou porque todos batiam nessas rotas com Bearer explícito —
que é o caminho das ferramentas, e continuava funcionando.
"""

import pytest

from server.app import fsdb
from server.app.services import store

CONSOLE = {"X-NB-Console": "1"}


@pytest.fixture
def client(data_root):
    """HTTPS: o cookie de sessão é `Secure` e não viaja por HTTP."""
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


@pytest.fixture(autouse=True)
def sem_limite():
    from server.app.services import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def base(client, data_root, admin_key, ha):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": [], "public": True})
    r = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "Sala 1", "model": "t"},
        headers=ha,
    )
    assert r.status_code == 201, r.text
    return r.json()


def entrar(client, chave):
    r = client.post("/api/v1/session", json={"key": chave}, headers=CONSOLE)
    assert r.status_code == 200, r.text
    return r


CORPO = {"name": "extras", "packages": ["htop"]}


# --- o caminho do navegador ---


def test_admin_monta_camada_por_imagem_so_com_o_cookie(client, base, admin_key):
    entrar(client, admin_key)
    r = client.post("/api/v1/site-images/sala1/layerbuilds", json=CORPO, headers=CONSOLE)
    assert r.status_code == 201, r.text
    assert r.json()["attach_to"] == ["sala1"]
    # admin não gasta cota da imagem
    assert r.json()["quota"] is None


def test_admin_lista_camadas_da_imagem_so_com_o_cookie(client, base, admin_key):
    entrar(client, admin_key)
    client.post("/api/v1/site-images/sala1/layerbuilds", json=CORPO, headers=CONSOLE)
    r = client.get("/api/v1/site-images/sala1/layerbuilds", headers=CONSOLE)
    assert r.status_code == 200, r.text
    assert [b["name"] for b in r.json()["builds"]] == ["extras"]


def test_subadmin_dono_monta_pela_sessao(client, base, ha, data_root):
    code = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    entrar(client, code)
    criada = client.post(
        "/api/v1/site-images",
        json={"id": "minhasala", "fullname": "M", "model": "t"},
        headers=CONSOLE,
    )
    assert criada.status_code == 201, criada.text
    r = client.post("/api/v1/site-images/minhasala/layerbuilds", json=CORPO, headers=CONSOLE)
    assert r.status_code == 201, r.text


def test_imagem_de_outro_dono_responde_404(client, base, ha):
    """E não 401: o sub-admin autenticado não pode distinguir "não é sua" de
    "não existe"."""
    code = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    entrar(client, code)
    r = client.get("/api/v1/site-images/sala1/layerbuilds", headers=CONSOLE)
    assert r.status_code == 404, r.text
    assert store.site_image_exists("sala1")


# --- o que não podia quebrar ---


def test_bearer_continua_valendo(client, base, ha):
    """É o caminho das ferramentas de linha de comando."""
    r = client.post("/api/v1/site-images/sala1/layerbuilds", json=CORPO, headers=ha)
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/site-images/sala1/layerbuilds", headers=ha).status_code == 200


def test_token_da_imagem_continua_valendo_e_gasta_cota(client, base, ha):
    """O dono da sede pede build pelo configureitor, com o token da URL — e
    esse sim gasta a cota, que existe para conter o auto-atendimento."""
    client.patch("/api/v1/site-images/sala1", json={"build_quota": 1}, headers=ha)
    hi = {"Authorization": f"Bearer {base['token']}"}
    r = client.post("/api/v1/site-images/sala1/layerbuilds", json=CORPO, headers=hi)
    assert r.status_code == 201, r.text
    assert r.json()["quota"] == 1
    # e a cota realmente contém: a segunda não passa
    r = client.post(
        "/api/v1/site-images/sala1/layerbuilds", json={**CORPO, "name": "outra"}, headers=hi
    )
    assert r.status_code == 403
    assert "cota" in r.json()["detail"]


def test_sem_o_cabecalho_de_console_o_cookie_nao_vale(client, base, admin_key):
    """A defesa de CSRF vale aqui como em toda escrita do console."""
    entrar(client, admin_key)
    assert client.post("/api/v1/site-images/sala1/layerbuilds", json=CORPO).status_code == 401


def test_sem_credencial_e_401_exista_a_imagem_ou_nao(client, base):
    for img in ("sala1", "nao-existe"):
        r = client.get(f"/api/v1/site-images/{img}/layerbuilds")
        assert r.status_code == 401, f"{img} deu {r.status_code}"
