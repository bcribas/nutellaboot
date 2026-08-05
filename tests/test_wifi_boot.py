"""O caminho de wifi do initrd, executado de verdade.

Até aqui nenhum teste jamais rodou `configure_wifi`. O que existia cobria a
GERAÇÃO do wpa_supplicant.conf (texto) e parava ali; associar, esperar, pedir
IP e desistir eram só código. Uma sala mostrou o preço: o rádio associava, o
cliente se desconectava um segundo depois, e o console não dizia por quê.

Aqui o supplicant, o `wpa_cli`, o `dhcpcd`, o `ip` e o `rfkill` são binários de
mentira num PATH temporário, roteirizados por ambiente. Não é rádio de verdade
— é o CONTRATO: quais comandos são chamados, com quais argumentos, em que
ordem, e o que o boot conclui de cada resposta.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO / "client" / "initramfs-tools" / "scripts" / "nutellaboot"

TAB = "\t"

# `configure_networking` do initramfs-tools, na parte que importa. Copiado do
# `scripts/functions` que está DENTRO do initrd construído (initramfs-tools do
# Ubuntu 24.04, linhas 421-465) — em especial o `IP="done"`, que ele grava na
# shell do CHAMADOR e que fazia a segunda chamada, a do wifi, não pedir IP
# nenhum. Se o texto de lá mudar, este pedaço é o que precisa mudar junto.
CONFIGURE_NETWORKING = """
configure_networking() {
    case ${IP} in
        none|done|off) IP="done" ;;
        *) dhcpcd -1KL -t 30 -4 ${DEVICE:+"${DEVICE}"} ;;
    esac
    if [ -z "${DEVICE}" ] && ls "$NB_NETCONF_DIR"/net-*.conf >/dev/null 2>&1 \
        || [ -e "$NB_NETCONF_DIR/net-${DEVICE}.conf" ]; then
        IP="done"
    fi
}
"""

HARNESS = """
export PATH="$FAKEBIN:$PATH"
log_begin_msg() { echo "BEGIN: $*"; }
log_end_msg() { :; }
log_warning_msg() { echo "WARN: $*"; }
log_failure_msg() { echo "FAIL: $*"; }
local_top() { :; }
local_premount() { :; }
local_bottom() { :; }
reboot() { echo "REBOOT-CHAMADO"; exit 0; }
panic() { echo "PANIC: $*"; exit 0; }
""" + CONFIGURE_NETWORKING + """
. "$BOOTSTRAP"
# depois do source: o bootstrap define nb_online, e um stub antes seria
# sobrescrito por ele
nb_online() { [ -e "$FAKE_ONLINE" ]; }
"""

# Cada falso anota o que recebeu. É isso que os testes leem.
FALSOS = {
    "wpa_supplicant": """#!/bin/sh
echo "wpa_supplicant $*" >> "$FAKE_LOG"
[ -n "$FAKE_WPA_CONFLOG" ] && printf '%s\\n' "$FAKE_WPA_CONFLOG" > "$NB_WPA_LOG"
echo 99999999 > "$NB_WPA_PID"
exit "${FAKE_WPA_RC:-0}"
""",
    "wpa_cli": """#!/bin/sh
echo "wpa_cli $*" >> "$FAKE_LOG"
for a in "$@"; do
    case "$a" in
        status) echo "wpa_state=${FAKE_WPA_STATE:-SCANNING}"; echo "ssid=${FAKE_SSID:-}" ;;
        scan_results) printf 'bssid\\tfreq\\tsignal\\tflags\\tssid\\n%s\\n' "${FAKE_SCAN:-}" ;;
    esac
done
exit 0
""",
    # cria o net-<iface>.conf igual ao hook 70-net-conf do dhcpcd de verdade,
    # mas só para as interfaces que o teste mandou dar certo
    "dhcpcd": """#!/bin/sh
echo "dhcpcd $*" >> "$FAKE_LOG"
for a in "$@"; do
    case " $FAKE_DHCP_OK " in
        *" $a "*) echo "IPV4DNS0=10.0.0.1" > "$NB_NETCONF_DIR/net-$a.conf" ;;
    esac
done
exit 0
""",
    "ip": """#!/bin/sh
echo "ip $*" >> "$FAKE_LOG"
exit 0
""",
    "rfkill": """#!/bin/sh
echo "rfkill $*" >> "$FAKE_LOG"
exit 0
""",
    "iw": """#!/bin/sh
