"""Sessão do console: entrar uma vez e continuar dentro.

Antes disto, recarregar o `/admin/` deslogava — a tela regravava o campo de
login (vazio no carregamento) por cima da chave guardada, o servidor devolvia
401 e o tratamento de erro apagava o resto. Agora a chave é trocada uma vez por
um cookie HttpOnly e o navegador cuida do resto.

O que estes testes protegem, além de "funciona": que o cookie não abriu CSRF,
que o Bearer continua sendo o caminho das ferramentas, e que trocar a chave de
administração continua derrubando o acesso na hora.
"""

import time

import pytest

from server.app import fsdb
from server.app.services import sessions
from server.app.services.default_schema import build_default_schema

CONSOLE = {"X-NB-Console": "1"}


@pytest.fixture
def client(data_root):
    """Cliente em HTTPS. O cookie de sessão é `Secure` — o navegador (e o
    cliente de teste) não o mandam por HTTP, que é exatamente o ponto: em
    produção quem termina TLS é o nginx."""
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture(autouse=True)
def sem_limite():
    from server.app.services import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def base(client, data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    return admin_key


def entrar(client, chave):
    return client.post("/api/v1/session", json={"key": chave}, headers=CONSOLE)


# --- entrar ---


def test_chave_de_admin_abre_sessao(client, base, admin_key):
    r = entrar(client, admin_key)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "admin"
    assert r.json()["expires_at"] > time.time()
    assert sessions.COOKIE in r.cookies


def test_o_cookie_sozinho_entra_no_console(client, base, admin_key):
    """É isto que o reload passa a fazer: nenhuma credencial no JavaScript,
    nenhum cabeçalho Authorization — só o cookie que o navegador guarda."""
    entrar(client, admin_key)
    r = client.get("/api/v1/whoami", headers=CONSOLE)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "admin"


def test_o_cookie_tem_as_protecoes(client, base, admin_key):
    """HttpOnly tira do alcance de qualquer script da página; Secure impede
    que vaze por HTTP; SameSite=Strict barra requisição vinda de outro site."""
    r = entrar(client, admin_key)
    bruto = r.headers["set-cookie"].lower()
    assert "httponly" in bruto
    assert "secure" in bruto
    assert "samesite=strict" in bruto
    assert "max-age=2592000" in bruto  # 30 dias


def test_codigo_de_convite_tambem_abre_sessao(client, base, ha):
    code = client.post(
        "/api/v1/invites", json={"count": 1, "max_images": 1}, headers=ha
    ).json()["invites"][0]["code"]
    r = entrar(client, code)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "subadmin"


def test_chave_errada_nao_abre_e_nao_vaza(client, base):
    r = entrar(client, "nb3a_naoexiste")
    assert r.status_code == 401
    assert sessions.COOKIE not in r.cookies


def test_tentativa_repetida_leva_a_429(client, base):
    vistos = [entrar(client, f"nb3a_{i:032d}").status_code for i in range(20)]
    assert 429 in vistos


def test_chave_de_servico_nao_abre_sessao(client, base, ha):
    """Chave de serviço é credencial de programa (o MOJ), não de navegador."""
    chave = client.post(
        "/api/v1/service-keys",
        json={"name": "moj", "scopes": ["machines:read"]},
        headers=ha,
    ).json()["key"]
    assert entrar(client, chave).status_code == 401


# --- sair ---


def test_sair_encerra_a_sessao(client, base, admin_key):
    entrar(client, admin_key)
    assert client.delete("/api/v1/session", headers=CONSOLE).status_code == 200
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 401


def test_sair_de_todos_os_dispositivos(client, base, admin_key):
    """Para quando uma máquina se perde com a sessão aberta."""
    entrar(client, admin_key)
    sid_outro = sessions.create("admin", "test")["id"]
    r = client.delete("/api/v1/session?all=true", headers=CONSOLE)
    assert r.json()["ended"] >= 2
    assert sessions.resolve(sid_outro) is None


# --- revogação: a razão de a sessão ter estado, e não ser só assinada ---


def test_trocar_a_chave_de_admin_derruba_a_sessao(client, base, data_root, admin_key):
    """Com sessão assinada (stateless) isto não seria possível: a sessão
    sobreviveria 30 dias à rotação da chave."""
    entrar(client, admin_key)
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 200

    fsdb.write_json(data_root / "keys" / "admin.json", {"keys": []})
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 401


def test_suspender_o_subadmin_derruba_a_sessao(client, base, ha):
    from server.app.services import owners

    code = client.post(
        "/api/v1/invites", json={"count": 1}, headers=ha
    ).json()["invites"][0]["code"]
    entrar(client, code)
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 200

    owners.set_disabled(owners.owner_id(code), True)
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 401


def test_revogar_o_convite_derruba_a_sessao(client, base, ha):
    code = client.post(
        "/api/v1/invites", json={"count": 1}, headers=ha
    ).json()["invites"][0]["code"]
    entrar(client, code)
    client.delete(f"/api/v1/invites/{code}", headers=ha)
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 401


def test_sessao_expirada_nao_entra(client, base, admin_key, monkeypatch):
    entrar(client, admin_key)
    depois = time.time() + sessions.DURACAO + 60
    monkeypatch.setattr(time, "time", lambda: depois)
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 401


# --- CSRF: o preço de existir cookie ---


def test_cookie_sem_o_cabecalho_nao_vale(client, base, admin_key):
    """Um <form> de outro site consegue mandar o cookie, mas não consegue
    definir cabeçalho. Sem X-NB-Console, o cookie é ignorado."""
    entrar(client, admin_key)
    assert client.get("/api/v1/whoami").status_code == 401
    assert client.post("/api/v1/models", json={"name": "invadido"}).status_code == 401


def test_ver_e_encerrar_sessao_tambem_exigem_o_cabecalho(client, base, admin_key):
    """As duas liam o cookie direto, fora do ponto único de credencial —
    únicas rotas de console sem essa defesa. `DELETE ?all=true` derruba todas
    as sessões de alguém; não é lugar para depender só do SameSite."""
    entrar(client, admin_key)
    assert client.get("/api/v1/session").status_code == 401
    assert client.delete("/api/v1/session?all=true").status_code == 401
    # e a sessão continua de pé: a tentativa sem cabeçalho não derrubou nada
    assert client.get("/api/v1/whoami", headers=CONSOLE).status_code == 200


@pytest.mark.parametrize(
    "metodo,rota,corpo",
    [
        ("post", "/api/v1/models", {"name": "modelo-csrf"}),
        ("post", "/api/v1/invites", {}),
        ("post", "/api/v1/site-images", {"id": "sala1", "fullname": "S", "model": "t"}),
    ],
)
def test_escrita_com_cookie_exige_o_cabecalho(client, base, admin_key, metodo, rota, corpo):
    entrar(client, admin_key)
    sem = getattr(client, metodo)(rota, json=corpo)
    assert sem.status_code == 401, f"{rota} aceitou sem o cabecalho"
    com = getattr(client, metodo)(rota, json=corpo, headers=CONSOLE)
    assert com.status_code < 400, com.text


# --- o Bearer não pode ter quebrado ---


def test_bearer_continua_funcionando(client, base, admin_key, ha):
    """É o que as ferramentas de linha de comando e o MOJ usam. Nenhuma delas
    manda cookie nem o cabeçalho de console."""
    assert client.get("/api/v1/whoami", headers=ha).status_code == 200
    assert client.get("/api/v1/models", headers=ha).status_code == 200
    r = client.post("/api/v1/models", json={"name": "porbearer"}, headers=ha)
    assert r.status_code == 201, r.text


def test_token_de_imagem_continua_funcionando(client, base, ha):
    """O link de sede (/configureitor/?id=&tk=) não muda."""
    criada = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "S", "model": "t"},
        headers=ha,
    ).json()
    r = client.get(
        "/api/v1/site-images/sala1/config",
        headers={"Authorization": f"Bearer {criada['token']}"},
    )
    assert r.status_code == 200


