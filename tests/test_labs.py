"""O painel da frota: o resumo por sede e o comando que atravessa sedes.

Duas coisas que este arquivo protege, e as duas doem calado:

  * **quem vê o quê.** O resumo é cacheado, e cache indexado só pela janela
    serviria a um sub-admin a contagem das sedes de outra pessoa — um vazamento
    que nenhum teste de rota pegaria, porque a rota está certa;
  * **uma sede recusada não pode parar as outras.** Comandar 54 sedes de uma
    vez com metade falhando em silêncio é meia frota comandada sem ninguém
    saber quais.
"""

import time

import pytest

from server.app import fsdb
from server.app.services import labs
from server.app.services import machines as m
from server.app.services import store
from server.app.services.default_schema import build_default_schema

DIA = 86400


@pytest.fixture(autouse=True)
def sem_cache():
    labs.limpar_cache()
    yield
    labs.limpar_cache()


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}", "X-NB-Console": "1"}


@pytest.fixture
def frota(data_root):
    """Duas sedes da administração e uma de um convite, com máquinas plantadas
    em datas escolhidas."""
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    store.create_site_image("sala1", "Sala 1", "t")
    store.create_site_image("sala2", "Sala 2", "t")
    store.create_site_image("dooutro", "De Outro", "t", owner="invite:NB3-AAAA-BBBB")
    return data_root


def planta(image, mac, *, visto_ha, apareceu_ha=None, locked=False, alertas=0, time_=None):
    agora = time.time()
    d = m.machine_dir(image, mac)
    d.mkdir(parents=True, exist_ok=True)
    fsdb.write_json(
        d / "machine.json",
        {
            "mac": mac,
            "first_seen": agora - (apareceu_ha if apareceu_ha is not None else visto_ha),
            "last_seen": agora - visto_ha,
        },
    )
    fsdb.write_json(d / "status.json", {})
    if locked:
        fsdb.write_json(d / "lockstate.json", {"locked": True})
    if alertas:
        fsdb.write_json(d / "alerts.json", [{"id": f"a{i}"} for i in range(alertas)])
    if time_:
        fsdb.write_json(d / "binding.json", {"user_id": time_})


# --- o resumo ---------------------------------------------------------------


def test_o_resumo_conta_o_estado_de_agora(client, frota, ha):
    planta("sala1", "52-54-00-00-00-01", visto_ha=5, time_="team-1")
    planta("sala1", "52-54-00-00-00-02", visto_ha=5, locked=True, alertas=2)
    planta("sala1", "52-54-00-00-00-03", visto_ha=3600)  # offline

    r = client.get("/api/v1/labs", headers=ha)
    assert r.status_code == 200, r.text
    linha = {s["id"]: s for s in r.json()["sites"]}["sala1"]
    assert linha["machines"] == 3
    assert linha["online"] == 2
    assert linha["locked"] == 1
    assert linha["alerts"] == 2
    assert linha["unbound"] == 2


def test_quantas_rodaram_nos_ultimos_x_dias(client, frota, ha):
    """A pergunta tem duas leituras e as duas são úteis: `active` é quem teve
    contato na janela, `new` é quem apareceu nela."""
    planta("sala1", "52-54-00-00-00-01", visto_ha=2 * DIA, apareceu_ha=40 * DIA)
    planta("sala1", "52-54-00-00-00-02", visto_ha=1 * DIA, apareceu_ha=1 * DIA)
    planta("sala1", "52-54-00-00-00-03", visto_ha=40 * DIA, apareceu_ha=40 * DIA)

    def conta(dias):
        labs.limpar_cache()
        s = {x["id"]: x for x in client.get(f"/api/v1/labs?dias={dias}", headers=ha).json()["sites"]}
        return s["sala1"]["active"], s["sala1"]["new"]

    assert conta(1) == (0, 0), "nada teve contato dentro de 1 dia"
    # a de 40 dias que reportou anteontem é ATIVA e não é NOVA
    assert conta(7) == (2, 1)
    assert conta(60) == (3, 3)


def test_o_resumo_traz_a_lista_de_alertas(client, frota, ha):
    """O painel dizia "3 alertas" sem conseguir dizer QUAIS — o arquivo sempre
    foi lido inteiro e só o len() era aproveitado. A lista sai com teto
    (ALERTAS_NA_LINHA) e a contagem continua sendo o TOTAL."""
    import time as _t

    planta("sala1", "52-54-00-00-00-01", visto_ha=5, alertas=0)
    d = m.machine_dir("sala1", "52-54-00-00-00-01")
    fsdb.write_json(d / "alerts.json", [
        {"id": "a1", "kind": "usb.storage", "detail": "Cruzer 16GB",
         "vendor": "SanDisk", "at": _t.time() - 60},
        {"id": "a2", "kind": "usb.phone", "detail": "Galaxy", "at": _t.time() - 10},
    ])
    fsdb.write_json(d / "binding.json", {"user_id": "t1", "name": "Time 01"})
    labs.limpar_cache()

    linha = next(s for s in client.get("/api/v1/labs", headers=ha).json()["sites"]
                 if s["id"] == "sala1")
    assert linha["alerts"] == 2
    lista = linha["alert_list"]
    assert [a["kind"] for a in lista] == ["usb.phone", "usb.storage"], "mais recente primeiro"
    assert lista[1]["vendor"] == "SanDisk"
    assert lista[0]["team"] == "Time 01"
    assert lista[0]["mac"] == "52-54-00-00-00-01"


