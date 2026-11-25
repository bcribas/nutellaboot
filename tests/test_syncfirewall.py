"""O allowlist do firewall chega à máquina sem reboot (`syncfirewall`).

O allowlist vai no stuff, que a máquina baixa no boot. Na prova isso cobrou o
preço: o domínio da prova entrou no allowlist com a sala já ligada, e o
firewall bloqueou o acesso em todas as máquinas que tinham bootado antes. Agora
o servidor expõe o allowlist atual à máquina, e manda ela rebuscar sempre que
ele muda.
"""

import subprocess
from pathlib import Path

import pytest

from server.app import fsdb
from server.app.services import config as cfg
from server.app.services import machines as m
from server.app.services.default_schema import build_default_schema

REPO = Path(__file__).resolve().parents[1]
AGENTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"
MAC = "52-54-00-12-34-56"
MAC2 = "52-54-00-12-34-57"
URL = f"/api/v1/site-images/testes3/machines/{MAC}/firewall"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    # o allowlist é campo travado: vale o que a imagem salvou só se ela estiver
    # destravada (ou se quem salvou for a administração, com ela destravada)
    info = fsdb.read_json(data_root / "site-images" / "testes3" / "image.json")
    info["unlocked"] = True
    fsdb.write_json(data_root / "site-images" / "testes3" / "image.json", info)
    return image_testes3


@pytest.fixture
def hm(img):
    return {"X-NB-Machine-Key": img["machine_key"]}


@pytest.fixture
def hi(img):
    return {"Authorization": f"Bearer {img['token']}"}


def _maquina(client, hm, mac=MAC):
    r = client.post(f"/api/v1/site-images/testes3/machines/{mac}/status", json={}, headers=hm)
    assert r.status_code == 200


# --- a rota ------------------------------------------------------------------


def test_a_maquina_recebe_o_allowlist_atual(client, img, hm):
    cfg.write_values(
        "testes3", {"FIREWALL_ALLOWLIST": ["prova.moj.example 200.19.248.54", "boca 10.0.0.2"]}, is_admin=True
    )
    r = client.get(URL, headers=hm)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.splitlines() == [
        "# nb3-firewall-allowlist v1",
        "prova.moj.example 200.19.248.54",
        "boca 10.0.0.2",
    ]


def test_a_rota_exige_a_chave_de_maquina(client, img, hi):
    assert client.get(URL).status_code in (401, 403)
    # o token da sede não é chave de máquina
    assert client.get(URL, headers=hi).status_code in (401, 403)


def test_itens_invalidos_ficam_de_fora(data_root, img):
    """Valor salvo antes da validação existir: nome com barra, o reservado, IP
    com letra fora de hexa — nenhum vira arquivo na máquina."""
    lista = ["../../etc/x 1.2.3.4", "maratona 1.2.3.4", "a.com 1.2.3.z", "ok.com 5.6.7.8"]
    fsdb.write_json(data_root / "site-images" / "testes3" / "config.json", {"values": {"FIREWALL_ALLOWLIST": lista}})
    assert cfg.config_values("testes3")["FIREWALL_ALLOWLIST"] == lista
    assert cfg.allowlist_firewall("testes3") == [("ok.com", "5.6.7.8")]


# --- o envio automático -------------------------------------------------------


def test_mudar_o_allowlist_manda_syncfirewall_para_a_sala(client, img, hm, admin_key):
    _maquina(client, hm, MAC)
    _maquina(client, hm, MAC2)
    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"FIREWALL_ALLOWLIST": ["prova.moj.example 200.19.248.54"]}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 200, r.text
    for mac in (MAC, MAC2):
        assert [c["command"] for c in m.pending_commands("testes3", mac)] == ["syncfirewall"]


def test_mudar_outro_campo_nao_manda_nada(client, img, hm, hi):
    _maquina(client, hm)
    r = client.put("/api/v1/site-images/testes3/config", json={"values": {"TIMEZONE": "UTC"}}, headers=hi)
    assert r.status_code == 200, r.text
    assert m.pending_commands("testes3", MAC) == []


def test_salvar_o_mesmo_allowlist_nao_manda_nada(client, img, hm, admin_key):
    lista = ["prova.moj.example 200.19.248.54"]
    cfg.write_values("testes3", {"FIREWALL_ALLOWLIST": lista}, is_admin=True)
    _maquina(client, hm)
    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"FIREWALL_ALLOWLIST": lista}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 200, r.text
    assert m.pending_commands("testes3", MAC) == []


def test_syncfirewall_pode_ser_mandado_a_mao(client, img, hm, hi):
    _maquina(client, hm)
    r = client.post("/api/v1/site-images/testes3/commands", json={"command": "syncfirewall"}, headers=hi)
    assert r.status_code == 200, r.text
    assert r.json()["machines"] == 1


# --- o agente -----------------------------------------------------------------


