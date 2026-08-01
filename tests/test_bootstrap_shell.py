"""Testa a lógica de configuração do bootstrap do initrd.

O script roda dentro do initramfs, mas as partes que decidem IMAGEROOT,
NB_SERVER, /etc/hosts e wpa_supplicant.conf são shell puro e podem (devem)
ser testadas aqui — é justamente onde um erro deixa a sala inteira sem boot.
Os caminhos são parametrizados no próprio script (NB_WPA_CONF, NB_HOSTS_FILE,
NB_CFGMNT...), então exercitamos as funções DE VERDADE, não uma cópia delas.
"""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO / "client" / "initramfs-tools" / "scripts" / "nutellaboot"
CLIENT_SH = [BOOTSTRAP, *sorted((REPO / "client" / "stuff").rglob("*.sh"))]

# Sem `set -e`: o /init do initramfs-tools também não usa, e o script depende
# disso (padrões como `[ -f x ] && cp x y` retornam 1 quando o arquivo falta).
HARNESS = """
export PATH="$FAKEBIN:$PATH"
log_begin_msg() { :; }
log_end_msg() { :; }
log_warning_msg() { echo "WARN: $*"; }
log_failure_msg() { echo "FAIL: $*"; }
configure_networking() { :; }
local_top() { :; }
local_premount() { :; }
local_bottom() { :; }
reboot() { echo "REBOOT-CHAMADO"; exit 0; }
panic() { echo "PANIC: $*"; exit 0; }
. "$BOOTSTRAP"
"""


