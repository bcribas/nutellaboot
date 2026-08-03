"""Sub-admins: o código de convite como credencial de console.

O que importa aqui não é só "funciona" — é o isolamento. Um sub-admin não pode
tomar nome reservado, não pode ver nem tocar no que é de outro, e o que é de
outro tem que responder 404 (um 403 já entregaria que o nome existe).
"""

import pytest

from server.app import fsdb
from server.app.services import invites, owners, ratelimit, store

MD5 = "0" * 32


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture(autouse=True)
def sem_limite():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def base(data_root, admin_key, client):
    """Um modelo público da administração, que é o ponto de partida de quem
    entra por convite."""
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    h = {"Authorization": f"Bearer {admin_key}"}
    client.post("/api/v1/models", json={"name": "oficial", "public": True}, headers=h)
    client.post(
        "/api/v1/models/oficial/layers",
        json={"file": "base.squashfs", "md5": MD5},
        headers=h,
    )
    return admin_key


def _convite(client, ha, **kw):
    corpo = {"max_images": 3, "max_models": 2, "count": 1, **kw}
    r = client.post("/api/v1/invites", json=corpo, headers=ha)
    assert r.status_code == 201, r.text
    return r.json()["invites"][0]["code"]


def _hs(code):
    return {"Authorization": f"Bearer {code}"}


# --- a credencial ---


def test_codigo_de_convite_abre_o_console(client, base, ha):
    code = _convite(client, ha)
    r = client.get("/api/v1/whoami", headers=_hs(code))
    assert r.status_code == 200, r.text
    eu = r.json()
    assert eu["kind"] == "subadmin"
    assert eu["can_create_reserved"] is False
    assert eu["can_manage_invites"] is False
    assert eu["quotas"]["site_images"] == 3


def test_codigo_novo_tem_tres_grupos(client, base, ha):
    """Como credencial de longa duração, dois grupos (40 bits) era pouco."""
    code = _convite(client, ha)
    assert len(code.split("-")) == 4


def test_codigo_inexistente_nao_entra(client, base):
    assert client.get("/api/v1/whoami", headers=_hs("NB3-AAAA-BBBB-CCCC")).status_code == 401


def test_codigo_expirado_nao_entra(client, base, ha):
    code = _convite(client, ha, expires_at=1.0)
    assert client.get("/api/v1/whoami", headers=_hs(code)).status_code == 401


def test_cota_de_imagem_esgotada_nao_tranca_o_console(client, base, ha):
    """Quem gastou a cota continua tendo que administrar o que já criou."""
    code = _convite(client, ha, max_images=1)
    client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "S", "model": "oficial"},
        headers=_hs(code),
    )
    assert client.get("/api/v1/whoami", headers=_hs(code)).status_code == 200


def test_erro_repetido_de_codigo_leva_429(client, base):
    """Código curto o bastante para digitar à mão é curto o bastante para
    tentar na força bruta."""
    vistos = [
        client.get("/api/v1/whoami", headers=_hs(f"NB3-AAAA-BBBB-{i:04d}")).status_code
        for i in range(20)
    ]
    assert 429 in vistos


# --- nomes reservados ---


@pytest.mark.parametrize("nome", ["26sede", "0abc", "9x"])
def test_subadmin_nao_cria_nome_com_digito(client, base, ha, nome):
    code = _convite(client, ha)
    r = client.post("/api/v1/models", json={"name": nome}, headers=_hs(code))
    assert r.status_code == 403
    r = client.post(
        "/api/v1/site-images",
        json={"id": nome, "fullname": "x", "model": "oficial"},
        headers=_hs(code),
    )
    assert r.status_code == 403
    assert not store.model_exists(nome)
    assert not store.site_image_exists(nome)


@pytest.mark.parametrize("nome", ["maratona", "icpc", "admin"])
def test_subadmin_nao_toma_nome_da_casa(client, base, ha, nome):
    code = _convite(client, ha)
    r = client.post("/api/v1/models", json={"name": nome}, headers=_hs(code))
    assert r.status_code == 403


def test_admin_cria_nome_com_digito(client, base, ha):
    r = client.post("/api/v1/models", json={"name": "26maratona"}, headers=ha)
    assert r.status_code == 201


# --- isolamento entre sub-admins ---


@pytest.fixture
def dois(client, base, ha):
    a, b = _convite(client, ha), _convite(client, ha)
    client.post("/api/v1/models", json={"name": "modelo-a"}, headers=_hs(a))
    client.post("/api/v1/models", json={"name": "modelo-b"}, headers=_hs(b))
    for code, img in ((a, "salaa"), (b, "salab")):
        r = client.post(
            "/api/v1/site-images",
            json={"id": img, "fullname": img, "model": "oficial"},
            headers=_hs(code),
        )
        assert r.status_code == 201, r.text
    return a, b


