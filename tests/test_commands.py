"""Fila de comandos, long-poll e bloqueio de tela."""

import threading
import time

import pytest

from server.app import fsdb
from server.app.services import machines as m

MAC = "52-54-00-12-34-56"


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


def test_status_ingest_creates_machine(client, img, hm, hi):
    r = client.post(
        f"/api/v1/site-images/testes3/machines/{MAC}/status",
        json={"hardware": {"memtotal": "16G"}, "operations": {"screen-lock": "NO"}},
        headers=hm,
    )
    assert r.status_code == 200
    assert r.json()["pending_commands"] == 0

    r = client.get("/api/v1/site-images/testes3/machines", headers=hi)
    machines = r.json()["machines"]
    assert len(machines) == 1
    assert machines[0]["mac"] == MAC
    assert machines[0]["online"] is True
    assert machines[0]["status"]["hardware"]["memtotal"] == "16G"


def test_status_requires_machine_key(client, img):
    r = client.post(
        f"/api/v1/site-images/testes3/machines/{MAC}/status",
        json={},
        headers={"X-NB-Machine-Key": "nb3m_errada"},
    )
    assert r.status_code == 401


def test_mac_is_validated(client, img, hm):
    r = client.post("/api/v1/site-images/testes3/machines/nao-e-mac/status", json={}, headers=hm)
    assert r.status_code == 400


def test_identificacao_invalida_fica_registrada(client, img, hm, hi):
    """Um agente com a detecção de MAC quebrada leva 400 em tudo — inclusive no
    status, então a máquina nunca chega a existir. O painel ficava vazio, sem
    dizer que alguém estava tentando: foram 4320 requisições rejeitadas em ~30
    horas antes de alguém olhar o log do servidor."""
    for _ in range(3):
        client.post("/api/v1/site-images/testes3/machines/enp0s3%5C/status", json={}, headers=hm)

    r = client.get("/api/v1/site-images/testes3/machines", headers=hi)
    assert r.status_code == 200, r.text
    assert r.json()["machines"] == []
    rejeitadas = r.json()["rejected"]
    assert len(rejeitadas) == 1
    assert rejeitadas[0]["id"] == "enp0s3\\"
    assert rejeitadas[0]["count"] == 3


def test_com_maquina_de_verdade_o_aviso_some(client, img, hm, hi):
    """O aviso é para o painel vazio: com máquina reportando, ele só atrapalha."""
    client.post("/api/v1/site-images/testes3/machines/naoemac/status", json={}, headers=hm)
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    r = client.get("/api/v1/site-images/testes3/machines", headers=hi)
    assert len(r.json()["machines"]) == 1
    assert "rejected" not in r.json()


def test_sem_chave_de_maquina_nao_registra_nada(client, img, hi):
    """Só agente nosso entra no registro: senão qualquer um enche o arquivo
    de fora, sem credencial nenhuma."""
    client.post("/api/v1/site-images/testes3/machines/lixo/status", json={})
    r = client.get("/api/v1/site-images/testes3/machines", headers=hi)
    assert "rejected" not in r.json()


def test_command_allowlist(client, img, hm, hi):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    r = client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "rm -rf /", "target": "all"},
        headers=hi,
    )
    assert r.status_code == 400
    # o comando de RCE do nb2 não existe mais
    r = client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "mlupdatecommands", "target": "all"},
        headers=hi,
    )
    assert r.status_code == 400


def test_command_lifecycle_enqueue_poll_ack(client, img, hm, hi):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    r = client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "cleanhomenow", "target": "all"},
        headers=hi,
    )
    cid = r.json()["command_id"]
    assert r.json()["machines"] == 1

    r = client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands", headers=hm)
    cmds = r.json()["commands"]
    assert [c["command"] for c in cmds] == ["cleanhomenow"]

    r = client.post(
        f"/api/v1/site-images/testes3/machines/{MAC}/commands/{cid}/ack",
        json={"status": "done"},
        headers=hm,
    )
    assert r.json()["found"] is True
    # depois do ack a fila fica vazia (o nb2 nunca truncava a fila)
    assert client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands", headers=hm).json()["commands"] == []


