"""Testa a lógica de configuração do bootstrap do initrd.

O script roda dentro do initramfs, mas as partes que decidem IMAGEROOT,
NB_SERVER, /etc/hosts e wpa_supplicant.conf são shell puro e podem (devem)
ser testadas aqui — é justamente onde um erro deixa a sala inteira sem boot.
Os caminhos são parametrizados no próprio script (NB_WPA_CONF, NB_HOSTS_FILE,
NB_CFGMNT...), então exercitamos as funções DE VERDADE, não uma cópia delas.
"""

import re
import shutil
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


def test_le_o_pendrive_sem_head_no_caminho(tmp_path):
    """O initrd não tem `head`, e a falta dele não aparece como erro: o pipe
    morre com "head: not found" e a variável fica VAZIA.

    Foi assim que todo valor do pendrive voltava em branco — o pendrive
    genérico caía na tela "NO IMAGE" com o arquivo preenchido, e o de sede
    ignorava o servidor configurado e ia para o padrão embutido. Visto num
    boot de verdade em qemu, nunca por um teste.

    Aqui o PATH tem só o mínimo, sem `head`: se alguém reintroduzir a
    dependência, este teste cai.
    """
    magro = tmp_path / "bin"
    magro.mkdir()
    # o que o initrd de verdade tem (visto no boot em qemu): sed, tr, awk e
    # grep rodaram; só `head` não estava lá
    disponiveis = [
        "sh", "sed", "tr", "awk", "grep", "cat", "cut", "sleep", "ip",
        "mkdir", "rm", "cp", "mv", "sync",
    ]
    for nome in disponiveis:
        alvo = shutil.which(nome)
        if alvo:
            (magro / nome).symlink_to(alvo)
    assert not (magro / "head").exists()

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "nutellaboot.conf").write_text(
        "# comentário\nIMAGEROOT=25brbr\nNB_BOOT_KEY=nb3b_abc\nNB_SERVER=https://exemplo.test/\n"
    )
    script = HARNESS + '\nnb_read_usbconfig; echo "I=$IMAGEROOT K=$NB_BOOT_KEY S=$NB_SERVER"'
    r = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        env={
            "BOOTSTRAP": str(BOOTSTRAP),
            "FAKEBIN": str(magro),
            "PATH": str(magro),
            "NB_RUN": str(run_dir),
            "NB_HOSTS_FILE": str(tmp_path / "hosts"),
            "NB_DEFAULTS_FILE": str(tmp_path / "defaults"),
            "NB_CFG_TRIES": "1",
            "NB_CFG_WAIT": "0",
        },
    )
    assert "not found" not in r.stderr, r.stderr
    assert "I=25brbr" in r.stdout, r.stdout
    assert "K=nb3b_abc" in r.stdout, r.stdout
    assert "S=https://exemplo.test" in r.stdout, r.stdout


def test_a_identidade_da_construcao_viaja_dentro_do_initrd():
    """É o que permite à máquina saber que o pendrive de onde ela bootou está
    velho. O hook copia o carimbo e o bootstrap o exporta; sem o arquivo (todo
    initrd anterior a isto) a variável fica VAZIA — e o stuff não confere nada,
    porque recusar quem não sabe a própria versão seria recusar todos os
    pendrives já gravados de uma vez."""
    hook = HOOK.read_text()
    assert "/etc/nutellaboot-build" in hook, "o hook não põe o carimbo no initrd"

    boot = BOOTSTRAP.read_text()
    assert "NB_INITRD_BUILD" in boot
    assert "export" in boot[boot.index("NB_INITRD_BUILD") :][:400], "o carimbo não é exportado"

    ferramenta = (REPO / "tools" / "nb3-build-initrd").read_text()
    # gravado ANTES do update-initramfs, senão não entra no arquivo
    # (o `index` do comando, não o da menção no cabeçalho)
    assert ferramenta.index("nb3-build-id") < ferramenta.index('chroot "$MNT" update-initramfs')
    assert "build.json" in ferramenta, "o servidor precisa do md5 para o cliente conferir"