def test_cada_um_lista_so_o_seu(client, dois):
    a, b = dois
    meus = client.get("/api/v1/models", headers=_hs(a)).json()["models"]
    nomes = {m["name"] for m in meus}
    assert "modelo-a" in nomes
    assert "modelo-b" not in nomes
    # o modelo público da administração aparece: é dele que se deriva
    assert "oficial" in nomes

    imgs = client.get("/api/v1/site-images", headers=_hs(a)).json()["images"]
    assert {i["id"] for i in imgs} == {"salaa"}


def test_modelo_de_outro_responde_404_e_nao_403(client, dois):
    """403 confirmaria que o nome está tomado; nomes são por ordem de
    chegada, então isso seria um oráculo de existência."""
    a, _ = dois
    for metodo, rota in [
        ("get", "/api/v1/models/modelo-b"),
        ("delete", "/api/v1/models/modelo-b"),
        ("patch", "/api/v1/models/modelo-b"),
        ("get", "/api/v1/models/modelo-b/schema"),
    ]:
        r = client.request(metodo.upper(), rota, headers=_hs(a), json={})
        assert r.status_code == 404, f"{metodo} {rota} deu {r.status_code}"


def test_site_image_de_outro_responde_404(client, dois):
    a, _ = dois
    for metodo, rota in [
        ("get", "/api/v1/site-images/salab/credentials"),
        ("get", "/api/v1/site-images/salab/boot-key"),
        ("delete", "/api/v1/site-images/salab"),
        ("post", "/api/v1/site-images/salab/token/rotate"),
    ]:
        r = client.request(metodo.upper(), rota, headers=_hs(a), json={})
        assert r.status_code == 404, f"{metodo} {rota} deu {r.status_code}"
    assert store.site_image_exists("salab")


def test_toda_rota_de_imagem_de_outro_responde_404(client, dois):
    """As rotas que passam por `require_image_access` respondiam 403 — e 403
    numa e 404 noutra é o mesmo oráculo, só que espalhado por ~26 rotas que
    este arquivo nunca visitou: config, máquinas, roster, alertas, camadas."""
    a, _ = dois
    for metodo, rota in [
        ("get", "/api/v1/site-images/salab"),
        ("get", "/api/v1/site-images/salab/config"),
        ("put", "/api/v1/site-images/salab/config"),
        ("get", "/api/v1/site-images/salab/machines"),
        ("get", "/api/v1/site-images/salab/roster"),
        ("get", "/api/v1/site-images/salab/alerts"),
        ("get", "/api/v1/site-images/salab/layers"),
        ("get", "/api/v1/site-images/salab/layerbuilds"),
        ("post", "/api/v1/site-images/salab/lock"),
    ]:
        r = client.request(metodo.upper(), rota, headers=_hs(a), json={})
        assert r.status_code == 404, f"{metodo} {rota} deu {r.status_code}"
    assert store.site_image_exists("salab")


def test_sem_credencial_e_401_exista_a_imagem_ou_nao(client, dois):
    """A dependência conferia a existência ANTES da credencial: um anônimo
    separava 404 (não existe) de 401 (existe) sem ter credencial nenhuma."""
    for rota in ("/api/v1/site-images/salab/config", "/api/v1/site-images/nao-existe/config"):
        assert client.get(rota).status_code == 401, rota


def test_nao_edita_modelo_publico_de_outro(client, base, ha):
    """Público é leitura: se pudesse editar, mexer numa trava derrubaria a
    trava de todas as sedes que usam o mesmo modelo."""
    code = _convite(client, ha)
    assert client.get("/api/v1/models/oficial", headers=_hs(code)).status_code == 200
    r = client.put(
        "/api/v1/models/oficial/schema/locks", json={"locks": {"TIMEZONE": False}}, headers=_hs(code)
    )
    assert r.status_code == 404
    r = client.post(
        "/api/v1/models/oficial/layers", json={"file": "x.squashfs", "md5": MD5}, headers=_hs(code)
    )
    assert r.status_code == 404


def test_deriva_do_modelo_publico(client, base, ha):
    code = _convite(client, ha)
    r = client.post("/api/v1/models/oficial/duplicate", json={"name": "meu"}, headers=_hs(code))
    assert r.status_code == 201, r.text
    assert [c["file"] for c in r.json()["layers"]] == ["base.squashfs"]
    assert r.json()["owner"].startswith("invite:")