def _funcoes(*nomes: str) -> str:
    texto = AGENTE.read_text()
    partes = []
    for nome in nomes:
        inicio = texto.index(f"{nome}() {{")
        fim = texto.index("\n}\n", inicio) + 3
        partes.append(texto[inicio:fim])
    return "\n".join(partes)


@pytest.fixture
def maquina(tmp_path):
    """Os arquivos que o sync mexe, num diretório de teste, e um systemctl
    falso que anota o que foi pedido."""
    hosts = tmp_path / "hosts"
    hosts.mkdir()
    (hosts / "maratona").write_text("127.0.1.1\n")
    (hosts / "da-base").write_text("9.9.9.9\n")  # veio da camada base: não é nosso
    (hosts / "antigo.example").write_text("1.1.1.1\n")
    (tmp_path / "nossos").write_text("antigo.example\n")
    (tmp_path / "etc_hosts").write_text(
        "127.0.0.1\tlocalhost\n127.0.1.1\tmaratona\n9.9.9.9\tda-base\n1.1.1.1\tantigo.example\n"
    )
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "systemctl").write_text(
        f'#!/bin/sh\necho "$*" >> {tmp_path}/systemctl.log\n[ "$1" != is-active ] || [ -e {tmp_path}/ativo ]\n'
    )
    (bin_ / "systemctl").chmod(0o755)
    return tmp_path


def _sync(maquina, resposta: str | None, ativo=True):
    if ativo:
        (maquina / "ativo").touch()
    resp = maquina / "resposta"
    if resposta is None:
        curl = "curl_api() { return 22; }"
    else:
        resp.write_text(resposta)
        curl = f'curl_api() {{ cat "{resp}"; }}'
    script = "\n".join(
        [
            "log() { echo \"LOG $*\"; }",
            curl,
            _funcoes("cmd_syncfirewall"),
            "cmd_syncfirewall",
        ]
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": f"{maquina}/bin:/usr/bin:/bin",
            "MAC": MAC,
            "NB3_FW_HOSTS": str(maquina / "hosts"),
            "NB3_FW_NOSSOS": str(maquina / "nossos"),
            "NB3_ETC_HOSTS": str(maquina / "etc_hosts"),
        },
    )


def test_o_agente_aplica_o_allowlist_novo(maquina):
    r = _sync(maquina, "# nb3-firewall-allowlist v1\nprova.moj.example 200.19.248.54\n")
    assert r.returncode == 0, r.stderr + r.stdout
    hosts = maquina / "hosts"
    assert (hosts / "prova.moj.example").read_text() == "200.19.248.54\n"
    # o que saiu da lista sai da máquina, arquivo e linha do /etc/hosts
    assert not (hosts / "antigo.example").exists()
    assert "antigo.example" not in (maquina / "etc_hosts").read_text()
    # o que não é do nutellaboot fica
    assert (hosts / "maratona").exists() and (hosts / "da-base").exists()
    assert "da-base" in (maquina / "etc_hosts").read_text()
    assert (maquina / "nossos").read_text().split() == ["prova.moj.example"]
    # firewall ligado: reaplicado
    assert "restart maratona-firewall.service" in (maquina / "systemctl.log").read_text()


def test_com_o_firewall_desligado_so_prepara(maquina):
    r = _sync(maquina, "# nb3-firewall-allowlist v1\nprova.moj.example 200.19.248.54\n", ativo=False)
    assert r.returncode == 0, r.stderr
    assert (maquina / "hosts/prova.moj.example").exists()
    assert "restart" not in (maquina / "systemctl.log").read_text()


@pytest.mark.parametrize("resposta", [None, "<html>portal cativo</html>\n", ""])
def test_resposta_ruim_nao_apaga_nada(maquina, resposta):
    """Servidor fora, ou um 200 que não é dele: a sala fica com o que tem."""
    r = _sync(maquina, resposta)
    assert r.returncode != 0
    assert (maquina / "hosts/antigo.example").exists()
    assert (maquina / "nossos").read_text() == "antigo.example\n"
    assert not (maquina / "systemctl.log").exists()


def test_o_agente_recusa_nomes_perigosos(maquina):
    r = _sync(
        maquina,
        "# nb3-firewall-allowlist v1\n../../x 1.2.3.4\nmaratona 1.2.3.4\nruim.example 1.2.3.4;rm\nok.example 5.6.7.8\n",
    )
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in (maquina / "hosts").iterdir()) == ["da-base", "maratona", "ok.example"]
    assert (maquina / "hosts/maratona").read_text() == "127.0.1.1\n"
    assert not (maquina / "x").exists()


def test_lista_vazia_remove_os_nossos(maquina):
    r = _sync(maquina, "# nb3-firewall-allowlist v1\n")
    assert r.returncode == 0, r.stderr
    assert not (maquina / "hosts/antigo.example").exists()
    assert (maquina / "hosts/da-base").exists()


def test_enablefirewall_sincroniza_antes_de_ligar():
    corpo = _funcoes("cmd_enablefirewall")
    assert corpo.index("cmd_syncfirewall") < corpo.index("systemctl start")