def test_o_carimbo_ausente_nao_quebra_o_boot(tmp_path):
    """Initrd construído antes disto não tem o arquivo. `sed` num arquivo que
    não existe tem que dar string vazia, não erro."""
    r = subprocess.run(
        ["sh", "-c", 'B=$(sed -n 1p /nao/existe/nutellaboot-build 2> /dev/null); echo "B=[$B]"'],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "B=[]" in r.stdout


HOOK = REPO / "client" / "initramfs-tools" / "hooks" / "nutellaboot"

# O que o initramfs-tools já põe no initrd (busybox/klibc) — visto rodando numa
# máquina de verdade. `head` NÃO estava aqui, e foi o que apagou em silêncio
# tudo que vinha do pendrive.
DO_INITRD = {
    "sh", "echo", "printf", "cat", "cp", "mv", "rm", "mkdir", "rmdir", "ln",
    "ls", "sed", "awk", "grep", "tr", "cut", "sort", "uniq", "wc", "sleep",
    "kill", "wait", "test", "true", "false", "sync", "chmod", "chown", "dd",
    "mount", "umount", "mountpoint", "df", "free", "modprobe", "udevadm",
    "ip", "hostname", "date", "readlink", "basename", "dirname", "mktemp",
    "logger", "reboot", "poweroff", "run-parts", "find", "xargs", "id",
    "sysctl", "swapoff", "mkswap", "touch", "seq", "env", "tee", "stty",
}


def _copiados_pelo_hook() -> set[str]:
    nomes = set()
    for m in re.finditer(r"copy_exec\s+(\S+)(?:\s+(\S+))?", HOOK.read_text()):
        origem, destino = m.group(1), m.group(2) or ""
        # `copy_exec /usr/bin/wget /usr/bin/wget.good` renomeia
        nomes.add(Path(destino).name if destino and "." in Path(destino).name else Path(origem).name)
    return nomes


def _sem_heredoc(texto: str) -> str:
    """Tira o corpo dos heredocs: aquilo é conteúdo escrito para dentro do
    sistema montado (scripts de rc.local.d, arquivos de configuração), não
    comando que roda no initrd."""
    saida, pulando, fim = [], False, None
    for linha in texto.splitlines():
        if pulando:
            if linha.strip() == fim:
                pulando = False
            continue
        m = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", linha)
        if m:
            pulando, fim = True, m.group(1)
        saida.append(linha)
    return "\n".join(saida)


def _comandos_usados(path: Path) -> set[str]:
    """Comandos chamados DENTRO DE PIPE ou de substituição — que é onde a
    ausência é muda.

    Um comando inexistente no começo de uma linha ao menos imprime "not found"
    e costuma derrubar o `if` que o cerca. Num pipe, não: o pedaço morre, a
    saída vem vazia e o boot segue com a variável em branco. Foi assim com o
    `| head -n1`, por 30 horas. Restringir a estes dois casos deixa o teste
    quase sem falso positivo — e ele existe para essa classe de erro.
    """
    usados = set()
    for linha in _sem_heredoc(path.read_text()).splitlines():
        if linha.lstrip().startswith("#"):
            continue
        linha = re.sub(r"#.*$", "", linha)
        # texto entre aspas não é comando: as mensagens do diskslog são cheias
        # de `|` ("$disk|$fstype|mounted read-only")
        linha = re.sub(r"'[^']*'", "''", linha)
        linha = re.sub(r'"[^"]*"', '""', linha)
        # padrão de `case`: `ext3 | ext4 | ntfs)` são rótulos, não pipes
        if re.match(r"^\s*[\w*?.\[\]| -]+\)", linha):
            continue
        for m in re.finditer(r"(?:\|\s*|\$\(\s*)([a-z][a-z0-9._-]*)\s", linha):
            usados.add(m.group(1))
    return usados


def test_todo_comando_do_caminho_de_boot_existe_no_initrd():
    """A falha de um comando que não está lá é MUDA: o pipe morre, a variável
    fica vazia e o boot segue com o valor errado. Foi assim com o `head`.

    Se um comando novo aparecer, ou ele entra nesta lista (porque o initramfs
    o traz) ou o hook passa a copiá-lo — as duas coisas são uma linha."""
    conhecidos = DO_INITRD | _copiados_pelo_hook()
    # funções do próprio projeto e palavras de shell não são comandos externos
    definidas = set()
    for path in CLIENT_SH:
        definidas |= set(re.findall(r"^([a-z][a-z0-9_]*)\s*\(\)", path.read_text(), re.M))
    definidas |= {
        "log_begin_msg", "log_end_msg", "log_warning_msg", "log_failure_msg",
        "panic", "configure_networking", "local_top", "local_premount",
        "local_bottom", "wait_for_udev", "run_scripts",
    }
    palavras = {
        "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
        "done", "case", "esac", "in", "function", "return", "exit", "shift",
        "local", "set", "unset", "export", "read", "eval", "exec", "trap",
        "break", "continue", "command", "type", "source", "cd", "pwd", "wait",
        "kill", "jobs", "umask", "alias", "time", "let", "declare", "typeset",
    }

    faltando = {}
    for path in CLIENT_SH:
        for cmd in _comandos_usados(path) - conhecidos - definidas - palavras:
            faltando.setdefault(cmd, []).append(path.name)
    assert not faltando, (
        "comandos sem garantia de existir no initrd: "
        + "; ".join(f"{c} ({', '.join(sorted(set(f)))})" for c, f in sorted(faltando.items()))
    )


def test_nenhum_script_de_boot_depende_de_head():
    """`head` volta a ser copiado pelo hook, mas nenhum script deve depender
    dele: um initrd construído noutro ambiente pode não o ter, e a falha é
    silenciosa."""
    for path in CLIENT_SH:
        # fora dos comentários: eles contam a história e citam o comando
        codigo = "\n".join(
            l for l in path.read_text().splitlines() if not l.lstrip().startswith("#")
        )
        assert "| head" not in codigo and "head -n" not in codigo, path.name


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
