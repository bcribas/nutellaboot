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
    for i in range(3):
        espeta(client, hm, detail=f"dev{i}")  # dispositivos distintos: o igual não repete
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
    for i in range(alerts.MAX_ABERTOS + 20):
        espeta(client, hm, detail=f"dev{i}")  # dispositivos distintos: o igual não repete
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
    # só o nó com conteúdo sondado: no disco inteiro (sem label) a exclusão
    # não vale e a label das filhas ainda não está no banco do udev durante o
    # coldplug — era daí que vinha o alerta a cada boot
    linha = next(l for l in regra.splitlines() if "usb-event.sh storage" in l or 'SUBSYSTEM=="block"' in l)
    bloco = regra[regra.index('SUBSYSTEM=="block"') : regra.index("usb-event.sh storage")]
    assert 'ENV{ID_FS_USAGE}=="?*"' in bloco


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
# Reclamação da sala: toda máquina que ficava com o pendrive de boot espetado
# aparecia na faixa vermelha. Alerta é MUDANÇA de estado — alguém espetou algo
# durante a prova. O que já estava conectado quando a máquina ligou (o
# pendrive de boot, o leitor de cartão embutido) não é.


def _funcao_do_agente(nome: str) -> str:
    texto = (CLIENTE / "usr/share/mlog/agent.sh").read_text()
    inicio = texto.index(f"{nome}() {{")
    fim = texto.index("\n}\n", inicio) + 3
    return texto[inicio:fim]


def test_o_que_ja_estava_conectado_no_boot_nao_alerta(tmp_path):
    """O udev reemite `add` para tudo que está presente (coldplug) antes de o
    agente existir; a fila que o agente encontra ao subir é estado, não
    mudança, e é descartada — com registro no log da máquina."""
    import subprocess

    fila = tmp_path / "usb-events"
    fila.mkdir()
    (fila / "100-1").write_text("kind=usb.storage\nvendor=SanDisk Ultra\ndetail=sdb1\n")
    (fila / "101-2").write_text("kind=usb.phone\nvendor=Samsung\ndetail=mtp\n")
    corpo = f'USB_FILA="{fila}"\nlog() {{ echo "LOG: $*"; }}\n{_funcao_do_agente("usb_descarta_estado_inicial")}\nusb_descarta_estado_inicial\n'
    r = subprocess.run(["bash", "-c", corpo], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert list(fila.iterdir()) == []
    assert "SanDisk Ultra" in r.stdout and "sem alerta" in r.stdout


def test_a_varredura_de_boot_sumiu_de_proposito():
    """Ela alarmava "presente no boot" para o que não é mudança nenhuma —
    inclusive leitor de cartão embutido e o próprio pendrive de boot quando o
    lsblk ainda não sabia a label."""
    agente = (CLIENTE / "usr/share/mlog/agent.sh").read_text()
    assert "/sys/block/*/removable" not in agente
    assert "present at boot" not in agente
    assert "usb_descarta_estado_inicial" in agente[agente.index("usb_loop() {") :]


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
    # e a checagem sem corrida: a label do próprio nó, exportada pelo udev
    assert '"${ID_FS_LABEL:-}" = NB3CFG' in script


def test_o_tipo_de_cd_nao_e_usb():
    """`media.cd` vale para drive interno também — chamá-lo de `usb.*` faria a
    tela dizer que alguém espetou um pendrive."""
    script = (CLIENTE / "usr/share/mlog/usb-event.sh").read_text()
    assert "media.cd" in script


# --- o mesmo dispositivo não vira uma parede de alertas -----------------------


def _espeta(client, hm, **kw):
    r = client.post(f"/api/v1/site-images/sala1/machines/{MAC}/events", json={"kind": "usb.storage", **kw}, headers=hm)
    assert r.status_code == 200, r.text
    return r.json()


def test_o_mesmo_dispositivo_com_alerta_aberto_nao_repete(client, imagem, hm, ha, monkeypatch):
    from server.app.services import webhook_push

    vistos = []
    monkeypatch.setattr(webhook_push, "emit", lambda image, event, data: vistos.append(event))
    a = _espeta(client, hm, vendor="Kingston DT", detail="sdb1")
    b = _espeta(client, hm, vendor="Kingston DT", detail="sdb1")
    assert b["id"] == a["id"] and b["repeated"] is True and a["repeated"] is False
    assert vistos.count("alert.raised") == 1
    abertos = client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"]
    assert len(abertos) == 1


def test_dispositivo_diferente_ou_depois_de_dispensar_alerta_de_novo(client, imagem, hm, ha):
    a = _espeta(client, hm, vendor="Kingston DT", detail="sdb1")
    _espeta(client, hm, vendor="Samsung", detail="mtp", kind="usb.phone")
    assert len(client.get("/api/v1/site-images/sala1/alerts", headers=ha).json()["alerts"]) == 2
    client.post(f"/api/v1/site-images/sala1/machines/{MAC}/alerts/{a['id']}/dismiss", headers=ha)
    c = _espeta(client, hm, vendor="Kingston DT", detail="sdb1")
    assert c["id"] != a["id"] and c["repeated"] is False
