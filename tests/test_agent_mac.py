"""A identidade que o agente manda ao servidor.

O agente lia o MAC contando campos a partir do fim da saída do `ip -o link`.
O formato varia (`altname`, `permaddr`, e a barra invertida que o `ip -o` usa
de separador virando parte de um campo), e numa máquina de teste o resultado
foi `enp0s3\\` — o NOME da interface.

O servidor recusa isso com 400, corretamente. Só que o `status` também era
recusado, então a máquina nunca chegava a existir: o hotconfig ficava vazio,
sem nenhum sinal de que alguém estava tentando. Foram 4320 requisições
rejeitadas, ~30 horas, em silêncio.

Aqui a detecção roda contra uma `/sys/class/net` de mentira, com os casos que
quebravam.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AGENTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"

# o mesmo do servidor (server/app/services/machines.py)
MAC_RE = re.compile(r"^[0-9a-f]{2}(-[0-9a-f]{2}){5,7}$")


def _funcoes() -> str:
    """Só as funções de detecção, sem o resto do agente (que exige /etc/.nb3,
    rede e um servidor)."""
    texto = AGENTE.read_text()
    partes = []
    for nome in ("nb3_mac_de", "nb3_detect_mac"):
        inicio = texto.index(f"{nome}() {{")
        fim = texto.index("\n}\n", inicio) + 3
        partes.append(texto[inicio:fim])
    return "\n".join(partes)


class Net:
    """Uma /sys/class/net de mentira."""

    def __init__(self, raiz: Path):
        self.raiz = raiz
        raiz.mkdir()

    def add(self, nome, endereco, *, fisica=True):
        d = self.raiz / nome
        d.mkdir()
        (d / "address").write_text(endereco + "\n")
        if fisica:
            # `device` é o que separa placa de verdade de bridge/veth
            (d / "device").mkdir()

    def __str__(self):
        return str(self.raiz)


@pytest.fixture
def net(tmp_path):
    return Net(tmp_path / "net")


def detectar(net, rota_padrao="") -> str:
    """Roda nb3_detect_mac com um `ip` de mentira no PATH."""
    fakebin = net.raiz.parent / "bin"
    fakebin.mkdir(exist_ok=True)
    ip = fakebin / "ip"
    saida = f"default via 10.0.2.2 dev {rota_padrao} proto dhcp\\n" if rota_padrao else ""
    ip.write_text(f'#!/bin/sh\nprintf "{saida}"\n')
    ip.chmod(0o755)

    script = f'NB3_SYSFS_NET="{net}"\n{_funcoes()}\nnb3_detect_mac\n'
    r = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{fakebin}:/usr/bin:/bin"},
    )
    return r.stdout.strip()


# --- o caso que quebrou ---


def test_a_vm_de_teste_devolve_o_mac_e_nao_o_nome_da_interface(net):
    """`enp0s3` com uma placa só: era daqui que saía `enp0s3\\`."""
    net.add("lo", "00:00:00:00:00:00", fisica=False)
    net.add("enp0s3", "52:54:00:12:34:56")
    mac = detectar(net)
    assert mac == "52-54-00-12-34-56"
    assert MAC_RE.match(mac), "o servidor recusaria isto com 400"


# --- as formas que a saída do `ip` tinha de variar ---


def test_ignora_a_interface_de_loopback(net):
    net.add("lo", "00:00:00:00:00:00", fisica=False)
    net.add("enp7s0", "58:11:22:99:fc:6a")
    assert detectar(net) == "58-11-22-99-fc-6a"


def test_ignora_interfaces_virtuais(net):
    """docker0, veth e bridges têm MAC sorteado a cada boot: reportar por ele
    faria a mesma máquina aparecer como nova toda vez."""
    net.add("docker0", "02:42:ab:cd:ef:01", fisica=False)
    net.add("enp7s0", "58:11:22:99:fc:6a")
    assert detectar(net) == "58-11-22-99-fc-6a"


def test_prefere_a_interface_da_rota_padrao(net):
    """Com cabo e wifi, o que vale é por onde se fala com o servidor."""
    net.add("enp7s0", "58:11:22:99:fc:6a")
    net.add("wlp6s0", "34:6f:24:dc:27:dd")
    assert detectar(net, rota_padrao="wlp6s0") == "34-6f-24-dc-27-dd"


def test_sem_rota_padrao_pega_a_primeira_fisica(net):
    net.add("enp7s0", "58:11:22:99:fc:6a")
    net.add("wlp6s0", "34:6f:24:dc:27:dd")
    assert detectar(net) == "58-11-22-99-fc-6a"


def test_maiusculas_e_dois_pontos_viram_o_formato_do_servidor(net):
    net.add("enp7s0", "58:11:22:99:FC:6A")
    assert detectar(net) == "58-11-22-99-fc-6a"


def test_sem_interface_nenhuma_nao_inventa_valor(net):
    net.add("lo", "00:00:00:00:00:00", fisica=False)
    assert detectar(net) == ""


def test_endereco_zerado_nao_conta(net):
    net.add("enp7s0", "00:00:00:00:00:00")
    assert detectar(net) == ""


# --- o agente não pode martelar o servidor com um MAC inválido ---


def test_sem_mac_valido_o_agente_para_e_diz_por_que():
    texto = AGENTE.read_text()
    assert "SEM MAC VALIDO" in texto
    assert "exit 1" in texto


def test_a_deteccao_nao_conta_campos_da_saida_do_ip():
    """A regressão exata: contar posição em saída de ferramenta."""
    texto = AGENTE.read_text()
    codigo = "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("#"))
    assert "NF-2" not in codigo and "NF - 2" not in codigo
    assert "/sys/class/net" in codigo
