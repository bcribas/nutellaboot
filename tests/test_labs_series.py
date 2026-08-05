"""A série histórica da frota e a chave compartilhável do dashboard.

A série existe porque "como estava desde as 14:00" não se responde com uma
tela que acumula desde o F5; e a chave `labs:read` existe para pôr o dashboard
num telão ou numa transmissão SEM entregar comando nem hotconfig — as duas
promessas têm teste aqui.
"""

import json
import time

import pytest

from server.app import auth, fsdb
from server.app.services import labs, labs_series
from server.app.services import machines as m
from server.app.services import store
from server.app.services.default_schema import build_default_schema

DIA = 86400


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}", "X-NB-Console": "1"}


@pytest.fixture
def frota(data_root):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    store.create_site_image("sala1", "Sala 1", "t")
    store.create_site_image("dooutro", "De Outro", "t", owner="invite:NB3-AAAA-BBBB")
    labs.limpar_cache()
    return data_root


@pytest.fixture
def cliente(data_root):
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


def planta_maquina(image, mac, mem=40):
    d = m.machine_dir(image, mac)
    d.mkdir(parents=True, exist_ok=True)
    fsdb.write_json(d / "machine.json", {"mac": mac, "first_seen": 1, "last_seen": time.time()})
    fsdb.write_json(d / "status.json", {
        "hwinfo": {"cores": 4, "memtotal_mb": 8000, "processor": "Intel i5"},
        "sysresources": {"mem_pct": mem, "loadavg": [1.0, 0, 0]},
    })


# --- o gravador e a janela ----------------------------------------------------


def test_o_ponto_gravado_tem_as_sedes(frota):
    planta_maquina("sala1", "52-54-00-00-00-01", mem=50)
    labs.limpar_cache()
    ponto = labs_series.gravar_ponto()
    assert "sala1" in ponto["sites"]
    online, mem, cpu, alerts = ponto["sites"]["sala1"]
    assert online == 1 and mem == 50
    linhas = labs_series._path().read_text().strip().splitlines()
    assert json.loads(linhas[-1])["t"] == ponto["t"]


def test_a_janela_recorta_e_o_downsample_tem_teto(frota, admin_key):
    agora = time.time()
    for i in range(1000):
        fsdb  # noqa: B018
        labs_series.append_capped(
            labs_series._path(),
            json.dumps({"t": int(agora - 1000 + i), "sites": {"sala1": [1, 40, 20, 0]}}),
            cap=labs_series.CAP,
        )
    p = auth.Principal("admin", "test")
    pontos = labs_series.serie(p, since=agora - 500)
    assert len(pontos) <= labs_series.MAX_PONTOS
    assert all(x["t"] >= agora - 501 for x in pontos)
    # o mais recente sobrevive ao downsample? o último ponto amostrado é
    # próximo do fim da janela
    assert pontos[-1]["t"] >= agora - 10


def test_o_total_e_recalculado_da_visibilidade(frota):
    """Sub-admin não pode deduzir a contagem alheia pelo total da frota."""
    agora = int(time.time())
    labs_series.append_capped(
        labs_series._path(),
        json.dumps({"t": agora, "sites": {"sala1": [3, 40, 20, 1], "dooutro": [5, 90, 80, 2]}}),
        cap=labs_series.CAP,
    )
    p_sub = auth.Principal(kind="subadmin", name="invite:NB3-AAAA-BBBB")
    pontos = labs_series.serie(p_sub)
    assert pontos[0]["online"] == 5, "só a sede dele"
    assert pontos[0]["mem"] == 90
    assert pontos[0]["alerts"] == 2

    p_admin = auth.Principal("admin", "test")
    assert labs_series.serie(p_admin)[0]["online"] == 8


def test_o_ponto_leva_os_editores_por_sede(frota):
    """O 5º elemento é opcional e POR SEDE — gravado por sede justamente para
    o recorte de visibilidade poder somar só o que cada um pode ver."""
    planta_maquina("sala1", "52-54-00-00-00-01")
    d = m.machine_dir("sala1", "52-54-00-00-00-01")
    st = fsdb.read_json(d / "status.json", {})
    st["operations"] = {"editors": ["code", "vim"]}
    fsdb.write_json(d / "status.json", st)
    labs.limpar_cache()
    ponto = labs_series.gravar_ponto()
    assert ponto["sites"]["sala1"][4] == {"code": 1, "vim": 1}
    # sede sem editor não paga o campo
    assert len(ponto["sites"]["dooutro"]) == 4