@pytest.fixture
def sh(tmp_path):
    """Executa trechos do bootstrap com caminhos redirecionados para tmp."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for tool in ("blkid", "mount", "umount", "rfkill"):
        p = fakebin / tool
        p.write_text("#!/bin/sh\nexit 1\n")
        p.chmod(0o755)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def _run(script: str, **env):
        full = HARNESS + "\n" + script
        e = {
            "BOOTSTRAP": str(BOOTSTRAP),
            "FAKEBIN": str(fakebin),
            "PATH": "/usr/bin:/bin",
            "NB_RUN": str(run_dir),
            "NB_CFGMNT": str(tmp_path / "cfgmnt"),
            "NB_WPA_CONF": str(tmp_path / "wpa_supplicant.conf"),
            "NB_HOSTS_FILE": str(tmp_path / "hosts"),
            "NB_RESOLV_FILE": str(tmp_path / "resolv.conf"),
            "NB_DEFAULTS_FILE": str(tmp_path / "defaults"),
            # sem espera de enumeração de USB nem de reboot nos testes
            "NB_CFG_TRIES": "1",
            "NB_CFG_WAIT": "0",
            "NB_FATAL_WAIT": "0",
            **{k: str(v) for k, v in env.items()},
        }
        r = subprocess.run(["sh", "-c", full], capture_output=True, text=True, env=e)
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        return r.stdout

    _run.tmp = tmp_path
    _run.run_dir = run_dir
    return _run


def test_bootstrap_is_valid_sh():
    subprocess.run(["sh", "-n", str(BOOTSTRAP)], check=True)


def test_all_client_scripts_are_valid_sh():
    for path in CLIENT_SH:
        subprocess.run(["sh", "-n", str(path)], check=True)


def test_wpaconf_from_wifi_conf(sh):
    (sh.run_dir / "wifi.conf").write_text(
        "# comentário\nICPC-BR\tsenha-secreta\nICPC-BR-EMG\noculta\toutra\thidden\n"
    )
    out = sh('nb_write_wpaconf; cat "$NB_WPA_CONF"')
    assert 'ssid="ICPC-BR"' in out
    assert 'psk="senha-secreta"' in out
    # rede aberta não pode ganhar psk
    emg = out.split('ssid="ICPC-BR-EMG"')[1].split("}")[0]
    assert "key_mgmt=NONE" in emg and "psk=" not in emg
    # rede oculta precisa de scan_ssid para ser encontrada
    assert "scan_ssid=1" in out.split('ssid="oculta"')[1].split("}")[0]
    assert "comentário" not in out


def test_wpaconf_absent_wifi_conf(sh):
    out = sh("if nb_write_wpaconf; then echo GEROU; else echo NAOGEROU; fi")
    assert "NAOGEROU" in out


def test_usbconfig_reads_pendrive(sh):
    (sh.run_dir / "nutellaboot.conf").write_text(
        "IMAGEROOT=25brbr\nNB_SERVER=https://exemplo.test/\n"
    )
    out = sh('nb_read_usbconfig; echo "I=$IMAGEROOT S=$NB_SERVER"')
    assert "I=25brbr" in out
    assert "S=https://exemplo.test" in out  # barra final removida


def test_usbconfig_cmdline_beats_pendrive(sh):
    (sh.run_dir / "nutellaboot.conf").write_text("IMAGEROOT=doPendrive\n")
    out = sh('IMAGEROOT=daCmdline; nb_read_usbconfig; echo "I=$IMAGEROOT"')
    assert "I=daCmdline" in out


def test_usbconfig_falls_back_to_builtin_defaults(sh):
    (sh.tmp / "defaults").write_text("NB_SERVER=https://padrao.embutido\n")
    (sh.run_dir / "nutellaboot.conf").write_text("IMAGEROOT=x\n")
    out = sh('nb_read_usbconfig; echo "S=$NB_SERVER"')
    assert "S=https://padrao.embutido" in out


def test_usbconfig_without_imageroot_reboots(sh):
    """Sem IMAGEROOT não há o que bootar: avisa e reinicia (nunca trava)."""
    out = sh("NB_FATAL_WAIT=0; nb_read_usbconfig; echo NAO-DEVERIA-CHEGAR-AQUI")
    assert "REBOOT-CHAMADO" in out
    assert "NAO-DEVERIA-CHEGAR-AQUI" not in out


def test_nb_hosts_pin(sh):
    """NB_HOSTS vira linha de /etc/hosts — é o que permite testar em qemu
    (SLIRP, host em 10.0.2.2) sem abrir mão da validação de certificado."""
    (sh.run_dir / "nutellaboot.conf").write_text(
        "IMAGEROOT=x\nNB_HOSTS=nutellaboot.charge.naquadah.com.br 10.0.2.2\n"
    )
    sh("nb_read_usbconfig")
    assert "10.0.2.2 nutellaboot.charge.naquadah.com.br" in (sh.tmp / "hosts").read_text()


def test_no_interactive_read_in_client_scripts():
    """Regressão do nb2: `read` esperando teclado trava máquina desatendida —
    o boot da sala inteira parava num "Press ENTER to continue"."""
    offenders = []
    for path in CLIENT_SH:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if (s == "read" or s.startswith("read ")) and "<" not in s:
                offenders.append(f"{path.name}:{n}: {s}")
    assert offenders == [], "read interativo: " + "; ".join(offenders)


def test_no_disabled_certificate_check():
    """Nenhum download de conteúdo pode desligar a verificação de certificado.
    Exceção única e documentada: /boot/v3/time, que existe para CORRIGIR o
    relógio e assim tornar a validação possível."""
    bad = []
    for path in CLIENT_SH:
        lines = path.read_text().splitlines()
        for n, line in enumerate(lines):
            s = line.strip()
            if s.startswith("#"):
                continue
            if "check-certificate=false" in s or "--no-check-certificate" in s:
                janela = "\n".join(lines[n : n + 3])
                if "boot/v3/time" not in janela:
                    bad.append(f"{path.name}:{n + 1}")
    assert bad == [], "verificação de certificado desligada em: " + ", ".join(bad)


def test_stuff_does_not_redefine_network_functions():
    """A regressão que matou o wifi no nb2: o stuff servido sobrescrevia
    configure_localnetwork() e, ao fazê-lo, deixava de chamar configure_wifi().
    No v3 a rede pertence ao bootstrap; o stuff não pode redefini-la."""
    proibidas = ("configure_localnetwork", "configure_wifi", "nb_write_wpaconf")
    bad = []
    for path in (REPO / "client" / "stuff").rglob("*.sh"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for fn in proibidas:
                if line.strip().startswith(f"{fn}()") or line.strip().startswith(f"{fn} ()"):
                    bad.append(f"{path.name}:{n}: {fn}")
    assert bad == [], "stuff redefine função de rede: " + "; ".join(bad)
