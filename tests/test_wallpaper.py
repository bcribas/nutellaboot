"""A prévia do papel de parede no configureitor.

A tela apontava para `/boot/v3/{id}/wallpaper`, que pede a chave de boot — a
credencial do pendrive, que a sede não tem e que uma tag `<img>` não teria como
mandar de qualquer jeito. Toda imagem criada pelo nutellaboot3 tem `boot.key`,
então a prévia nunca carregou em imagem nenhuma: ícone quebrado e nenhum aviso.

A rota nova vive junto do resto da configuração e aceita as credenciais que o
navegador tem: `?tk=` (token da sede, que já está na URL da tela) ou o cookie
de sessão. Como `<img>` também não manda `X-NB-Console`, o cookie vale sem ele
aqui — é GET, não muda estado, e sem CORS nenhuma página de fora lê a resposta.
É a mesma exceção, pela mesma razão, do SSE.
"""

import pytest

from server.app import fsdb

CONSOLE = {"X-NB-Console": "1"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def client(data_root):
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
def sede(client, data_root, ha):
    """Uma imagem como as de verdade: com boot.key, e com wallpaper enviado."""
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    criada = client.post(
        "/api/v1/site-images", json={"id": "sala1", "fullname": "S", "model": "t"}, headers=ha
    ).json()
    r = client.put(
        "/api/v1/site-images/sala1/wallpaper",
        files={"file": ("p.png", PNG, "image/png")},
        headers={"Authorization": f"Bearer {criada['token']}"},
    )
    assert r.status_code == 200, r.text
    assert (data_root / "site-images" / "sala1" / "boot.key").is_file()
    return criada


def test_a_previa_carrega_com_o_token_da_sede(client, sede):
    """É o que o configureitor tem: o `tk` que já vem na URL da tela."""
    r = client.get(f"/api/v1/site-images/sala1/wallpaper?tk={sede['token']}")
    assert r.status_code == 200, r.text
    assert r.content == PNG
    assert r.headers["content-type"].startswith("image/")


def test_a_previa_carrega_com_a_sessao_do_console(client, sede, admin_key):
    """Sem `X-NB-Console`: uma tag <img> não manda cabeçalho nenhum."""
    client.post("/api/v1/session", json={"key": admin_key}, headers=CONSOLE)
    r = client.get("/api/v1/site-images/sala1/wallpaper")
    assert r.status_code == 200, r.text


def test_sem_credencial_nao_carrega(client, sede):
    assert client.get("/api/v1/site-images/sala1/wallpaper").status_code == 401
    assert client.get("/api/v1/site-images/sala1/wallpaper?tk=nb3i_errado").status_code == 401


def test_token_de_outra_imagem_nao_carrega(client, sede, ha, data_root):
    outra = client.post(
        "/api/v1/site-images", json={"id": "sala2", "fullname": "S2", "model": "t"}, headers=ha
    ).json()
    r = client.get(f"/api/v1/site-images/sala1/wallpaper?tk={outra['token']}")
    assert r.status_code == 401


def test_imagem_sem_wallpaper_responde_404(client, ha, data_root):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    criada = client.post(
        "/api/v1/site-images", json={"id": "vazia", "fullname": "V", "model": "t"}, headers=ha
    ).json()
    r = client.get(f"/api/v1/site-images/vazia/wallpaper?tk={criada['token']}")
    assert r.status_code == 404


def test_a_tela_aponta_para_a_rota_certa():
    """A rota de boot continua existindo (é dela que a máquina baixa), mas a
    tela não pode voltar a apontar para lá."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "web"
    app = (web / "configureitor" / "app.js").read_text(encoding="utf-8")
    assert "/boot/v3/" not in app, "a prévia voltou para a rota da chave de boot"
    assert "wallpaperUrl" in app
