"""Roster e vínculo sem tudo-ou-nada (achado 12 do relatório do MOJ).

O roster só tinha o PUT da lista inteira e o vínculo dava 404 quando o time não
estava nele. Em 21/09 o roster estava vazio em todas as imagens, inclusive na
do evento da semana: todo vínculo publicado no login voltava 404.
"""

import threading

import pytest

from server.app import fsdb
from server.app.services import roster as ros
from server.app.services import store

BASE = "/api/v1/site-images/testes3"
M1, M2, M3 = "52-54-00-00-00-01", "52-54-00-00-00-02", "52-54-00-00-00-03"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


@pytest.fixture
def hi(img):
    return {"Authorization": f"Bearer {img['token']}"}


def _ids(client, hi):
    return [e["user_id"] for e in client.get(f"{BASE}/roster", headers=hi).json()["roster"]]


def test_post_acrescenta_e_atualiza_um_time(client, img, hi):
    r = client.post(f"{BASE}/roster", json={"user_id": "t1", "name": "Um", "country": "br"}, headers=hi)
    assert r.status_code == 200 and r.json()["created"] and r.json()["entry"]["country"] == "BR"
    client.post(f"{BASE}/roster", json={"user_id": "t2", "name": "Dois"}, headers=hi)
    r = client.post(f"{BASE}/roster", json={"user_id": "t1", "name": "Um, de novo"}, headers=hi)
    assert not r.json()["created"]
    roster = client.get(f"{BASE}/roster", headers=hi).json()["roster"]
    assert [(e["user_id"], e["name"]) for e in roster] == [("t1", "Um, de novo"), ("t2", "Dois")]
    r = client.post(f"{BASE}/roster", json={"name": "sem id"}, headers=hi)
    assert r.status_code == 400 and r.json()["code"] == "invalid_roster_entry"


def test_delete_tira_um_time_e_nao_desfaz_o_vinculo(client, img, hi):
    client.post(f"{BASE}/roster", json={"user_id": "t1", "name": "Um"}, headers=hi)
    client.put(f"{BASE}/machines/{M1}/binding", json={"user_id": "t1"}, headers=hi)
    assert client.delete(f"{BASE}/roster/t1", headers=hi).status_code == 204
    assert _ids(client, hi) == []
    assert (store.site_image_dir("testes3") / "machines" / M1 / "binding.json").is_file()
    r = client.delete(f"{BASE}/roster/t1", headers=hi)
    assert r.status_code == 404 and r.json()["code"] == "user_not_in_roster"