echo "iw $*" >> "$FAKE_LOG"
exit 0
""",
    "dmesg": """#!/bin/sh
echo "[    5.1] mt7921e 0000:03:00.0: WM Firmware Version: ____010000, Build Time: 20240826"
""",
}


@pytest.fixture
def sh(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for nome, corpo in FALSOS.items():
        p = fakebin / nome
        p.write_text(corpo)
        p.chmod(0o755)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    netconf = tmp_path / "netconf"
    netconf.mkdir()
    sysnet = tmp_path / "sysnet"
    (sysnet / "eth0").mkdir(parents=True)
    (sysnet / "eth0" / "carrier").write_text("0\n")
    (sysnet / "wlan0" / "wireless").mkdir(parents=True)
    (sysnet / "wlan0" / "device" / "power").mkdir(parents=True)
    (sysnet / "wlan0" / "device" / "power" / "control").write_text("auto\n")
    (tmp_path / "cmdline").write_text("boot=nutellaboot quiet\n")

    def _run(script: str, **env):
        e = {
            "BOOTSTRAP": str(BOOTSTRAP),
            "FAKEBIN": str(fakebin),
            "PATH": "/usr/bin:/bin",
            "NB_RUN": str(run_dir),
            "NB_CFGMNT": str(tmp_path / "cfgmnt"),
            "NB_WPA_CONF": str(tmp_path / "wpa_supplicant.conf"),
            "NB_WPA_CTRL": str(tmp_path / "ctrl"),
            "NB_WPA_PID": str(tmp_path / "wpa.pid"),
            "NB_WPA_LOG": str(tmp_path / "wpa.log"),
            "NB_SYS_NET": str(sysnet),
            "NB_NETCONF_DIR": str(netconf),
            "NB_HOSTS_FILE": str(tmp_path / "hosts"),
            "NB_RESOLV_FILE": str(tmp_path / "resolv.conf"),
            "NB_DEFAULTS_FILE": str(tmp_path / "defaults"),
            "FAKE_LOG": str(tmp_path / "chamadas.log"),
            "FAKE_ONLINE": str(tmp_path / "online"),
            "FAKE_DHCP_OK": "",
            "NB_CMDLINE": str(tmp_path / "cmdline"),
            "NB_WIFI_TIMEOUT": "2",
            "NB_NET_TRIES": "1",
            "NB_FATAL_WAIT": "0",
            "NB_SCREEN_WAIT": "0",
            **{k: str(v) for k, v in env.items()},
        }
        r = subprocess.run(
            ["sh", "-c", HARNESS + "\n" + script],
            capture_output=True,
            text=True,
            env=e,
            timeout=60,
        )
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        return r.stdout + r.stderr

    _run.tmp = tmp_path
    _run.run = run_dir
    _run.sysnet = sysnet
    _run.netconf = netconf
    def _chamadas():
        p = tmp_path / "chamadas.log"
        return p.read_text() if p.is_file() else ""

    _run.chamadas = _chamadas
    _run.wpaconf = lambda: (tmp_path / "wpa_supplicant.conf").read_text()
    _run.wifi = lambda t: (run_dir / "wifi.conf").write_text(t)
    return _run


# --- normalização do wifi.conf ----------------------------------------------


def test_crlf_do_windows_nao_gruda_na_senha(sh):
    """O `\\r` no fim da linha entrava na senha e o handshake falhava com a
    senha CERTA digitada. A limpeza é feita uma vez, na cópia que vai para a
    RAM, porque o arquivo tem dois consumidores (este e o NetworkManager)."""
    cru = sh.tmp / "cru.conf"
    cru.write_text(f"MinhaRede{TAB}senha-boa\r\nOutra{TAB}outra-senha\r\n")
    sh(f'nb_wifi_normalize "{cru}" "$NB_RUN/wifi.conf"')
    limpo = (sh.run / "wifi.conf").read_text()
    assert "\r" not in limpo
    assert f"MinhaRede{TAB}senha-boa{TAB}" in limpo


def test_espaco_sobrando_sai_do_campo(sh):
    cru = sh.tmp / "cru.conf"
    cru.write_text(f"  MinhaRede {TAB} senha-boa  \n")
    sh(f'nb_wifi_normalize "{cru}" "$NB_RUN/wifi.conf"')
    assert (sh.run / "wifi.conf").read_text() == f"MinhaRede{TAB}senha-boa{TAB}\n"


def test_linha_sem_tab_avisa_em_vez_de_adivinhar(sh):
    """Cortar no espaço quebraria quem tem SSID com espaço ("sala de aula"),
    que é legítimo. Avisa — e o relatório de falha mostra o nome tentado."""
    cru = sh.tmp / "cru.conf"
    cru.write_text("MinhaRede senha-boa\n")
    out = sh(f'nb_wifi_normalize "{cru}" "$NB_RUN/wifi.conf"')
    assert "no TAB" in out
    assert (sh.run / "wifi.conf").read_text() == f"MinhaRede senha-boa{TAB}{TAB}\n"


def test_comentario_e_bom_saem(sh):
    cru = sh.tmp / "cru.conf"
    cru.write_bytes(
        "﻿# comentario\n   # indentado\n\nRede\tsenha-boa\n".encode()
    )
    sh(f'nb_wifi_normalize "{cru}" "$NB_RUN/wifi.conf"')
    assert (sh.run / "wifi.conf").read_text() == f"Rede{TAB}senha-boa{TAB}\n"


def test_senha_com_barra_invertida_atravessa_inteira(sh):
    cru = sh.tmp / "cru.conf"
    cru.write_text(f"Rede{TAB}se\\nha\"boa\n")
    sh(f'nb_wifi_normalize "{cru}" "$NB_RUN/wifi.conf"')
    assert (sh.run / "wifi.conf").read_text() == f'Rede{TAB}se\\nha"boa{TAB}\n'


# --- wpa_supplicant.conf gerado ----------------------------------------------


def test_o_bloco_aceita_wpa2_e_wpa3(sh):
    """Roteador atual vem em WPA2/WPA3 misto e EXIGE proteção de quadro de
    gerência. Cliente que só oferece WPA-PSK associa e se desconecta sozinho um
    segundo depois — foi o que a sala viu, nas duas bandas do mesmo roteador."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    sh("nb_write_wpaconf")
    conf = sh.wpaconf()
    assert "key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE" in conf
    assert "ieee80211w=1" in conf
    assert 'psk="senha-boa"' in conf


