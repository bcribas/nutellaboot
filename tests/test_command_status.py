"""Comando rastreável: quem executou, por `command_id`.

`POST …/commands` devolvia `{command_id, machines}` e o resto se perdia: o MOJ
(e o operador) nunca sabiam quem tinha executado.
"""

import pytest

from server.app import fsdb
from server.app.services import command_log
from server.app.services import machines as m

BASE = "/api/v1/site-images/testes3"
M1, M2, M3 = "52-54-00-00-00-01", "52-54-00-00-00-02", "52-54-00-00-00-03"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


@pytest.fixture
def hm(img):
    return {"X-NB-Machine-Key": img["machine_key"]}


@pytest.fixture
def hi(img):
    return {"Authorization": f"Bearer {img['token']}"}


def _sala(client, hm):
    for mac in (M1, M2, M3):
        client.post(f"{BASE}/machines/{mac}/status", json={}, headers=hm)


def test_do_envio_a_confirmacao_e_a_expiracao(client, img, hm, hi, monkeypatch):
    _sala(client, hm)
    cid = client.post(f"{BASE}/commands", json={"command": "mlreboot", "target": "all"}, headers=hi).json()["command_id"]

    e = client.get(f"{BASE}/commands/{cid}", headers=hi).json()
    assert e["command"] == "mlreboot" and e["machines"] == 3
    assert e["summary"] == {"acked": 0, "pending": 3, "expired": 0}
    assert e["expires_at"] == e["not_before"] + 600 and isinstance(e["created_at"], int)

    client.post(f"{BASE}/machines/{M1}/commands/{cid}/ack", json={"status": "done", "output": "ok!"}, headers=hm)
    client.post(f"{BASE}/machines/{M2}/commands/{cid}/ack", json={"status": "error"}, headers=hm)
    e = client.get(f"{BASE}/commands/{cid}", headers=hi).json()
    por_mac = {t["mac"]: t for t in e["targets"]}
    assert por_mac[M1]["state"] == "acked" and por_mac[M1]["status"] == "done" and por_mac[M1]["output_bytes"] == 3
    assert por_mac[M2]["status"] == "error", "confirmou que falhou: é acked, com o status que veio"
    assert por_mac[M3] == {"mac": M3, "state": "pending"}

    # a máquina desligada nunca escreve nada: o estado dela se deduz do prazo
    depois = command_log.estado("testes3", cid, agora=e["expires_at"] + 1)
    assert depois["summary"] == {"acked": 2, "pending": 0, "expired": 1}


def test_a_expiracao_da_fila_fica_no_registro(client, img, hm, hi, monkeypatch):
    _sala(client, hm)
    cid = client.post(f"{BASE}/commands", json={"command": "mlreboot", "target": [M1]}, headers=hi).json()["command_id"]
    monkeypatch.setattr(m, "_command_ttl", lambda: 0)
    assert m.pending_commands("testes3", M1) == []  # a leitura poda o que caducou
    alvo = client.get(f"{BASE}/commands/{cid}", headers=hi).json()["targets"][0]
    assert alvo["state"] == "expired" and isinstance(alvo["at"], int)


def test_o_evento_do_ack_diz_de_qual_comando(client, img, hm, hi, monkeypatch):
    from server.app.services import webhook_push

    vistos = []
    monkeypatch.setattr(webhook_push, "emit", lambda image, event, data: vistos.append((event, data)))
    _sala(client, hm)
    cid = client.post(f"{BASE}/commands", json={"command": "cleanhomenow", "target": [M1]}, headers=hi).json()["command_id"]
    client.post(f"{BASE}/machines/{M1}/commands/{cid}/ack", json={"status": "done"}, headers=hm)
    dados = next(d for ev, d in vistos if ev == "command.acked")
    assert dados == {"mac": M1, "id": cid, "command_id": cid, "status": "done", "command": "cleanhomenow"}


def test_trava_da_sala_tambem_e_rastreada(client, img, hm, hi):
    _sala(client, hm)
    cid = client.post(f"{BASE}/lock", headers=hi).json()["command_id"]
    e = client.get(f"{BASE}/commands/{cid}", headers=hi).json()
    assert e["command"] == "donottouch" and e["machines"] == 3


def test_cid_inventado_nao_cria_arquivo_nem_atravessa_diretorio(client, img, hm, hi, data_root):
    _sala(client, hm)
    for cid in ("naoexiste123", "../../../etc", "0" * 12):
        r = client.get(f"{BASE}/commands/{cid}", headers=hi)
        assert r.status_code == 404, cid
    client.post(f"{BASE}/machines/{M1}/commands/{'a' * 12}/ack", json={"status": "done"}, headers=hm)
    d = data_root / "site-images" / "testes3" / "commands"
    assert not d.is_dir() or not list(d.glob("a*"))


def test_o_registro_tem_teto(img, monkeypatch):
    monkeypatch.setattr(command_log, "GUARDA_MAX", 3)
    ids = [m.enqueue("testes3", [M1], "mlreboot") for _ in range(6)]
    assert [command_log.ler("testes3", c) is not None for c in ids] == [False] * 3 + [True] * 3


def test_quem_so_le_maquinas_nao_consulta_comando(client, img, hm, hi, admin_key):
    ha = {"Authorization": f"Bearer {admin_key}"}
    chave = client.post("/api/v1/service-keys", json={"name": "leitor", "scopes": ["machines:read"]}, headers=ha).json()["key"]
    _sala(client, hm)
    cid = client.post(f"{BASE}/commands", json={"command": "mlreboot", "target": "all"}, headers=hi).json()["command_id"]
    r = client.get(f"{BASE}/commands/{cid}", headers={"Authorization": f"Bearer {chave}"})
    assert r.status_code == 403 and r.json()["code"] == "insufficient_scope"