def test_command_only_reaches_target_machine(client, img, hm, hi):
    outra = "52-54-00-aa-bb-cc"
    for mac in (MAC, outra):
        client.post(f"/api/v1/site-images/testes3/machines/{mac}/status", json={}, headers=hm)
    client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "mlreboot", "target": [outra]},
        headers=hi,
    )
    assert client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands", headers=hm).json()["commands"] == []
    assert len(client.get(f"/api/v1/site-images/testes3/machines/{outra}/commands", headers=hm).json()["commands"]) == 1


def test_delay_holds_command(client, img, hm, hi):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "mlpoweroff", "target": "all", "delay": 60},
        headers=hi,
    )
    assert client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands", headers=hm).json()["commands"] == []
    assert len(m.pending_commands("testes3", MAC)) == 1


def test_longpoll_returns_within_seconds(client, img, hm, hi):
    """O requisito operacional: travar a tela precisa chegar em bem menos de
    10 s. O long-poll é acordado no instante do enqueue."""
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)

    resultado = {}

    def poll():
        t0 = time.monotonic()
        r = client.get(
            f"/api/v1/site-images/testes3/machines/{MAC}/commands?wait=25", headers=hm
        )
        resultado["elapsed"] = time.monotonic() - t0
        resultado["body"] = r.json()

    th = threading.Thread(target=poll)
    th.start()
    time.sleep(0.4)  # garante que o poll já está pendurado
    client.post("/api/v1/site-images/testes3/lock", headers=hi)
    th.join(timeout=20)

    assert not th.is_alive(), "long-poll não retornou"
    assert resultado["elapsed"] < 10, f"demorou {resultado['elapsed']:.1f}s"
    assert [c["command"] for c in resultado["body"]["commands"]] == ["donottouch"]
    assert resultado["body"]["lock"]["locked"] is True


def test_longpoll_times_out_without_commands(client, img, hm):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    t0 = time.monotonic()
    r = client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands?wait=1", headers=hm)
    elapsed = time.monotonic() - t0
    assert r.json()["commands"] == []
    assert 0.8 < elapsed < 8


def test_lock_sets_state_and_command(client, img, hm, hi):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/lock", headers=hi)

    # 1) estado consultável pela própria tela (funciona mesmo se o agente cair)
    assert client.get(f"/boot/v3/testes3/machines/{MAC}/lockstate").text.strip() == "locked"
    # 2) comando na fila para o agente executar
    cmds = client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands", headers=hm).json()
    assert cmds["commands"][0]["command"] == "donottouch"

    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/unlock", headers=hi)
    assert client.get(f"/boot/v3/testes3/machines/{MAC}/lockstate").text.strip() == "unlocked"


def test_precontest_grava_a_trava_no_servidor(client, img, hm, hi):
    """A macro do fim do warmup inclui travar a tela, e a trava só dura se o
    SERVIDOR souber dela: o agente obedece o lockstate do long-poll, então o
    ensure_locked que o comando faz na máquina seria desfeito no ciclo seguinte
    — travava por segundos e caía, sem ninguém entender."""
    outro = "52-54-00-99-99-99"
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.post(f"/api/v1/site-images/testes3/machines/{outro}/status", json={}, headers=hm)

    r = client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "precontest", "target": [MAC]},
        headers=hi,
    )
    assert r.status_code == 200, r.text
    # o alvo trava DE VERDADE (estado no servidor), e só ele
    assert client.get(f"/boot/v3/testes3/machines/{MAC}/lockstate").text.strip() == "locked"
    assert client.get(f"/boot/v3/testes3/machines/{outro}/lockstate").text.strip() == "unlocked"
    # e o comando segue na fila para o agente executar o resto da macro
    cmds = client.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands", headers=hm).json()
    assert [c["command"] for c in cmds["commands"]] == ["precontest"]