def test_escritas_simultaneas_nao_se_atropelam(img):
    """Era ler-modificar-gravar sem lock: a tela e o MOJ perdiam o time um do
    outro."""
    erros = []

    def escreve(i):
        try:
            ros.upsert("testes3", {"user_id": f"t{i:02d}", "name": f"Time {i}"})
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    fios = [threading.Thread(target=escreve, args=(i,)) for i in range(24)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()
    assert not erros
    assert sorted(e["user_id"] for e in ros.ler("testes3")) == [f"t{i:02d}" for i in range(24)]


def test_vinculo_cria_a_entrada_so_quando_pedido(client, img, hi):
    r = client.put(f"{BASE}/machines/{M1}/binding", json={"user_id": "teambr01"}, headers=hi)
    assert r.status_code == 404 and r.json()["code"] == "user_not_in_roster"

    corpo = {"user_id": "teambr01", "source": "moj-login", "at": 1788026460,
             "create_roster_entry": {"name": "Os Batatinhas", "display_name": "[UFU] Os Batatinhas",
                                     "organization": {"name": "UFU"}, "country": "BR"}}
    r = client.put(f"{BASE}/machines/{M1}/binding", json=corpo, headers=hi)
    assert r.status_code == 200, r.text
    assert r.json()["roster_entry_created"] is True and r.json()["user_id"] == "teambr01"
    entrada = client.get(f"{BASE}/roster", headers=hi).json()["roster"][0]
    assert entrada["name"] == "Os Batatinhas" and entrada["source"] == "binding"
    # e a tela de bloqueio já mostra o time
    from server.app.routers import roster as rota

    assert rota.lockinfo("testes3", M1)["team"]["name"] == "Os Batatinhas"

    # de novo: não recria nem avisa que criou
    r = client.put(f"{BASE}/machines/{M1}/binding", json=corpo, headers=hi)
    assert "roster_entry_created" not in r.json()
    # `true`: os campos do time vêm do próprio corpo
    r = client.put(f"{BASE}/machines/{M2}/binding",
                   json={"user_id": "teambr02", "name": "Dois", "create_roster_entry": True}, headers=hi)
    assert r.json()["roster_entry_created"] is True
    assert ros.achar(ros.ler("testes3"), "teambr02")["name"] == "Dois"


def test_roster_oficial_sobrescreve_mas_nunca_apaga_vinculo(client, img, hi):
    for mac, uid in ((M1, "a"), (M2, "b")):
        client.put(f"{BASE}/machines/{mac}/binding",
                   json={"user_id": uid, "name": f"provisório {uid}", "create_roster_entry": True}, headers=hi)
    # o oficial traz `a` (sobrescreve, perde a marca) e um novo `c`; omite `b`, que está vinculado
    r = client.put(f"{BASE}/roster", json={"roster": [{"user_id": "a", "name": "Oficial A"},
                                                      {"user_id": "c", "name": "Oficial C"}]}, headers=hi)
    assert r.status_code == 200 and r.json() == {"ok": True, "entries": 2, "kept_bound": ["b"]}
    roster = {e["user_id"]: e for e in client.get(f"{BASE}/roster", headers=hi).json()["roster"]}
    assert roster["a"]["name"] == "Oficial A" and "source" not in roster["a"]
    assert roster["b"]["source"] == "binding" and roster["b"]["name"] == "provisório b"
    assert "source" not in roster["c"]
    vinculos = {b["mac"]: b["user_id"] for b in client.get(f"{BASE}/bindings", headers=hi).json()["bindings"]}
    assert vinculos == {}  # /bindings lista máquinas CONHECIDAS; os arquivos é que contam:
    for mac in (M1, M2):
        assert (store.site_image_dir("testes3") / "machines" / mac / "binding.json").is_file()


def test_lote_de_vinculos_com_resultado_por_item(client, img, hi, monkeypatch):
    from server.app.services import webhook_push

    eventos = []
    monkeypatch.setattr(webhook_push, "emit", lambda image, event, data: eventos.append((event, data["mac"])))
    client.post(f"{BASE}/roster", json={"user_id": "t1", "name": "Um"}, headers=hi)
    corpo = {
        "create_roster_entry": True,
        "bindings": [
            {"mac": M1, "user_id": "t1", "source": "moj-replay", "at": 1788026460},
            {"mac": M2, "user_id": "t2", "name": "Dois"},                    # cria a entrada
            {"mac": "zz", "user_id": "t1"},                                   # MAC ruim
            {"mac": M3, "user_id": "t3", "create_roster_entry": False},       # o item desliga a opção
        ],
    }
    r = client.put(f"{BASE}/bindings", json=corpo, headers=hi)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["bound"], d["failed"]) == (2, 2)
    assert [(x["mac"], x["ok"], x.get("code")) for x in d["results"]] == [
        (M1, True, None), (M2, True, None), ("zz", False, "invalid_mac"), (M3, False, "user_not_in_roster"),
    ]
    assert d["results"][0]["binding"]["client_at"] == 1788026460
    assert sorted(_ids(client, hi)) == ["t1", "t2"]
    # a rota é `def` (threadpool): o evento tem de sair mesmo assim, um por vínculo
    assert eventos == [("machine.bound", M1), ("machine.bound", M2)]

    r = client.put(f"{BASE}/bindings", json={"bindings": [{}] * 1001}, headers=hi)
    assert r.status_code == 413


def test_escopos_das_rotas_novas(client, img, admin_key):
    ha = {"Authorization": f"Bearer {admin_key}"}

    def chave(nome, scopes, images=()):
        r = client.post("/api/v1/service-keys", json={"name": nome, "scopes": scopes, "images": list(images)}, headers=ha)
        return {"Authorization": f"Bearer {r.json()['key']}"}

    so_leitura = chave("leitor", ["roster:read", "machines:read"])
    assert client.post(f"{BASE}/roster", json={"user_id": "x"}, headers=so_leitura).json()["code"] == "insufficient_scope"
    assert client.delete(f"{BASE}/roster/x", headers=so_leitura).json()["code"] == "insufficient_scope"
    assert client.put(f"{BASE}/bindings", json={"bindings": []}, headers=so_leitura).json()["code"] == "insufficient_scope"
    fora = chave("fora", ["roster:write", "bindings:write"], ["outra*"])
    assert client.post(f"{BASE}/roster", json={"user_id": "x"}, headers=fora).json()["code"] == "image_out_of_scope"
    moj = chave("moj", ["roster:write", "bindings:write"])
    assert client.post(f"{BASE}/roster", json={"user_id": "x"}, headers=moj).status_code == 200
    assert client.put(f"{BASE}/bindings", json={"bindings": [{"mac": M1, "user_id": "x"}]}, headers=moj).json()["bound"] == 1


def test_logotipo_para_a_tela(client, img, hi):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = client.put(f"{BASE}/roster/logos/ufu", files={"file": ("ufu.svg", svg, "image/svg+xml")}, headers=hi)
    assert r.status_code == 200, r.text
    assert client.get(f"{BASE}/roster", headers=hi).json()["logos"] == ["ufu"]

    r = client.get(f"{BASE}/roster/logos/ufu?tk={img['token']}")
    assert r.status_code == 200 and r.content == svg
    # SVG é de quem tem o token da sede: aberto direto na aba do admin, não roda script
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"

    assert client.get(f"{BASE}/roster/logos/ufu").status_code == 401
    assert client.get(f"{BASE}/roster/logos/naotem?tk={img['token']}").status_code == 404
