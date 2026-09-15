"""Duas máquinas com o mesmo machine-id.

O MOJ ligava o login do time à máquina pelo `machine_id` do user-agent, e
achou 62 grupos de máquinas com o id repetido (24 em Salvador, 39 pares no
Rio): era a home clonada por imagem de disco. O servidor agora mantém um
índice por sede e abre um alerta na segunda máquina que reporta um id já
visto — a sede vê o problema no warm-up, não no relatório.
"""

import pytest

from server.app import fsdb
from server.app.services import alerts

A = "52-54-00-00-00-0a"
B = "52-54-00-00-00-0b"


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


def _status(client, hm, mac, mid):
    return client.post(
        f"/api/v1/site-images/testes3/machines/{mac}/status",
        json={"hwinfo": {"machine_id": mid, "boot_id": "x"}},
        headers=hm,
    )


def test_machine_id_repetido_gera_alerta_na_segunda_maquina(client, img, hm, hi):
    _status(client, hm, A, "abc")
    _status(client, hm, B, "abc")
    assert alerts.open_alerts("testes3", A) == []
    abertos = alerts.open_alerts("testes3", B)
    assert [a["kind"] for a in abertos] == ["identity.duplicate"]
    assert abertos[0]["other_mac"] == A and abertos[0]["machine_id"] == "abc"
    # e aparece onde o painel olha
    maq = client.get(f"/api/v1/site-images/testes3/machines/{B}", headers=hi).json()
    assert maq["alerts"][0]["kind"] == "identity.duplicate"


def test_o_alerta_vai_por_evento(client, img, hm, monkeypatch):
    from server.app.services import webhook_push

    vistos = []
    monkeypatch.setattr(webhook_push, "emit", lambda image, event, data: vistos.append((event, data)))
    _status(client, hm, A, "abc")
    _status(client, hm, B, "abc")
    assert any(e == "alert.raised" and d.get("kind") == "identity.duplicate" for e, d in vistos)


def test_o_alerta_nao_repete_enquanto_esta_aberto(client, img, hm):
    _status(client, hm, A, "abc")
    for _ in range(5):
        _status(client, hm, B, "abc")
        _status(client, hm, A, "abc")
    assert len(alerts.open_alerts("testes3", B)) == 1
    assert len(alerts.open_alerts("testes3", A)) == 1


def test_depois_de_dispensar_pode_reaparecer(client, img, hm, hi):
    _status(client, hm, A, "abc")
    _status(client, hm, B, "abc")
    aid = alerts.open_alerts("testes3", B)[0]["id"]
    alerts.dismiss("testes3", B, aid, "teste")
    _status(client, hm, A, "abc")
    _status(client, hm, B, "abc")
    assert len(alerts.open_alerts("testes3", B)) == 1


def test_machine_id_vazio_nao_indexa_nem_alarma(client, img, hm, data_root):
    _status(client, hm, A, "")
    _status(client, hm, B, "")
    client.post(f"/api/v1/site-images/testes3/machines/{A}/status", json={}, headers=hm)
    assert not (data_root / "site-images" / "testes3" / "machineids.json").exists()
    assert alerts.open_alerts("testes3", B) == []


def test_a_mesma_maquina_nao_alarma_e_ids_distintos_tampouco(client, img, hm):
    for _ in range(3):
        _status(client, hm, A, "abc")
    _status(client, hm, B, "def")
    assert alerts.open_alerts("testes3", A) == [] and alerts.open_alerts("testes3", B) == []
