"""Alerta de dispositivo USB: nasce na máquina e fica até alguém dispensar.

A regra que define tudo aqui: o alerta NÃO some quando o dispositivo é
removido. Quem espeta um pendrive por cinco segundos não pode escapar do
registro — some só quando um fiscal clica, e fica gravado quem foi.
"""

import json
from pathlib import Path

import pytest

from server.app import fsdb
from server.app.services import alerts
from server.app.services.default_schema import build_default_schema

MAC = "52-54-00-11-22-33"
CLIENTE = Path(__file__).resolve().parents[1] / "client" / "telemetry"


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def imagem(client, data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    r = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "Sala 1", "model": "t"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 201, r.text
    # a máquina precisa existir para entrar na listagem
    client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/status",
        json={"hwinfo": {}},
        headers={"X-NB-Machine-Key": r.json()["machine_key"]},
    )
    return r.json()


@pytest.fixture
def hm(imagem):
    return {"X-NB-Machine-Key": imagem["machine_key"]}


def espeta(client, hm, kind="usb.storage", **kw):
    r = client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/events",
        json={"kind": kind, **kw},
        headers=hm,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --- o ciclo de vida ---


def test_pendrive_espetado_vira_alerta_aberto(client, imagem, hm, ha):
    espeta(client, hm, detail="sdb1", vendor="SanDisk Cruzer 32GB")
    abertos = client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"]
    assert len(abertos) == 1
    a = abertos[0]
    assert a["kind"] == "usb.storage"
    assert a["mac"] == MAC
    assert a["vendor"] == "SanDisk Cruzer 32GB"
    assert a["detail"] == "sdb1"


def test_alerta_nao_some_sozinho(client, imagem, hm, ha):
    """O ponto inteiro da funcionalidade: o dispositivo sai, o alerta fica."""
    espeta(client, hm)
    for _ in range(3):
        client.post(
            f"/api/v1/site-images/sala1/machines/{MAC}/status",
            json={"hwinfo": {}},
            headers=hm,
        )
    assert len(client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"]) == 1


def test_dispensar_tira_e_registra_quem_foi(client, imagem, hm, ha):
    aid = espeta(client, hm)
    r = client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/alerts/{aid}/dismiss", headers=ha
    )
    assert r.status_code == 200
    assert r.json()["alert"]["dismissed_by"]
    assert client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"] == []

    historico = client.get(
        f"/api/v1/site-images/sala1/machines/{MAC}/alerts/history", headers=ha
    ).json()["history"]
    assert [h["event"] for h in historico] == ["raised", "dismissed"]
    assert historico[-1]["dismissed_by"]


def test_dispensar_duas_vezes_nao_e_erro(client, imagem, hm, ha):
    """Dois fiscais clicando ao mesmo tempo é o caso normal numa sala."""
    aid = espeta(client, hm)
    rota = f"/api/v1/site-images/sala1/machines/{MAC}/alerts/{aid}/dismiss"
    assert client.post(rota, headers=ha).status_code == 200
    r = client.post(rota, headers=ha)
    assert r.status_code == 200
    assert r.json()["already"] is True


def test_alerta_sobrevive_a_recarga_da_pagina(client, imagem, hm, ha):
    """Está em disco, não em memória do processo nem da aba: recarregar a tela
    (ou abrir noutro computador) mostra o mesmo."""
    espeta(client, hm)
    assert alerts.open_alerts("sala1", MAC), "o alerta tem que estar em disco"
    maquinas = client.get("/api/v1/site-images/sala1/machines", headers=ha).json()["machines"]
    assert len(maquinas[0]["alerts"]) == 1


def test_dispensar_tudo_de_uma_maquina(client, imagem, hm, ha):
    for _ in range(3):
        espeta(client, hm)
    r = client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/alerts/dismiss-all", headers=ha
    )
    assert r.json()["dismissed"] == 3
    assert client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"] == []


@pytest.mark.parametrize("kind", ["usb.storage", "usb.phone", "usb.network", "usb.other"])
def test_todos_os_tipos_entram(client, imagem, hm, ha, kind):
    espeta(client, hm, kind=kind)
    abertos = client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"]
    assert abertos[0]["kind"] == kind