def test_chave_de_maquina_continua_funcionando(client, base, ha):
    criada = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "S", "model": "t"},
        headers=ha,
    ).json()
    r = client.post(
        "/api/v1/site-images/sala1/machines/52-54-00-11-22-33/status",
        json={"hwinfo": {}},
        headers={"X-NB-Machine-Key": criada["machine_key"]},
    )
    assert r.status_code == 200


# --- o serviço em si ---


def test_sessao_nao_vale_para_credencial_de_programa():
    with pytest.raises(ValueError):
        sessions.create("service", "moj")


def test_sessao_de_outro_id_nao_resolve(data_root):
    assert sessions.resolve("inventado") is None
    assert sessions.resolve("") is None


def test_expiradas_saem_do_arquivo(data_root, admin_key, monkeypatch):
    fsdb.write_json(data_root / "keys" / "admin.json", {"keys": [{"id": "a", "sha256": "x"}]})
    velha = sessions.create("admin", "a")["id"]
    monkeypatch.setattr(time, "time", lambda: 1e12)  # muito depois do prazo
    sessions.create("admin", "a")
    assert velha not in fsdb.read_json(data_root / "sessions.json", {})


def test_arquivo_de_sessoes_e_privado(data_root, admin_key):
    fsdb.write_json(data_root / "keys" / "admin.json", {"keys": [{"id": "a", "sha256": "x"}]})
    sessions.create("admin", "a")
    modo = (data_root / "sessions.json").stat().st_mode & 0o777
    assert modo == 0o600, oct(modo)


# --- a regressão que gerou tudo isto ---


def test_o_front_nao_guarda_mais_credencial():
    """A tela regravava o campo de login vazio por cima da chave a cada
    carregamento. A credencial deixou de morar no navegador; se voltar a
    morar, este teste avisa."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "web"
    api = (web / "common" / "api.js").read_text(encoding="utf-8")
    assert "sessionStorage.setItem" not in api
    assert "localStorage.setItem" not in api

    for tela in ("admin/app.js", "criar/app.js", "index.js"):
        texto = (web / tela).read_text(encoding="utf-8")
        assert "nb3-admin-key" not in texto, f"{tela} ainda guarda a chave"


def test_o_console_entra_pela_sessao_no_carregamento():
    from pathlib import Path

    app = (Path(__file__).resolve().parents[1] / "web" / "admin" / "app.js").read_text()
    assert "retomarSessao" in app
    assert "api.login(" in app
    # o padrão antigo: enter() chamado no carregamento, regravando o campo vazio
    assert "if (api.consoleKey()) enter();" not in app
