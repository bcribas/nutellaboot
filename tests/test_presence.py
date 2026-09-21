"""Eventos de máquina: reiniciou, sumiu, voltou; e o alerta com contexto.

`online` era uma conta feita na leitura; ninguém avisava que uma máquina tinha
parado de reportar, nem que tinha reiniciado (o MOJ inferia pela troca do
`boot_id` a cada coleta).
"""

import asyncio

import pytest

from server.app import fsdb
from server.app.services import machines as m
from server.app.services import presence, webhook_push

BASE = "/api/v1/site-images/testes3"
MAC = "52-54-00-12-34-56"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    presence.reset()
    yield image_testes3
    presence.reset()


@pytest.fixture
def hm(img):
    return {"X-NB-Machine-Key": img["machine_key"]}


@pytest.fixture
def vistos(monkeypatch):
    lista = []
    monkeypatch.setattr(webhook_push, "emit", lambda image, event, data: lista.append((event, data)))
    return lista


def _status(client, hm, boot):
    r = client.post(f"{BASE}/machines/{MAC}/status", json={"hwinfo": {"boot_id": boot}}, headers=hm)
    assert r.status_code == 200


def _nomes(vistos):
    return [e for e, _ in vistos if e != "machine.status"]


def test_reboot_avisa_e_o_primeiro_contato_nao(client, img, hm, vistos):
    _status(client, hm, "111")
    assert _nomes(vistos) == ["machine.first_seen"]
    _status(client, hm, "111")
    assert _nomes(vistos) == ["machine.first_seen"]
    _status(client, hm, "222")
    ev, dados = vistos[-1]
    assert ev == "machine.rebooted"
    assert dados["mac"] == MAC and dados["boot_id"] == "222" and dados["previous_boot_id"] == "111"
    assert dados["boots"] == 2 and isinstance(dados["last_boot"], int)


def test_volta_ao_ar_depois_de_sumir(client, img, hm, vistos, data_root):
    _status(client, hm, "111")
    arq = m.machine_dir("testes3", MAC) / "machine.json"
    info = fsdb.read_json(arq)
    info["last_seen"] -= 400
    fsdb.write_json(arq, info)
    _status(client, hm, "111")
    ev, dados = vistos[-1]
    assert ev == "machine.online" and dados["mac"] == MAC and 399 <= dados["offline_for"] <= 405


def test_a_varredura_anuncia_uma_vez_e_so_em_memoria(img):
    presence.marcar("testes3", MAC, agora=1000.0)
    assert presence.varrer(agora=1000.0 + m.ONLINE_WINDOW - 1) == []
    assert presence.varrer(agora=1000.0 + m.ONLINE_WINDOW) == [("testes3", MAC, 1000.0)]
    assert presence.varrer(agora=5000.0) == [], "anunciou de novo"
    # voltou a reportar: some da lista de quem está fora, e pode sumir de novo
    presence.marcar("testes3", MAC, agora=6000.0)
    assert presence.varrer(agora=6000.0 + m.ONLINE_WINDOW) == [("testes3", MAC, 6000.0)]


def test_ao_subir_quem_ja_estava_desligado_nao_vira_noticia(client, img, hm, data_root):
    """O primeiro deploy não pode despejar um machine.offline para cada máquina
    desligada da frota; só o sumiço recente ainda é notícia."""
    import time

    for mac, atras in (("52-54-00-00-00-01", 86400), ("52-54-00-00-00-02", 120), ("52-54-00-00-00-03", 5)):
        client.post(f"{BASE}/machines/{mac}/status", json={}, headers=hm)
        arq = m.machine_dir("testes3", mac) / "machine.json"
        info = fsdb.read_json(arq)
        info["last_seen"] = time.time() - atras
        fsdb.write_json(arq, info)
    presence.reset()
    presence._semear()
    assert [mac for _, mac, _ in presence.varrer()] == ["52-54-00-00-00-02"]


def test_o_tique_publica_offline_e_comando_vencido(client, img, hm, vistos, monkeypatch):
    hi = {"Authorization": f"Bearer {img['token']}"}
    _status(client, hm, "111")
    cid = client.post(f"{BASE}/commands", json={"command": "mlreboot", "target": "all"}, headers=hi).json()["command_id"]
    vistos.clear()
    presence._vistos[("testes3", MAC)] -= 1000
    presence._comandos[("testes3", cid)] = 0
    monkeypatch.setattr(m, "_command_ttl", lambda: 0)
    fsdb.write_json(
        m.site_image_dir("testes3") / "commands" / f"{cid}.json",
        {**fsdb.read_json(m.site_image_dir("testes3") / "commands" / f"{cid}.json"), "ttl": 0, "not_before": 1},
    )
    asyncio.run(presence.tique())
    eventos = dict(vistos)
    assert eventos["machine.offline"]["mac"] == MAC and isinstance(eventos["machine.offline"]["last_seen"], int)
    assert eventos["command.expired"] == {"command_id": cid, "command": "mlreboot", "machines": [MAC], "count": 1}


def test_o_alerta_leva_o_boot_e_o_time(client, img, hm, vistos):
    hi = {"Authorization": f"Bearer {img['token']}"}
    _status(client, hm, "777")
    client.post(f"{BASE}/roster", json={"user_id": "teambr01", "name": "Um"}, headers=hi)
    client.put(f"{BASE}/machines/{MAC}/binding", json={"user_id": "teambr01"}, headers=hi)
    r = client.post(f"{BASE}/machines/{MAC}/events", json={"kind": "usb.storage", "detail": "pendrive", "vendor": "X"}, headers=hm)
    assert r.status_code == 200, r.text
    dados = next(d for e, d in vistos if e == "alert.raised")
    assert dados["boot_id"] == "777" and dados["binding"] == {"user_id": "teambr01"}
    # o contrato antigo continua: mac, id, kind
    assert dados["mac"] == MAC and dados["id"] and dados["kind"] == "usb.storage"
    client.post(f"{BASE}/machines/{MAC}/alerts/dismiss-all", headers=hi)
    dispensa = next(d for e, d in vistos if e == "alert.dismissed")
    assert dispensa["boot_id"] == "777" and dispensa["binding"] == {"user_id": "teambr01"}