def test_tipo_desconhecido_nao_e_recusado(client, imagem, hm, ha):
    """O cliente pode ganhar um detector novo sem esperar o servidor."""
    espeta(client, hm, kind="bluetooth.pairing")
    assert client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"]


# --- segurança ---


def test_so_a_maquina_levanta_alerta(client, imagem):
    r = client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/events", json={"kind": "usb.storage"}
    )
    assert r.status_code == 401


def test_so_quem_tem_credencial_dispensa(client, imagem, hm):
    aid = espeta(client, hm)
    r = client.post(f"/api/v1/site-images/sala1/machines/{MAC}/alerts/{aid}/dismiss")
    assert r.status_code == 401
    assert alerts.open_alerts("sala1", MAC), "o alerta tem que continuar aberto"


def test_maquina_nao_dispensa_o_proprio_alerta(client, imagem, hm):
    """Senão bastaria adulterar o agente para apagar o próprio rastro."""
    aid = espeta(client, hm)
    r = client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/alerts/{aid}/dismiss", headers=hm
    )
    assert r.status_code == 401
    assert alerts.open_alerts("sala1", MAC)


def test_texto_do_dispositivo_e_limitado(client, imagem, hm, ha):
    """O nome vem do fabricante e entra na tela do fiscal."""
    espeta(client, hm, detail="x" * 5000, vendor="y" * 5000)
    a = client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"][0]
    assert len(a["detail"]) <= 300
    assert len(a["vendor"]) <= 120


def test_muitos_alertas_nao_crescem_sem_limite(client, imagem, hm, ha):
    for _ in range(alerts.MAX_ABERTOS + 20):
        espeta(client, hm)
    assert len(alerts.open_alerts("sala1", MAC)) == alerts.MAX_ABERTOS


# --- eventos para a tela e para o MOJ ---


def test_alerta_esta_no_catalogo_de_eventos(client):
    tipos = client.get("/api/v1/events/types").json()["events"]
    assert "alert.raised" in tipos
    assert "alert.dismissed" in tipos


def test_alerta_dispara_webhook(client, imagem, hm, ha, monkeypatch):
    enviados = []
    from server.app.services import webhook_push

    monkeypatch.setattr(webhook_push, "emit", lambda img, ev, data: enviados.append((ev, data)))
    espeta(client, hm)
    assert any(ev == "alert.raised" for ev, _ in enviados), enviados


# --- a regra de udev do lado da máquina ---


def test_regra_udev_ignora_o_pendrive_de_boot():
    """Em muitas salas o pendrive de boot fica espetado o dia todo; se ele
    disparasse o alarme, ninguém olharia mais para a faixa vermelha."""
    regra = (CLIENTE / "etc/udev/rules.d/99-nb3-usb.rules").read_text()
    assert 'ENV{ID_FS_LABEL}!="NB3CFG"' in regra


def test_regra_udev_cobre_pendrive_celular_e_tethering():
    regra = (CLIENTE / "etc/udev/rules.d/99-nb3-usb.rules").read_text()
    assert 'SUBSYSTEM=="block"' in regra
    assert "ID_MTP_DEVICE" in regra
    assert 'SUBSYSTEM=="net"' in regra, "tethering é o jeito mais direto de furar o firewall"


def test_script_do_udev_nao_fala_com_a_rede():
    """Ele roda dentro da fila de eventos do udev: esperar rede ali atrasa a
    enumeração de dispositivos da máquina inteira."""
    script = (CLIENTE / "usr/share/mlog/usb-event.sh").read_text()
    for proibido in ("curl", "wget", "nc "):
        assert proibido not in script, f"{proibido} no caminho do udev"


def test_agente_monta_o_json_com_escape():
    """O nome do dispositivo vem do fabricante; uma aspa no modelo quebraria o
    corpo montado com aspas no shell — que foi como o nb2 fazia."""
    agente = (CLIENTE / "usr/share/mlog/agent.sh").read_text()
    assert "nb3-json --escape" in agente

    import subprocess

    r = subprocess.run(
        ["python3", str(CLIENTE / "usr/bin/nb3-json"), "--escape",
         "kind", "usb.storage", "vendor", 'Kingston "DT" 64GB'],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(r.stdout)["vendor"] == 'Kingston "DT" 64GB'