def test_a_serie_soma_editores_so_das_sedes_visiveis(frota):
    agora = int(time.time())
    # um ponto antigo (4 elementos, de antes dos editores) no meio: não quebra
    labs_series.append_capped(
        labs_series._path(),
        json.dumps({"t": agora - 60, "sites": {"sala1": [1, 40, 20, 0]}}),
        cap=labs_series.CAP,
    )
    labs_series.append_capped(
        labs_series._path(),
        json.dumps({"t": agora, "sites": {
            "sala1": [3, 40, 20, 0, {"code": 2, "vim": 1}],
            "dooutro": [5, 90, 80, 0, {"code": 4, "emacs": 2}],
        }}),
        cap=labs_series.CAP,
    )
    p_admin = auth.Principal("admin", "test")
    pontos = labs_series.serie(p_admin)
    assert "ed" not in pontos[0], "ponto antigo segue valendo, sem inventar zero"
    assert pontos[1]["ed"] == {"code": 6, "vim": 1, "emacs": 2}

    p_sub = auth.Principal(kind="subadmin", name="invite:NB3-AAAA-BBBB")
    assert labs_series.serie(p_sub)[1]["ed"] == {"code": 4, "emacs": 2}, "só a sede dele"

    # e o modo de UMA sede também entrega
    pontos = labs_series.serie(p_admin, site="sala1")
    assert pontos[1]["ed"] == {"code": 2, "vim": 1}


def test_site_de_outro_dono_e_404(cliente, frota, ha, admin_key):
    labs_series.append_capped(
        labs_series._path(),
        json.dumps({"t": int(time.time()), "sites": {"sala1": [1, 1, 1, 0]}}),
        cap=labs_series.CAP,
    )
    fsdb.write_json(frota / "invites.json", {})
    # cria um convite de verdade para ter credencial de sub-admin
    code = cliente.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    hs = {"Authorization": f"Bearer {code}", "X-NB-Console": "1"}
    r = cliente.get("/api/v1/labs/series?site=sala1", headers=hs)
    assert r.status_code == 404


# --- a chave compartilhável ---------------------------------------------------


@pytest.fixture
def chave_dash(cliente, ha):
    r = cliente.post(
        "/api/v1/service-keys",
        json={"name": "telao", "scopes": ["labs:read"], "images": []},
        headers=ha,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["key"]


def test_a_chave_le_as_tres_rotas(cliente, frota, ha, chave_dash):
    planta_maquina("sala1", "52-54-00-00-00-01")
    labs.limpar_cache()
    labs.limpar_cache_inventario()
    # por Bearer
    hb = {"Authorization": f"Bearer {chave_dash}"}
    assert cliente.get("/api/v1/labs", headers=hb).status_code == 200
    assert cliente.get("/api/v1/labs/inventory", headers=hb).status_code == 200
    assert cliente.get("/api/v1/labs/series", headers=hb).status_code == 200
    # por ?tk= (o jeito da URL compartilhada)
    assert cliente.get(f"/api/v1/labs?tk={chave_dash}").status_code == 200
    assert cliente.get(f"/api/v1/labs/inventory?tk={chave_dash}").status_code == 200
    assert cliente.get(f"/api/v1/labs/series?tk={chave_dash}").status_code == 200


def test_a_chave_nao_abre_hotconfig_nem_comanda(cliente, frota, ha, chave_dash):
    """As duas promessas do compartilhamento. O hotconfig vive de
    GET /machines (exige machines:read → 403) e comandos exigem console
    (serviço → 401)."""
    hb = {"Authorization": f"Bearer {chave_dash}"}
    r = cliente.get("/api/v1/site-images/sala1/machines", headers=hb)
    assert r.status_code == 403
    r = cliente.post(
        "/api/v1/site-images/sala1/commands",
        json={"command": "mlreboot", "target": "all"},
        headers={**hb, "X-NB-Console": "1"},
    )
    assert r.status_code == 403
    r = cliente.post(
        "/api/v1/commands",
        json={"command": "mlreboot", "targets": {"sala1": "all"}},
        headers={**hb, "X-NB-Console": "1"},
    )
    assert r.status_code == 401


def test_servico_sem_o_escopo_nao_le_a_frota(cliente, frota, ha):
    r = cliente.post(
        "/api/v1/service-keys",
        json={"name": "moj", "scopes": ["machines:read"], "images": []},
        headers=ha,
    )
    chave = r.json()["key"]
    assert cliente.get(f"/api/v1/labs?tk={chave}").status_code == 401


def test_o_glob_da_chave_limita_as_sedes(cliente, frota, ha):
    r = cliente.post(
        "/api/v1/service-keys",
        json={"name": "parcial", "scopes": ["labs:read"], "images": ["sala*"]},
        headers=ha,
    )
    chave = r.json()["key"]
    labs.limpar_cache()
    d = cliente.get(f"/api/v1/labs?tk={chave}").json()
    assert [s["id"] for s in d["sites"]] == ["sala1"], "o glob filtra; dooutro não aparece"
