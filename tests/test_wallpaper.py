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


# --- o papel de parede do MODELO ---------------------------------------------
#
# A organização define um papel de parede uma vez e toda sede daquele modelo o
# usa, sem poder trocar. A herança é POR CONSULTA, não por cópia: trocar no
# modelo na véspera tem que chegar às sedes já criadas.
#
# São três consumidores, e errar um deles dá o pior tipo de defeito, o parcial:
# o md5 no `stuff` (é ele que faz a máquina baixar), o download do boot e a
# prévia do configureitor. Cada um tem teste próprio aqui.

PNG2 = b"\x89PNG\r\n\x1a\n" + b"modelo" * 20


@pytest.fixture
def sede_sem_wallpaper(client, data_root, ha):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return client.post(
        "/api/v1/site-images", json={"id": "sala2", "fullname": "S2", "model": "t"}, headers=ha
    ).json()


def sobe_no_modelo(client, ha, nome="t", conteudo=PNG2):
    r = client.put(
        f"/api/v1/models/{nome}/wallpaper",
        files={"file": ("m.png", conteudo, "image/png")},
        headers=ha,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_sede_sem_wallpaper_recebe_o_do_modelo(client, sede_sem_wallpaper, ha):
    meta = sobe_no_modelo(client, ha)
    r = client.get(f"/api/v1/site-images/sala2/wallpaper?tk={sede_sem_wallpaper['token']}")
    assert r.status_code == 200, r.text
    assert r.content == PNG2
    dados = client.get(
        "/api/v1/site-images/sala2/config",
        headers={"Authorization": f"Bearer {sede_sem_wallpaper['token']}"},
    ).json()
    assert dados["wallpaper"]["md5"] == meta["md5"]
    assert dados["wallpaper"]["origin"] == "model", "a tela precisa dizer de onde veio"


def test_o_md5_do_stuff_segue_o_modelo(client, sede_sem_wallpaper, ha):
    """É o md5 do stuff que faz a máquina baixar: esquecer a herança aqui
    deixaria a sala sem papel de parede com o modelo tendo um."""
    from server.app.services import stuffgen

    meta = sobe_no_modelo(client, ha)
    linhas = [l for l in stuffgen.render("sala2").splitlines() if l.startswith("NB_WALLPAPER_MD5=")]
    assert linhas and meta["md5"] in linhas[0], linhas


def test_o_boot_baixa_o_wallpaper_do_modelo(client, data_root, sede_sem_wallpaper, ha):
    sobe_no_modelo(client, ha)
    bk = (data_root / "site-images" / "sala2" / "boot.key").read_text().strip()
    r = client.get("/boot/v3/sala2/wallpaper", headers={"X-NB-Boot-Key": bk})
    assert r.status_code == 200, r.text
    assert r.content == PNG2


def test_o_da_sede_ganha_do_modelo(client, sede, ha):
    """Quem tem o seu próprio continua com ele."""
    sobe_no_modelo(client, ha)
    r = client.get(f"/api/v1/site-images/sala1/wallpaper?tk={sede['token']}")
    assert r.content == PNG, "o do modelo atropelou o da sede"


def test_apagar_o_da_sede_devolve_o_do_modelo(client, sede, ha):
    sobe_no_modelo(client, ha)
    client.delete("/api/v1/site-images/sala1/wallpaper", headers=ha)
    r = client.get(f"/api/v1/site-images/sala1/wallpaper?tk={sede['token']}")
    assert r.content == PNG2


def test_trocar_no_modelo_chega_nas_sedes_ja_criadas(client, sede_sem_wallpaper, ha):
    """O motivo de a herança ser por consulta e não por cópia: isto acontece na
    véspera, com as sedes já criadas."""
    sobe_no_modelo(client, ha)
    novo = b"\x89PNG\r\n\x1a\n" + b"trocado" * 20
    sobe_no_modelo(client, ha, conteudo=novo)
    r = client.get(f"/api/v1/site-images/sala2/wallpaper?tk={sede_sem_wallpaper['token']}")
    assert r.content == novo


def test_a_trava_do_modelo_vale_para_a_sede(client, sede_sem_wallpaper, ha):
    sobe_no_modelo(client, ha)
    assert client.patch("/api/v1/models/t", json={"wallpaper_locked": True}, headers=ha).status_code == 200

    tk = {"Authorization": f"Bearer {sede_sem_wallpaper['token']}"}
    r = client.put(
        "/api/v1/site-images/sala2/wallpaper",
        files={"file": ("x.png", PNG, "image/png")},
        headers=tk,
    )
    assert r.status_code == 400, r.text
    assert client.get("/api/v1/site-images/sala2/config", headers=tk).json()["can_edit_wallpaper"] is False

    # e a administração continua podendo
    assert client.put(
        "/api/v1/site-images/sala2/wallpaper",
        files={"file": ("x.png", PNG, "image/png")},
        headers=ha,
    ).status_code == 200


def test_destravar_no_modelo_libera_todas(client, sede_sem_wallpaper, ha):
    client.patch("/api/v1/models/t", json={"wallpaper_locked": True}, headers=ha)
    client.patch("/api/v1/models/t", json={"wallpaper_locked": False}, headers=ha)
    tk = {"Authorization": f"Bearer {sede_sem_wallpaper['token']}"}
    assert client.get("/api/v1/site-images/sala2/config", headers=tk).json()["can_edit_wallpaper"]


def test_o_modelo_so_aceita_imagem(client, ha, data_root):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    r = client.put(
        "/api/v1/models/t/wallpaper",
        files={"file": ("x.png", b"nao sou imagem", "image/png")},
        headers=ha,
    )
    assert r.status_code == 400, r.text
