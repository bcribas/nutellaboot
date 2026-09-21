"""Vínculo máquina ↔ time com histórico — o que o MOJ pediu.

O `PUT …/binding` já existia; o que faltava era dizer QUEM afirmou o vínculo
(`source`), QUANDO o cliente o viu (`client_at`), em qual boot (`boot_id`) e
guardar as trocas — um time que muda de máquina no meio da prova é
informação.
"""

import json

import pytest

from server.app import fsdb
from server.app.services import bindings

MAC = "52-54-00-01-02-03"
ROTA = f"/api/v1/site-images/testes3/machines/{MAC}/binding"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def hi(img):
    return {"Authorization": f"Bearer {img['token']}"}


@pytest.fixture
def roster(client, img, ha):
    r = client.put(
        "/api/v1/site-images/testes3/roster",
        json={"roster": [{"user_id": "team-001", "name": "A", "seat": "12"}, {"user_id": "team-002", "name": "B"}]},
        headers=ha,
    )
    assert r.status_code == 200, r.text


def _moj(client, ha, scopes, nome="moj"):
    return {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/service-keys", json={"name": nome, "scopes": scopes, "images": []}, headers=ha
        ).json()["key"]
    }


def test_source_padrao_vem_da_credencial(client, roster, ha, hi):
    b = client.put(ROTA, json={"user_id": "team-001"}, headers=hi).json()
    assert b["source"] == "console" and b["seat"] == "12"
    moj = _moj(client, ha, ["bindings:write"])
    b = client.put(ROTA, json={"user_id": "team-002"}, headers=moj).json()
    assert b["source"] == "service:moj"
    b = client.put(ROTA, json={"user_id": "team-002", "source": "moj-login"}, headers=moj).json()
    assert b["source"] == "moj-login"


def test_at_boot_id_e_note_ficam_no_vinculo(client, roster, hi):
    b = client.put(
        ROTA, json={"user_id": "team-001", "at": 1788026460, "boot_id": "2172579592", "note": "login"}, headers=hi
    ).json()
    assert b["client_at"] == 1788026460 and b["boot_id"] == "2172579592" and b["note"] == "login"
    assert abs(b["bound_at"] - __import__("time").time()) < 5, "bound_at continua sendo do servidor"
    assert client.put(ROTA, json={"user_id": "team-001", "at": "ontem"}, headers=hi).status_code == 400
    maq = client.get(f"/api/v1/site-images/testes3/machines/{MAC}", headers=hi).json()
    assert maq["binding"]["boot_id"] == "2172579592"


def test_bind_e_unbind_ficam_no_historico(client, roster, hi):
    client.put(ROTA, json={"user_id": "team-001"}, headers=hi)
    client.put(ROTA, json={"user_id": "team-002", "source": "moj-login"}, headers=hi)
    assert client.delete(ROTA, headers=hi).status_code == 204
    assert client.delete(ROTA, headers=hi).status_code == 204  # sem vínculo: sem linha nova

    h = client.get(f"{ROTA}/history", headers=hi).json()["history"]
    assert [e["event"] for e in h] == ["bound", "bound", "unbound"]
    assert h[1]["source"] == "moj-login"
    assert h[2]["user_id"] == "team-002", "o unbound diz o que foi desfeito"
    assert client.get(f"{ROTA}/history?n=1", headers=hi).json()["history"][0]["event"] == "unbound"


def test_historico_exige_machines_read(client, roster, ha, hi):
    client.put(ROTA, json={"user_id": "team-001"}, headers=hi)
    so_escreve = _moj(client, ha, ["bindings:write"])
    assert client.get(f"{ROTA}/history", headers=so_escreve).status_code == 403
    le = _moj(client, ha, ["bindings:write", "machines:read"], nome="moj-leitor")
    assert client.get(f"{ROTA}/history", headers=le).status_code == 200


def test_o_historico_tem_teto(client, roster, hi, monkeypatch):
    monkeypatch.setattr(bindings, "HISTORICO", 2048)
    for i in range(80):
        client.put(ROTA, json={"user_id": "team-001", "note": f"n{i}"}, headers=hi)
    p = bindings.machine_dir("testes3", MAC) / bindings.LOG
    assert p.stat().st_size <= 2048 + 300
    ultimo = json.loads(p.read_text().splitlines()[-1])
    assert ultimo["note"] == "n79"