def test_comando_comum_nao_mexe_na_trava(client, img, hm, hi):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": "cleanhomenow", "target": [MAC]},
        headers=hi,
    )
    assert client.get(f"/boot/v3/testes3/machines/{MAC}/lockstate").text.strip() == "unlocked"


def test_acks_log_is_capped(data_root, img):
    from server.app.services.logcap import append_capped

    path = m.machine_dir("testes3", MAC) / "acks.log"
    for i in range(4000):
        append_capped(path, f'{{"i":{i},"lixo":"{"x" * 200}"}}', cap=64 * 1024)
    assert path.stat().st_size <= 64 * 1024
    # a cauda continua sendo JSON válido linha a linha
    import json

    linhas = path.read_text().splitlines()
    assert json.loads(linhas[-1])["i"] == 3999
    assert all(json.loads(line) for line in linhas)


# --- o cadeado do modelo vale também aqui ------------------------------------
#
# `DISABLE_FIREWALL` nasce travado no esquema padrão ("o firewall é obrigatório
# durante a maratona"), e a trava valia no configureitor e NÃO valia no
# hotconfig: a mesma pessoa que a tela de configuração impedia de desligar o
# firewall desligava pela tela do laboratório, na sala inteira, durante a prova.


@pytest.fixture
def com_esquema(data_root, img):
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    return img


def _manda(client, headers, comando):
    return client.post(
        "/api/v1/site-images/testes3/commands",
        json={"command": comando, "target": "all"},
        headers=headers,
    )


@pytest.fixture
def uma_maquina(client, com_esquema, hm):
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    return MAC


def test_a_sede_nao_desliga_o_firewall_travado(client, uma_maquina, hi):
    r = _manda(client, hi, "disablefirewall")
    assert r.status_code == 403, r.text
    assert "DISABLE_FIREWALL" in r.text


def test_ligar_o_firewall_continua_liberado(client, uma_maquina, hi):
    """Move a máquina PARA o valor travado: recusar seria impedir a sede de
    consertar o que a organização quer."""
    assert _manda(client, hi, "enablefirewall").status_code == 200


def test_a_administracao_desliga(client, uma_maquina, admin_key):
    ha = {"Authorization": f"Bearer {admin_key}"}
    assert _manda(client, ha, "disablefirewall").status_code == 200


def test_imagem_destravada_desliga(client, uma_maquina, hi, data_root):
    info = fsdb.read_json(data_root / "site-images" / "testes3" / "image.json")
    fsdb.write_json(data_root / "site-images" / "testes3" / "image.json", {**info, "unlocked": True})
    assert _manda(client, hi, "disablefirewall").status_code == 200


def test_destravar_o_campo_no_modelo_libera(client, uma_maquina, hi, data_root):
    from server.app.services import store

    store.set_schema_field("t", "DISABLE_FIREWALL", {"locked": False})
    assert _manda(client, hi, "disablefirewall").status_code == 200


def test_a_regra_e_a_MESMA_das_duas_telas(client, uma_maquina, hi):
    """O que o configureitor recusa, o hotconfig recusa. Duas cópias da regra é
    exatamente como as portas ficaram diferentes."""
    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"DISABLE_FIREWALL": True}},
        headers=hi,
    )
    assert r.status_code == 400, "o configureitor deixou passar; revise este teste"
    assert _manda(client, hi, "disablefirewall").status_code == 403


def test_a_rota_diz_o_que_pode_ser_mandado(client, uma_maquina, hi, admin_key):
    r = client.get("/api/v1/site-images/testes3/commands", headers=hi)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["blocked"] == {"disablefirewall": "DISABLE_FIREWALL"}
    assert "disablefirewall" not in d["allowed"]
    assert "enablefirewall" in d["allowed"]

    ha = {"Authorization": f"Bearer {admin_key}"}
    assert client.get("/api/v1/site-images/testes3/commands", headers=ha).json()["blocked"] == {}
