"""Endpoint de credenciais: o caminho fácil para o admin pegar token e links.

No NutellaBoot 2 não havia como recuperar o token de uma imagem existente sem
efeitos colaterais; aqui o admin lê tudo de uma vez, sem rotacionar (o que
invalidaria os links já entregues aos coordenadores)."""

import pytest

from server.app import fsdb
from server.app.services import store


@pytest.fixture
def img(data_root, admin_key):
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    return store.create_image("25brbr", "Sede de teste", "t")


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def test_credentials_devolve_tudo(client, img, ha):
    r = client.get("/api/v1/images/25brbr/credentials", headers=ha)
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == img["token"]
    assert body["boot_key"] == img["boot_key"]
    assert body["machine_key"] == img["machine_key"]
    # os links já vêm com o token embutido, prontos para entregar
    assert body["configureitor_url"].endswith(f"?id=25brbr&tk={img['token']}")
    assert "/configureitor/" in body["configureitor_url"]
    assert "/hotconfig/" in body["hotconfig_url"]
    assert f"tk={img['token']}" in body["hotconfig_url"]


def test_credentials_nao_rotaciona(client, img, ha):
    """Ler credenciais não pode mudar o token (senão quebraria links já dados)."""
    antes = client.get("/api/v1/images/25brbr/credentials", headers=ha).json()["token"]
    depois = client.get("/api/v1/images/25brbr/credentials", headers=ha).json()["token"]
    assert antes == depois == img["token"]


def test_credentials_exige_admin(client, img):
    # sem chave nenhuma
    assert client.get("/api/v1/images/25brbr/credentials").status_code == 401
    # com o token da própria imagem NÃO basta: credenciais é coisa de admin
    r = client.get(
        "/api/v1/images/25brbr/credentials",
        headers={"Authorization": f"Bearer {img['token']}"},
    )
    assert r.status_code == 401


def test_credentials_404_imagem_inexistente(client, ha):
    assert client.get("/api/v1/images/naoexiste/credentials", headers=ha).status_code == 404


def test_link_de_criacao_ja_inclui_token(client, admin_key, data_root):
    """O link devolvido na criação precisa ser clicável (id + token)."""
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    r = client.post(
        "/api/v1/images",
        json={"id": "univap", "fullname": "Univap", "template": "t"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    body = r.json()
    assert f"tk={body['token']}" in body["configureitor_url"]
    assert "hotconfig_url" in body