def test_o_modo_basico_existe_para_supplicant_sem_sae(sh):
    """Um key_mgmt que o binário não conhece invalida o ARQUIVO INTEIRO, não só
    a linha — por isso há um caminho de volta."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    sh("nb_write_wpaconf basico")
    conf = sh.wpaconf()
    assert "key_mgmt=WPA-PSK\n" in conf
    assert "SAE" not in conf
    assert "ieee80211w" not in conf


def test_aspas_e_barras_sao_escapadas(sh):
    sh.wifi(f'Re"de{TAB}se\\nha"boa{TAB}\n')
    sh("nb_write_wpaconf")
    conf = sh.wpaconf()
    assert 'ssid="Re\\"de"' in conf
    assert 'psk="se\\\\nha\\"boa"' in conf


def test_senha_curta_demais_avisa_em_vez_de_sumir(sh):
    """Fora de 8..63 o wpa_supplicant descarta o bloco em silêncio, e o sintoma
    vira "não associou" — sem nada apontando o tamanho."""
    sh.wifi(f"Curta{TAB}1234567{TAB}\nBoa{TAB}senha-boa{TAB}\n")
    out = sh("nb_write_wpaconf")
    assert "8 to 63" in out
    conf = sh.wpaconf()
    assert 'ssid="Curta"' not in conf
    assert 'ssid="Boa"' in conf


def test_chave_de_64_hex_vai_sem_aspas(sh):
    """64 hexadecimais é a chave já derivada, e citá-la faria o wpa_supplicant
    tratar a chave como se fosse uma senha de 64 caracteres."""
    sh.wifi(f"Rede{TAB}{'a1' * 32}{TAB}\n")
    sh("nb_write_wpaconf")
    assert f"psk={'a1' * 32}\n" in sh.wpaconf()


def test_rede_aberta_continua_sem_senha(sh):
    sh.wifi(f"Aberta{TAB}{TAB}\n")
    sh("nb_write_wpaconf")
    conf = sh.wpaconf()
    assert "key_mgmt=NONE" in conf
    assert "psk=" not in conf


# --- a interface -------------------------------------------------------------


def test_a_interface_sai_da_capacidade_e_nao_do_nome(sh):
    """`ip -o link | /: w/` pegava qualquer nome começando com w: um `wwan0` de
    modem 4G ganha da wlan0 na ordem do kernel, e o boot ia associar num
    modem."""
    (sh.sysnet / "wwan0").mkdir()
    assert sh("nb_wifi_iface").strip() == "wlan0"


def test_sem_placa_sem_fio_configure_wifi_desiste(sh, tmp_path):
    vazio = tmp_path / "so-eth"
    (vazio / "eth0").mkdir(parents=True)
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh(
        'if configure_wifi; then echo SUBIU; else echo DESISTIU; fi',
        NB_SYS_NET=str(vazio),
    )
    assert "DESISTIU" in out
    assert "wpa_supplicant" not in sh.chamadas()


# --- associação --------------------------------------------------------------


def test_associou_exporta_o_device_para_o_dhcp(sh):
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh('configure_wifi && echo "DEVICE=$DEVICE"', FAKE_WPA_STATE="COMPLETED")
    assert "DEVICE=wlan0" in out
    chamadas = sh.chamadas()
    assert "-iwlan0" in chamadas
    assert str(sh.tmp / "wpa_supplicant.conf") in chamadas, "usou o config gerado"


def test_nao_associou_conta_o_motivo(sh):
    """A pergunta que o console não respondia. O log do supplicant ia para um
    arquivo e morria com o initrd."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh(
        "configure_wifi; echo \"REASON=$NB_WIFI_REASON\"",
        FAKE_WPA_STATE="4WAY_HANDSHAKE",
        FAKE_WPA_CONFLOG="WPA: 4-Way Handshake failed - pre-shared key may be incorrect",
    )
    assert "did not associate" in out
    assert "pre-shared key may be incorrect" in out
    assert "refused the password" in out
    assert "wifi state: 4WAY_HANDSHAKE" in out