def test_a_lista_de_alertas_tem_teto_mas_a_conta_nao(client, frota, ha):
    planta("sala1", "52-54-00-00-00-01", visto_ha=5)
    d = m.machine_dir("sala1", "52-54-00-00-00-01")
    fsdb.write_json(d / "alerts.json", [{"id": f"a{i}", "at": i} for i in range(40)])
    labs.limpar_cache()
    linha = next(s for s in client.get("/api/v1/labs", headers=ha).json()["sites"]
                 if s["id"] == "sala1")
    assert linha["alerts"] == 40
    assert len(linha["alert_list"]) == labs.ALERTAS_NA_LINHA


def test_o_csv_traz_as_mesmas_contas(client, frota, ha):
    planta("sala1", "52-54-00-00-00-01", visto_ha=2 * DIA, apareceu_ha=40 * DIA)
    labs.limpar_cache()
    linhas = {s["id"]: s for s in client.get("/api/v1/labs?dias=7", headers=ha).json()["sites"]}
    labs.limpar_cache()
    csv = client.get("/api/v1/labs?dias=7&format=csv", headers=ha)
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    corpo = {l.split(",")[0]: l.split(",") for l in csv.text.strip().splitlines()[1:]}
    assert corpo["sala1"][3] == str(linhas["sala1"]["active"])
    assert corpo["sala1"][4] == str(linhas["sala1"]["new"])


def test_a_administracao_ve_tudo_e_o_convidado_so_o_dele(client, frota, ha, data_root):
    from server.app import auth

    ids = {s["id"] for s in client.get("/api/v1/labs", headers=ha).json()["sites"]}
    assert ids == {"sala1", "sala2", "dooutro"}

    labs.limpar_cache()
    p = auth.Principal(kind="subadmin", name="invite:NB3-AAAA-BBBB")
    assert [s["id"] for s in labs.resumo(p)] == ["dooutro"]


def test_o_cache_nao_serve_a_conta_de_outro_dono(client, frota, ha):
    """Cache indexado só pela janela entregaria ao sub-admin a contagem das
    sedes da administração — e nenhum teste de rota pegaria, porque a rota
    está certa."""
    from server.app import auth

    admin = auth.Principal(kind="admin", name="adm")
    outro = auth.Principal(kind="subadmin", name="invite:NB3-AAAA-BBBB")

    primeiro = [s["id"] for s in labs.resumo(admin)]
    segundo = [s["id"] for s in labs.resumo(outro)]
    assert len(primeiro) == 3
    assert segundo == ["dooutro"], segundo


def test_o_resumo_nao_carrega_o_status_das_maquinas(client, frota, ha):
    """O `status.json` é livre e pode ter 256 kB. Numa frota de 1890 máquinas,
    devolvê-lo seria quase 1 MB por atualização — a razão de esta rota existir
    separada da de sede."""
    planta("sala1", "52-54-00-00-00-01", visto_ha=5)
    fsdb.write_json(
        m.machine_dir("sala1", "52-54-00-00-00-01") / "status.json",
        {"hwinfo": {"lixo": "x" * 5000}},
    )
    texto = client.get("/api/v1/labs", headers=ha).text
    assert "lixo" not in texto
    assert len(texto) < 2000, len(texto)


def test_sem_credencial_de_console_nao_ha_frota(client, frota):
    assert client.get("/api/v1/labs").status_code == 401


# --- o comando que atravessa sedes ------------------------------------------


def _manda(client, ha, **corpo):
    return client.post("/api/v1/commands", json=corpo, headers=ha)