def test_subadmin_nao_publica_modelo(client, base, ha):
    code = _convite(client, ha)
    r = client.post("/api/v1/models", json={"name": "meu", "public": True}, headers=_hs(code))
    assert r.status_code == 201
    assert r.json()["public"] is False
    r = client.patch("/api/v1/models/meu", json={"public": True}, headers=_hs(code))
    assert r.status_code == 403


def test_admin_ve_tudo(client, dois, ha):
    nomes = {m["name"] for m in client.get("/api/v1/models", headers=ha).json()["models"]}
    assert {"modelo-a", "modelo-b", "oficial"} <= nomes
    ids = {i["id"] for i in client.get("/api/v1/site-images", headers=ha).json()["images"]}
    assert {"salaa", "salab"} <= ids


# --- o que é só da administração ---


@pytest.mark.parametrize(
    "metodo,rota",
    [
        ("get", "/api/v1/invites"),
        ("post", "/api/v1/invites"),
        ("get", "/api/v1/requests"),
        ("get", "/api/v1/owners"),
        ("post", "/api/v1/site-images/bulk"),
    ],
)
def test_rotas_de_administracao_fechadas(client, base, ha, metodo, rota):
    code = _convite(client, ha)
    r = getattr(client, metodo)(rota, headers=_hs(code), **({} if metodo == "get" else {"json": {}}))
    assert r.status_code == 401


# --- cotas ---


def test_cota_de_modelos(client, base, ha):
    code = _convite(client, ha, max_models=1)
    assert client.post("/api/v1/models", json={"name": "um"}, headers=_hs(code)).status_code == 201
    r = client.post("/api/v1/models", json={"name": "dois"}, headers=_hs(code))
    assert r.status_code == 403
    assert "cota" in r.json()["detail"]


def test_cota_libera_ao_apagar(client, base, ha):
    """A cota conta o que existe, não o que já foi criado: contador que só
    sobe trava sem motivo depois de uma limpeza."""
    code = _convite(client, ha, max_models=1)
    client.post("/api/v1/models", json={"name": "um"}, headers=_hs(code))
    client.delete("/api/v1/models/um", headers=_hs(code))
    assert client.post("/api/v1/models", json={"name": "dois"}, headers=_hs(code)).status_code == 201