def test_o_motivo_distingue_pmf_de_senha(sh):
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh(
        "configure_wifi; echo \"REASON=$NB_WIFI_REASON\"",
        FAKE_WPA_CONFLOG="RSN: Management frame protection required but the driver does not support it",
    )
    assert "REASON=the access point requires WPA3 protection (PMF)" in out


def test_o_relatorio_nunca_imprime_a_senha(sh):
    sh.wifi(f"Rede{TAB}senha-secretissima{TAB}\n")
    out = sh(
        "configure_wifi || true",
        FAKE_WPA_CONFLOG="WPA: 4-Way Handshake failed - pre-shared key may be incorrect",
    )
    assert "senha-secretissima" not in out
    assert "Rede" in out, "o NOME da rede ajuda quem está na sala"
    # o TAMANHO vai, e é o que denuncia espaço invisível no fim do campo
    assert "password: 18 chars" in out


def test_supplicant_que_recusa_o_config_tenta_o_modo_basico(sh):
    """wpa_supplicant sem SAE compilado rejeita o arquivo inteiro. Uma segunda
    tentativa, com o mínimo — e só uma, senão vira laço."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_wifi; echo FIM", FAKE_WPA_RC="1")
    assert "retrying without WPA3" in out
    subiu = [l for l in sh.chamadas().splitlines() if l.startswith("wpa_supplicant ")]
    assert len(subiu) == 2, subiu
    assert "SAE" not in sh.wpaconf()


def test_nao_sobe_um_segundo_supplicant_na_mesma_interface(sh):
    """Dois processos disputando o mesmo rádio dão associação e queda em laço.
    A partir da segunda rodada de configure_localnetwork o antigo está vivo."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh(
        'echo $$ > "$NB_WPA_PID"; configure_wifi && echo OK',
        FAKE_WPA_STATE="COMPLETED",
    )
    assert "OK" in out
    chamadas = sh.chamadas()
    assert "wpa_supplicant" not in chamadas
    assert "reassociate" in chamadas


# --- a rede inteira ----------------------------------------------------------


def test_lease_cabeado_inutil_nao_pode_matar_o_dhcp_do_wifi(sh):
    """A regressão que este arquivo existe para segurar.

    `configure_networking` roda na NOSSA shell e marca `IP=done` assim que
    existe um net-*.conf. Sem restaurar, a chamada seguinte — a do wifi — não
    pede IP nenhum: basta a porta cabeada pegar um lease que não alcança o
    servidor (switch sem uplink, VLAN errada, portal cativo) para o wifi ficar
    sem endereço para sempre, sem nada na tela dizendo isso.
    """
    (sh.sysnet / "eth0" / "carrier").write_text("1\n")
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    sh(
        "configure_localnetwork",
        FAKE_WPA_STATE="COMPLETED",
        FAKE_DHCP_OK="eth0",  # o cabo pega IP; o servidor continua mudo
    )
    chamadas = sh.chamadas()
    assert "dhcpcd -1KL -t 30 -4 wlan0" in chamadas, (
        "o wifi associou e ninguém pediu IP nele:\n" + chamadas
    )