def test_comanda_varias_sedes_de_uma_vez(client, frota, ha):
    planta("sala1", "52-54-00-00-00-01", visto_ha=5)
    planta("sala1", "52-54-00-00-00-02", visto_ha=5)
    planta("sala2", "52-54-00-00-01-01", visto_ha=5)

    r = _manda(
        client, ha,
        command="resetcontaeditores",
        targets={"sala1": "all", "sala2": ["52-54-00-00-01-01"]},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["machines"] == 3
    assert d["failed"] == []
    assert len(m.pending_commands("sala1", "52-54-00-00-00-01")) == 1
    assert len(m.pending_commands("sala2", "52-54-00-00-01-01")) == 1


def test_uma_sede_recusada_nao_para_as_outras(client, frota, ha):
    planta("sala1", "52-54-00-00-00-01", visto_ha=5)
    r = _manda(client, ha, command="resetcontaeditores",
               targets={"sala1": "all", "naoexiste": "all"})
    d = r.json()
    assert d["results"]["sala1"]["machines"] == 1
    assert d["results"]["naoexiste"]["status"] == 404
    assert d["failed"] == ["naoexiste"]


def test_precontest_pela_frota_tambem_grava_a_trava(client, frota, ha):
    """A mesma regra da rota por sede: sem o lockstate no servidor, a trava do
    precontest cai no ciclo seguinte do long-poll."""
    planta("sala1", "52-54-00-00-00-01", visto_ha=5)
    planta("sala2", "52-54-00-00-01-01", visto_ha=5)
    r = _manda(client, ha, command="precontest",
               targets={"sala1": "all"})
    assert r.status_code == 200, r.text
    assert m.get_lock("sala1", "52-54-00-00-00-01")["locked"] is True
    assert m.get_lock("sala2", "52-54-00-00-01-01")["locked"] is False


def test_o_cadeado_do_modelo_vale_aqui_tambem(client, frota, ha, data_root):
    """A mesma regra do painel por sede: reimplementá-la seria a porta ficando
    diferente de novo."""
    from server.app import auth

    planta("sala1", "52-54-00-00-00-01", visto_ha=5)
    planta("dooutro", "52-54-00-00-02-01", visto_ha=5)
    # o dono do convite manda nas sedes DELE, com o campo travado no modelo
    p = auth.Principal(kind="subadmin", name="invite:NB3-AAAA-BBBB")
    from server.app.routers.machines import comandos_bloqueados

    assert comandos_bloqueados("dooutro", is_admin=False) == {
        "disablefirewall": "DISABLE_FIREWALL"
    }
    assert comandos_bloqueados("dooutro", is_admin=True) == {}


def test_o_dono_do_convite_nao_comanda_sede_alheia(client, frota, data_root):
    """404, não 403: um 403 confirmaria que o nome existe."""
    from server.app.services import invites

    fsdb.write_json(
        data_root / "invites.json",
        {"NB3-AAAA-BBBB": {"max_images": 5, "used_images": ["dooutro"], "label": "x"}},
    )
    assert invites.is_valid("NB3-AAAA-BBBB")[0]
    hc = {"Authorization": "Bearer NB3-AAAA-BBBB", "X-NB-Console": "1"}
    planta("sala1", "52-54-00-00-00-01", visto_ha=5)

    r = client.post(
        "/api/v1/commands",
        json={"command": "resetcontaeditores", "targets": {"sala1": "all"}},
        headers=hc,
    )
    assert r.status_code == 200, r.text
    assert r.json()["results"]["sala1"]["status"] == 404


def test_comando_desconhecido_e_recusado(client, frota, ha):
    assert _manda(client, ha, command="rm -rf", targets={"sala1": "all"}).status_code == 400
    assert _manda(client, ha, command="mlreboot", targets={}).status_code == 400


# --- a credencial de um LINK -------------------------------------------------
#
# O botão de baixar o CSV é um `<a download>`, e um `<a>` não manda cabeçalho.
# Como o cookie de sessão só vale com `X-NB-Console` (a barreira anti-CSRF), o
# clique dava 401 na cara de quem usava. É a mesma exceção da prévia do
# wallpaper, do SSE e do relatório por sede — e ela vale SÓ para leitura.


@pytest.fixture
def navegador(data_root, admin_key):
    """Cliente em HTTPS com sessão aberta — o cookie é `Secure`, e sobre http o
    próprio httpx não o guarda (como o navegador não guardaria)."""
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    c = TestClient(create_app(), base_url="https://testserver")
    r = c.post("/api/v1/session", json={"key": admin_key}, headers={"X-NB-Console": "1"})
    assert r.status_code == 200, r.text
    return c


def test_o_csv_abre_com_o_cookie_sem_o_cabecalho(navegador, frota):
    """Exatamente o que o navegador faz ao clicar no `<a download>`."""
    r = navegador.get("/api/v1/labs?dias=7&format=csv")
    assert r.status_code == 200, r.text
    assert r.text.startswith("id,fullname,")


def test_o_resumo_tambem(navegador, frota):
    assert navegador.get("/api/v1/labs?dias=7").status_code == 200


def test_mas_comandar_continua_exigindo_o_cabecalho(navegador, frota):
    """A assimetria é o ponto: ler a frota por link é inócuo; DESLIGÁ-LA não.
    "Relaxei o GET, relaxo o POST também" é o passo seguinte natural e errado —
    um `<form>` de outro site manda o cookie, e sem esta linha desligaria 1900
    máquinas."""
    corpo = {"command": "mlpoweroff", "targets": {"sala1": "all"}}
    assert navegador.post("/api/v1/commands", json=corpo).status_code == 401
    assert (
        navegador.post("/api/v1/commands", json=corpo, headers={"X-NB-Console": "1"}).status_code
        == 200
    )


def test_sem_sessao_nenhuma_das_duas_abre(client, frota):
    assert client.get("/api/v1/labs?format=csv").status_code == 401
    assert client.post("/api/v1/commands", json={"command": "mlreboot", "targets": {}}).status_code == 401