def test_admin_amplia_a_cota(client, base, ha):
    code = _convite(client, ha, max_models=1)
    oid = owners.owner_id(code)
    client.get("/api/v1/whoami", headers=_hs(code))  # registra o dono
    r = client.patch(f"/api/v1/owners/{oid}/quotas", json={"max_models": 5}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["quotas"]["models"] == 5
    assert client.post("/api/v1/models", json={"name": "dois"}, headers=_hs(code)).status_code == 201


# --- suspensão e revogação ---


def test_suspender_corta_o_acesso_sem_perder_o_dono(client, base, ha):
    code = _convite(client, ha)
    client.post("/api/v1/models", json={"name": "meu"}, headers=_hs(code))
    oid = owners.owner_id(code)

    assert client.post(f"/api/v1/owners/{oid}/disable", json={}, headers=ha).status_code == 200
    assert client.get("/api/v1/whoami", headers=_hs(code)).status_code == 401
    assert store.model_owner("meu") == oid  # o objeto continua sabendo de quem é

    client.post(f"/api/v1/owners/{oid}/disable", json={"disabled": False}, headers=ha)
    assert client.get("/api/v1/whoami", headers=_hs(code)).status_code == 200


def test_apagar_convite_em_uso_exige_force(client, base, ha):
    """Apagar o convite tira o console de quem já criou coisa; sem o aviso,
    isso aconteceria por engano na limpeza de códigos velhos."""
    code = _convite(client, ha)
    client.post("/api/v1/models", json={"name": "meu"}, headers=_hs(code))

    r = client.delete(f"/api/v1/invites/{code}", headers=ha)
    assert r.status_code == 409
    assert "meu" not in r.text or "sub-admin" in r.json()["detail"]
    assert invites.get(code) is not None

    r = client.delete(f"/api/v1/invites/{code}?force=true", headers=ha)
    assert r.status_code == 200
    assert r.json()["orphaned"]["models"] == ["meu"]
    assert client.get("/api/v1/whoami", headers=_hs(code)).status_code == 401


def test_apagar_convite_sem_uso_e_direto(client, base, ha):
    code = _convite(client, ha)
    assert client.delete(f"/api/v1/invites/{code}", headers=ha).status_code == 200


# --- auto-atendimento devolve o caminho do console ---


def test_criar_por_autoatendimento_devolve_o_console(client, base, ha):
    code = _convite(client, ha)
    r = client.post(
        "/api/v1/public/site-images",
        json={"code": code, "id": "meulab", "fullname": "Meu Lab", "model": "oficial"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["console_code"] == code
    assert corpo["console_url"].endswith("/admin/")
    # e o código NÃO fica gravado na imagem: quem tem só o token dela não pode
    # virar sub-admin
    assert "invite" not in (store.get_site_image("meulab") or {})
    assert store.site_image_owner("meulab") == owners.owner_id(code)


def test_token_da_imagem_nao_vira_console(client, base, ha):
    code = _convite(client, ha)
    criada = client.post(
        "/api/v1/public/site-images",
        json={"code": code, "id": "meulab", "fullname": "Meu Lab", "model": "oficial"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    ).json()
    r = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {criada['token']}"})
    assert r.status_code == 401


# --- caminhos de escalada que precisam continuar fechados ---


def test_nao_aponta_a_imagem_para_modelo_privado_da_casa(client, base, ha):
    """Trocar o modelo da própria imagem por um privado da administração
    entregaria as camadas dele — inclusive as de uma imagem de prova."""
    code = _convite(client, ha)
    client.post("/api/v1/models", json={"name": "privado-da-casa"}, headers=ha)
    client.post(
        "/api/v1/site-images",
        json={"id": "minhasala", "fullname": "x", "model": "oficial"},
        headers=_hs(code),
    )
    r = client.patch(
        "/api/v1/site-images/minhasala", json={"model": "privado-da-casa"}, headers=_hs(code)
    )
    assert r.status_code == 404
    assert (store.get_site_image("minhasala") or {})["model"] == "oficial"


def test_nao_destrava_a_propria_imagem_oficial(client, base, ha):
    """O perfil Oficial vem do convite. Se o dono pudesse virar a chave, todos
    os cadeados do modelo cairiam com um PATCH."""
    code = _convite(client, ha, unlocked=False)
    client.post(
        "/api/v1/site-images",
        json={"id": "minhasala", "fullname": "x", "model": "oficial", "unlocked": False},
        headers=_hs(code),
    )
    r = client.patch("/api/v1/site-images/minhasala", json={"unlocked": True}, headers=_hs(code))
    assert r.status_code == 403
    assert (store.get_site_image("minhasala") or {})["unlocked"] is False
    # e o admin muda
    assert client.patch(
        "/api/v1/site-images/minhasala", json={"unlocked": True}, headers=ha
    ).status_code == 200


def test_nao_anexa_camada_em_imagem_de_outro(client, dois):
    a, _ = dois
    r = client.post(
        "/api/v1/site-images/salab/layers",
        json={"file": "x.squashfs", "md5": MD5},
        headers=_hs(a),
    )
    assert r.status_code == 404


def test_build_de_camada_so_no_modelo_proprio(client, base, ha):
    code = _convite(client, ha)
    client.post("/api/v1/models/oficial/duplicate", json={"name": "meu"}, headers=_hs(code))
    ok = client.post(
        "/api/v1/layerbuilds", json={"name": "extras", "model": "meu", "packages": ["htop"]},
        headers=_hs(code),
    )
    assert ok.status_code == 201, ok.text
    # o modelo público é de leitura: não se constrói camada dentro dele
    r = client.post(
        "/api/v1/layerbuilds", json={"name": "extras", "model": "oficial", "packages": ["htop"]},
        headers=_hs(code),
    )
    assert r.status_code == 404


def test_cota_de_builds_do_subadmin(client, base, ha):
    code = _convite(client, ha, build_quota=1)
    client.post("/api/v1/models/oficial/duplicate", json={"name": "meu"}, headers=_hs(code))
    corpo = {"name": "extras", "model": "meu", "packages": ["htop"]}
    assert client.post("/api/v1/layerbuilds", json=corpo, headers=_hs(code)).status_code == 201
    r = client.post("/api/v1/layerbuilds", json={**corpo, "name": "outra"}, headers=_hs(code))
    assert r.status_code == 403
    assert "cota" in r.json()["detail"]


def test_nao_ve_build_de_outro(client, base, ha):
    a, b = _convite(client, ha), _convite(client, ha)
    for code, nome in ((a, "modelo-a"), (b, "modelo-b")):
        client.post("/api/v1/models/oficial/duplicate", json={"name": nome}, headers=_hs(code))
    r = client.post(
        "/api/v1/layerbuilds", json={"name": "extras", "model": "modelo-b", "packages": ["htop"]},
        headers=_hs(b),
    )
    assert r.status_code == 201, r.text
    job = r.json()
    assert client.get(f"/api/v1/layerbuilds/{job['id']}", headers=_hs(a)).status_code == 404
    assert client.get("/api/v1/layerbuilds", headers=_hs(a)).json()["builds"] == []
    assert client.get(f"/api/v1/layerbuilds/{job['id']}", headers=ha).status_code == 200
