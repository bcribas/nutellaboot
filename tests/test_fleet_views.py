"""A visão da frota: o dashboard e os laboratórios mostram o que cada um escolheu.

A administração enxerga tudo, e o painel dela virou a soma das sedes da prova
com os laboratórios de quem entrou por convite. O padrão agora é "minhas", a
seleção mora no servidor (vale em qualquer navegador e no telão), e o link
compartilhado pode segui-la.
"""

import time

import pytest

from server.app import fsdb
from server.app.services import fleet_views, invites, labs, owners, ownership, store
from server.app.services.default_schema import build_default_schema


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def frota(data_root):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    code = invites.create(max_images=5, label="Lab da Camila")[0]["code"]
    dono = owners.owner_id(code)
    owners.ensure(code)
    store.create_site_image("sala1", "Sala 1", "t")
    store.create_site_image("sala2", "Sala 2", "t")
    store.create_site_image("labcamila", "Lab da Camila", "t", owner=dono)
    labs.limpar_cache()
    return {"code": code, "dono": dono, "ref": ownership.owner_ref(dono)}


def _ids(r):
    assert r.status_code == 200, r.text
    return [s["id"] for s in r.json()["sites"]]


def test_o_padrao_da_administracao_e_minhas(client, frota, ha):
    r = client.get("/api/v1/labs", headers=ha)
    assert _ids(r) == ["sala1", "sala2"]
    meta = r.json()["view"]
    assert (meta["mode"], meta["shown"], meta["total"], meta["outside"]) == ("mine", 2, 3, 1)
    # a olhada sem salvar
    assert _ids(client.get("/api/v1/labs?view=all", headers=ha)) == ["labcamila", "sala1", "sala2"]
    assert _ids(client.get(f"/api/v1/labs?owner={frota['ref']}", headers=ha)) == ["labcamila"]
    assert client.get("/api/v1/labs/view", headers=ha).json()["view"]["mode"] == "mine", "olhar não salva"


def test_a_linha_diz_de_quem_e_a_sede_sem_entregar_o_codigo(client, frota, ha):
    r = client.get("/api/v1/labs?view=all", headers=ha)
    linha = next(s for s in r.json()["sites"] if s["id"] == "labcamila")
    assert linha["owner_kind"] == "subadmin" and linha["owner_label"] == "Lab da Camila"
    assert linha["owner_ref"] == frota["ref"]
    assert frota["code"] not in r.text
    csv = client.get("/api/v1/labs?view=all&format=csv", headers=ha).text
    assert csv.splitlines()[0].endswith(",owner_label") and "Lab da Camila" in csv