def test_sem_cabo_o_wifi_vem_primeiro(sh):
    """Sem carrier, o dhcpcd cabeado gasta 30+60+90+120 s ANTES de o rádio ser
    tentado — cinco minutos por rodada, medidos no console de uma sala."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_localnetwork", FAKE_WPA_STATE="COMPLETED")
    assert "no cable detected" in out
    chamadas = sh.chamadas()
    assert chamadas.index("wpa_supplicant") < chamadas.index("dhcpcd")


def test_com_cabo_o_caminho_cabeado_continua_primeiro(sh):
    """É ele que boota todas as salas."""
    (sh.sysnet / "eth0" / "carrier").write_text("1\n")
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_localnetwork", FAKE_WPA_STATE="COMPLETED")
    assert "no cable detected" not in out
    assert sh.chamadas().index("dhcpcd") < sh.chamadas().index("wpa_supplicant")


def test_placa_que_nao_reporta_carrier_fica_no_caminho_cabeado(sh):
    """Só quem responde 0 explicitamente é considerado sem link."""
    (sh.sysnet / "eth0" / "carrier").unlink()
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_localnetwork", FAKE_WPA_STATE="COMPLETED")
    assert "no cable detected" not in out


def test_rede_que_sobe_encerra_sem_tela_de_erro(sh):
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh(
        'touch "$FAKE_ONLINE"; configure_localnetwork && echo ONLINE',
        FAKE_WPA_STATE="COMPLETED",
    )
    assert "ONLINE" in out
    assert "REBOOT-CHAMADO" not in out


def test_falha_de_wifi_tem_tela_propria(sh):
    """"Confira o cabo e o switch" manda procurar no lugar errado quem está
    tentando por wifi."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh(
        "configure_localnetwork",
        FAKE_WPA_CONFLOG="WPA: 4-Way Handshake failed - pre-shared key may be incorrect",
    )
    assert "could not connect to the wireless network" in out
    assert "refused the password" in out
    assert "REBOOT-CHAMADO" in out


def test_wifi_conectado_sem_dhcp_diz_isso(sh):
    """Associou e o DHCP não veio: é outro problema, e outra ação."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_localnetwork", FAKE_WPA_STATE="COMPLETED")
    assert "no address came from DHCP" in out


def test_sem_wifi_conf_a_tela_e_a_de_sempre(sh):
    """Sede sem rede sem fio configurada continua vendo cabo, switch e DHCP."""
    out = sh("configure_localnetwork")
    assert "could not reach the network" in out
    assert "could not connect to the wireless network" not in out


def test_o_contador_de_rodadas_nao_e_o_do_wifi(sh):
    """`configure_wifi` usava `_n`, o MESMO nome do contador de rodadas de
    `configure_localnetwork`: uma passagem pelo wifi punha o contador em 30 e
    as 10 tentativas viravam uma. É a família do `sleep RAM` do 05-ui.sh."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_localnetwork", NB_NET_TRIES="3", NB_WIFI_TIMEOUT="1")
    assert out.count("no cable detected") == 3


# --- o wpa_supplicant de verdade --------------------------------------------


