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


# --- o que é alerta e o que não é ---------------------------------------------
#
# "Máquinas com CDROM e/ou FLOPPY não precisam alertar, só se colocarem um
# cdrom ou pendrive ou celular na máquina." O critério da varredura de boot era
# só `removable == 1`, e isso inclui leitor de CD e drive de disquete, vazios,
# em qualquer barramento: toda máquina com um deles alarmava "PENDRIVE
# CONECTADO" a cada boot — e o alerta fica na tela até um fiscal dispensar.


def varredura(tmp_path, discos):
    """Roda a varredura de boot do agente de verdade contra um /sys de mentira.

    `discos` é {nome: {"removable": "1", "size": "0", "usb": True, ...}}.
    """
    import subprocess

    sysblock = tmp_path / "sys" / "block"
    devices = tmp_path / "devices"
    fila = tmp_path / "fila"
    fila.mkdir(parents=True)
    for nome, d in discos.items():
        # o caminho real é o que diz se está pendurado no USB
        real = devices / ("pci0000:00/usb1/1-1" if d.get("usb") else "pci0000:00/ata1") / nome
        real.mkdir(parents=True)
        (real / "removable").write_text(d.get("removable", "1") + "\n")
        (real / "size").write_text(d.get("size", "0") + "\n")
        (real / "device").mkdir()
        (real / "device" / "model").write_text(d.get("model", nome) + "\n")
        sysblock.mkdir(parents=True, exist_ok=True)
        (sysblock / nome).symlink_to(real)

    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "lsblk").write_text(
        "#!/bin/sh\n"
        # só o pendrive de boot tem a label
        'case "$*" in *bootpen*) echo NB3CFG ;; *) echo ;; esac\n'
    )
    (fake / "lsblk").chmod(0o755)

    corpo = f"""
        USB_FILA="{fila}"
        {_trecho_varredura()}
    """
    r = subprocess.run(
        ["bash", "-c", corpo],
        capture_output=True,
        text=True,
        env={"PATH": f"{fake}:/usr/bin:/bin", "SYSBLOCK": str(sysblock)},
    )
    assert r.returncode == 0, r.stderr
    return {p.name: p.read_text() for p in fila.iterdir()}


def _trecho_varredura() -> str:
    """O laço de varredura do agente, com /sys/block parametrizado."""
    texto = (CLIENTE / "usr/share/mlog/agent.sh").read_text()
    inicio = texto.index("    for dev in /sys/block/*/removable; do")
    fim = texto.index("\n    done\n", inicio) + len("\n    done\n")
    return texto[inicio:fim].replace("/sys/block", '$SYSBLOCK')


def test_leitor_de_cd_vazio_nao_alerta(tmp_path):
    """Ter leitor de CD não é evento: a maioria das máquinas de laboratório
    tem um, e ele nasce `removable=1`."""
    assert varredura(tmp_path, {"sr0": {"size": "0", "model": "DVD-RAM GH24"}}) == {}


def test_disco_no_leitor_tambem_nao_alerta(tmp_path):
    """Nem com mídia dentro.

    Houve uma versão que alarmava quando o sysfs reportava tamanho — leitor com
    disco. Saiu por decisão de operação: aparecia demais. Some o aviso E o
    rastro, e é isso que este teste prende, para que voltar atrás seja uma
    escolha e não um acidente."""
    assert varredura(tmp_path, {"sr0": {"size": "1400000", "model": "DVD-RAM GH24"}}) == {}


def test_drive_de_disquete_nunca_alerta(tmp_path):
    """O kernel não emite troca de mídia para fd0 e o tamanho é fixo: não há o
    que detectar, então nem o drive vazio nem com disquete geram ruído."""
    assert varredura(tmp_path, {"fd0": {"size": "2880"}}) == {}


def test_pendrive_no_boot_alerta(tmp_path):
    fila = varredura(tmp_path, {"sdb": {"usb": True, "model": "SanDisk Ultra"}})
    assert "kind=usb.storage" in fila["boot-sdb"]
    assert "SanDisk Ultra" in fila["boot-sdb"]


def test_pendrive_de_boot_nao_alerta(tmp_path):
    assert varredura(tmp_path, {"bootpen": {"usb": True}}) == {}


def test_disco_removivel_interno_nao_alerta(tmp_path):
    """Gaveta hot-swap SATA é hardware da sala, não algo que alguém espetou."""
    assert varredura(tmp_path, {"sdc": {"usb": False, "model": "ST1000"}}) == {}


# --- o udev ---


def test_udev_nao_alerta_disco_optico():
    """Nenhuma regra pode casar mídia óptica: nem `change` com ID_CDROM_MEDIA,
    nem o drive entrando pela regra de armazenamento USB."""
    linhas = [
        l
        for l in (CLIENTE / "etc/udev/rules.d/99-nb3-usb.rules").read_text().splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]
    regras = "\n".join(linhas)
    assert "ID_CDROM_MEDIA" not in regras, "o alerta de mídia óptica voltou"
    assert 'ACTION=="change"' not in regras
    # e o gravador de DVD USB continua fora da regra de armazenamento
    assert 'ENV{ID_CDROM}!="1"' in regras


def test_o_script_do_udev_descarta_o_pendrive_de_boot():
    """A exclusão por label na regra só pega o nó da PARTIÇÃO; o do disco
    inteiro (sem label) escapava e alarmava a cada boot."""
    script = (CLIENTE / "usr/share/mlog/usb-event.sh").read_text()
    assert "NB3CFG" in script and "lsblk" in script


def test_o_tipo_de_cd_nao_e_usb():
    """`media.cd` vale para drive interno também — chamá-lo de `usb.*` faria a
    tela dizer que alguém espetou um pendrive."""
    script = (CLIENTE / "usr/share/mlog/usb-event.sh").read_text()
    assert "media.cd" in script