def test_gravar_a_visao_vale_para_as_tres_leituras(client, frota, ha):
    r = client.put("/api/v1/labs/view", json={"mode": "custom", "images": ["sala2", "labcamila"]}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["view"]["updated_by"] and r.json()["meta"]["shown"] == 2
    assert _ids(client.get("/api/v1/labs", headers=ha)) == ["labcamila", "sala2"]
    inv = client.get("/api/v1/labs/inventory", headers=ha)
    assert inv.status_code == 200
    assert client.get("/api/v1/labs/series", headers=ha).status_code == 200
    # por dono
    client.put("/api/v1/labs/view", json={"mode": "owners", "owners": ["admin", frota["ref"]]}, headers=ha)
    assert _ids(client.get("/api/v1/labs", headers=ha)) == ["labcamila", "sala1", "sala2"]
    donos = client.get("/api/v1/labs/view", headers=ha).json()["owners"]
    assert [(d["owner_kind"], d["images"]) for d in donos] == [("admin", 2), ("subadmin", 1)]


def test_imagem_nova_fica_fora_de_uma_selecao_feita_a_mao(client, frota, ha, data_root):
    """O laboratório novo de alguém não pode pular para o telão sozinho."""
    client.put("/api/v1/labs/view", json={"mode": "custom", "images": ["sala1"]}, headers=ha)
    arq = data_root / "fleet-views.json"
    visoes = fsdb.read_json(arq)
    visoes["admin"]["updated_at"] = int(time.time()) - 100
    fsdb.write_json(arq, visoes)
    for antiga in ("sala1", "sala2", "labcamila"):  # já existiam quando a seleção foi feita
        info = data_root / "site-images" / antiga / "image.json"
        fsdb.write_json(info, {**fsdb.read_json(info), "created_at": time.time() - 1000})
    store.create_site_image("salanova", "Sala Nova", "t")
    r = client.get("/api/v1/labs", headers=ha)
    assert _ids(r) == ["sala1"]
    assert r.json()["view"]["new_outside"] == ["salanova"]
    # em "minhas" a nova entra sozinha: é minha
    client.put("/api/v1/labs/view", json={"mode": "mine"}, headers=ha)
    assert _ids(client.get("/api/v1/labs", headers=ha)) == ["sala1", "sala2", "salanova"]


def test_apagar_a_imagem_a_tira_de_toda_selecao(client, frota, ha):
    client.put("/api/v1/labs/view", json={"mode": "custom", "images": ["sala1", "sala2"]}, headers=ha)
    assert client.delete("/api/v1/site-images/sala2", headers=ha).status_code == 204
    assert fleet_views.get("admin")["images"] == ["sala1"]


def test_validacao_e_o_que_e_de_outro_dono_nao_existe(client, frota, ha):
    hs = {"Authorization": f"Bearer {frota['code']}"}
    for corpo in ({"mode": "tudo"}, {"mode": "custom", "images": ["naoexiste"]},
                  {"mode": "owners", "owners": ["deadbeef"]}):
        assert client.put("/api/v1/labs/view", json=corpo, headers=ha).status_code == 400, corpo
    # o sub-admin vê só as dele, com qualquer visão, e não filtra por dono
    assert _ids(client.get("/api/v1/labs?view=all", headers=hs)) == ["labcamila"]
    assert client.put("/api/v1/labs/view", json={"mode": "owners", "owners": ["admin"]}, headers=hs).status_code == 400
    assert client.put("/api/v1/labs/view", json={"mode": "custom", "images": ["sala1"]}, headers=hs).status_code == 400
    assert "owners" not in client.get("/api/v1/labs/view", headers=hs).json()
    # a visão é por dono: a do sub-admin não mexe na da administração
    client.put("/api/v1/labs/view", json={"mode": "all"}, headers=hs)
    assert fleet_views.get("admin")["mode"] == "mine"


def _chave(data_root, nome, **extra):
    from server.app import auth

    chave = auth.new_key("nb3s")
    arq = data_root / "keys" / "services.json"
    conf = fsdb.read_json(arq, {}) or {}
    conf[nome] = {"sha256": auth.key_hash(chave), "scopes": ["labs:read"], "images": [], **extra}
    fsdb.write_json(arq, conf)
    return chave


def test_o_link_compartilhado_segue_a_visao_mas_o_glob_e_o_teto(client, frota, ha, data_root):
    livre = _chave(data_root, "telao-antigo")
    segue = _chave(data_root, "telao", follow="admin")
    segue_com_glob = _chave(data_root, "telao-sp", follow="admin", images=["sala*"])

    assert _ids(client.get(f"/api/v1/labs?tk={livre}")) == ["labcamila", "sala1", "sala2"], "link antigo não muda"
    assert _ids(client.get(f"/api/v1/labs?tk={segue}")) == ["sala1", "sala2"]
    client.put("/api/v1/labs/view", json={"mode": "custom", "images": ["sala2", "labcamila"]}, headers=ha)
    assert _ids(client.get(f"/api/v1/labs?tk={segue}")) == ["labcamila", "sala2"], "o telão acompanha na hora"
    assert _ids(client.get(f"/api/v1/labs?tk={segue_com_glob}")) == ["sala2"]
    # o link não se alarga sozinho, nem conta o que ficou de fora
    r = client.get(f"/api/v1/labs?tk={segue}&view=all")
    assert _ids(r) == ["labcamila", "sala2"] and r.json()["view"] == {"following": True}
    assert "owner_ref" not in r.json()["sites"][0]
    assert client.get("/api/v1/labs/view", headers={"Authorization": f"Bearer {segue}"}).status_code == 403


def test_a_frota_se_calcula_uma_vez_para_todos_os_espectadores(client, frota, ha, monkeypatch):
    """O cache era por principal: cada espectador recalculava a frota no worker
    único. Por sede, uma passada serve a todos, e o dono nunca mora no cache."""
    chamadas = []
    real = labs.resumo_de
    monkeypatch.setattr(labs, "resumo_de", lambda image_id, **kw: chamadas.append(image_id) or real(image_id, **kw))
    labs.limpar_cache()
    client.get("/api/v1/labs?view=all", headers=ha)
    client.get("/api/v1/labs", headers=ha)
    client.get("/api/v1/labs", headers={"Authorization": f"Bearer {frota['code']}"})
    assert sorted(chamadas) == ["labcamila", "sala1", "sala2"]
    assert all("owner" not in linha for _, linha in labs._cache.values())