@pytest.mark.skipif(
    not shutil.which("wpa_supplicant"), reason="wpa_supplicant não instalado aqui"
)
def test_um_wpa_supplicant_de_verdade_aceita_o_arquivo_gerado(sh):
    """Os falsos acima provam o contrato; este prova a SINTAXE.

    Um `key_mgmt` que o binário não conhece invalida o bloco inteiro — e é uma
    linha de log que ninguém vê, porque o log do supplicant morre com o initrd.
    Aqui o arquivo gerado passa por um wpa_supplicant real: ele falha só ao
    abrir a interface que não existe, o que quer dizer que a configuração foi
    lida e aceita antes disso.
    """
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\nOculta{TAB}outra-senha{TAB}hidden\nAberta{TAB}{TAB}\n")
    sh("nb_write_wpaconf")
    conf = sh.tmp / "wpa_supplicant.conf"
    r = subprocess.run(
        ["wpa_supplicant", "-c", str(conf), "-i", "nb3-nao-existe"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    saida = r.stdout + r.stderr
    assert "failed to parse network block" not in saida, saida
    assert "invalid key_mgmt" not in saida, saida
    assert "Failed to initialize driver interface" in saida, (
        "parou antes de chegar na interface — o arquivo não foi aceito:\n" + saida
    )


# --- as mitigações do mt792x -------------------------------------------------
#
# Uma MT7922 de sala falhou o 4-way em DUAS redes WPA2 — uma delas um hotspot
# lançado só para o teste, com o tamanho da senha confirmado na tela. A família
# mt792x tem histórico documentado de firmware cochilando no meio do handshake
# (upstream chegou a desligar o power-save por padrão no mt7921), e o
# supplicant carimba WRONG_KEY com a senha certa.


def test_power_save_e_desligado_antes_do_supplicant(sh):
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    sh("configure_wifi", FAKE_WPA_STATE="COMPLETED")
    chamadas = sh.chamadas()
    assert "iw dev wlan0 set power_save off" in chamadas
    assert chamadas.index("set power_save off") < chamadas.index("wpa_supplicant"), (
        "desligar depois de conectar não salva o handshake"
    )
    # e o runtime-PM do dispositivo, que não depende do iw existir
    assert (sh.sysnet / "wlan0" / "device" / "power" / "control").read_text() == "on\n"


def test_sem_iw_o_wifi_segue(sh):
    """O iw entra no initrd SE a imagem-mestre o tiver. A falta dele não pode
    derrubar o rádio — o caminho do sysfs continua."""
    (sh.tmp / "bin" / "iw").unlink()
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_wifi && echo SUBIU", FAKE_WPA_STATE="COMPLETED")
    assert "SUBIU" in out
    assert (sh.sysnet / "wlan0" / "device" / "power" / "control").read_text() == "on\n"


def test_handshake_que_nao_fecha_tenta_o_modo_basico(sh):
    """Não só quando o supplicant nem sobe: há driver e AP que tropeçam nos
    AKMs extras ou no bit de PMF DEPOIS de associar. A segunda tentativa usa o
    mesmo supplicant (reconfigure), com o bloco mínimo — e só uma vez."""
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_wifi; echo FIM")  # nunca chega a COMPLETED
    assert "retrying with plain WPA2" in out
    chamadas = sh.chamadas()
    assert "reconfigure" in chamadas
    assert chamadas.count("reconfigure") == 1, "uma tentativa extra, não um laço"
    # a segunda escrita do arquivo é a básica
    conf = sh.wpaconf()
    assert "SAE" not in conf and "ieee80211w" not in conf


def test_o_relatorio_traz_a_impressao_digital_da_senha(sh):
    """Nunca a senha — o md5 curto dos bytes exatos. Quem está na sala compara
    com `printf '%s' 'senha' | md5sum` e fecha a dúvida de uma vez."""
    import hashlib

    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("nb_wifi_report")
    fp = hashlib.md5(b"senha-boa").hexdigest()[:8]
    assert f"fingerprint {fp}" in out
    assert "senha-boa" not in out


def test_o_relatorio_diz_o_hardware(sh):
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("nb_wifi_report")
    assert "mt7921e" in out, "a foto da falha precisa dizer qual rádio e firmware"


def test_nbwifidebug_liga_o_dd_e_despeja_o_log(sh):
    (sh.tmp / "cmdline").write_text("boot=nutellaboot nbwifidebug=y\n")
    (sh.tmp / "wpa.log").write_text("linha-um\nlinha-final-do-log\n")
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_wifi; echo FIM")
    assert "-dd" in sh.chamadas().splitlines()[
        [i for i, l in enumerate(sh.chamadas().splitlines()) if l.startswith("wpa_supplicant")][0]
    ]
    assert "linha-final-do-log" in out


def test_sem_a_flag_nao_ha_dd_nem_despejo(sh):
    (sh.tmp / "wpa.log").write_text("linha-que-nao-deve-aparecer\n")
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_wifi; echo FIM")
    primeira = [l for l in sh.chamadas().splitlines() if l.startswith("wpa_supplicant")][0]
    assert "-dd" not in primeira
    assert "linha-que-nao-deve-aparecer" not in out


def test_conectou_diz_em_qual_modo(sh):
    sh.wifi(f"Rede{TAB}senha-boa{TAB}\n")
    out = sh("configure_wifi", FAKE_WPA_STATE="COMPLETED")
    assert "(full config)" in out
