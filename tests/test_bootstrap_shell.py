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
    for tool in ("blkid", "mount", "umount", "rfkill", "udevadm"):
        p = fakebin / tool
        p.write_text("#!/bin/sh\nexit 1\n")
        p.chmod(0o755)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def _stub(nome: str, corpo: str) -> None:
        p = fakebin / nome
        p.write_text("#!/bin/sh\n" + corpo)
        p.chmod(0o755)

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
            "NB_USB_LIVRE_MARK": str(tmp_path / "usb-livre"),
            "NB_USB_LIVRE_WAIT": "0",
            # o conf do netboot, que só existe quando o teste o cria
            "NB_NETCONF": str(tmp_path / "netboot" / "nutellaboot.conf"),
            **{k: str(v) for k, v in env.items()},
        }
        r = subprocess.run(["sh", "-c", full], capture_output=True, text=True, env=e)
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        return r.stdout

    _run.tmp = tmp_path
    _run.run_dir = run_dir
    _run.stub = _stub
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
            "NB_NETCONF": str(tmp_path / "sem-netboot"),
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
        # fora dos comentários (eles contam a história e citam o comando) e
        # fora dos heredocs (conteúdo gravado no sistema montado, onde o
        # `head` de verdade existe)
        codigo = "\n".join(
            l for l in _sem_heredoc(path.read_text()).splitlines()
            if not l.lstrip().startswith("#")
        )
        assert "| head" not in codigo and "head -n" not in codigo, path.name


def test_wpaconf_from_wifi_conf(sh):
    # as senhas têm 8 caracteres ou mais porque é o que o WPA aceita: abaixo
    # disso o wpa_supplicant descarta o bloco, e agora o gerador avisa e pula
    # (tests/test_wifi_boot.py). O "outra" de antes nunca teria funcionado numa
    # sala.
    (sh.run_dir / "wifi.conf").write_text(
        "# comentário\nICPC-BR\tsenha-secreta\nICPC-BR-EMG\noculta\toutra-senha\thidden\n"
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
        "IMAGEROOT=25brbr\nNB_BOOT_KEY=nb3b_x\nNB_SERVER=https://exemplo.test/\n"
    )
    out = sh('nb_read_usbconfig; echo "I=$IMAGEROOT S=$NB_SERVER"')
    assert "I=25brbr" in out
    assert "S=https://exemplo.test" in out  # barra final removida


def test_usbconfig_cmdline_beats_pendrive(sh):
    (sh.run_dir / "nutellaboot.conf").write_text("IMAGEROOT=doPendrive\nNB_BOOT_KEY=nb3b_x\n")
    out = sh('IMAGEROOT=daCmdline; nb_read_usbconfig; echo "I=$IMAGEROOT"')
    assert "I=daCmdline" in out


def test_usbconfig_falls_back_to_builtin_defaults(sh):
    (sh.tmp / "defaults").write_text("NB_SERVER=https://padrao.embutido\n")
    (sh.run_dir / "nutellaboot.conf").write_text("IMAGEROOT=x\nNB_BOOT_KEY=nb3b_x\n")
    out = sh('nb_read_usbconfig; echo "S=$NB_SERVER"')
    assert "S=https://padrao.embutido" in out


def test_usbconfig_without_imageroot_reboots(sh):
    """Sem IMAGEROOT não há o que bootar: avisa e reinicia (nunca trava)."""
    (sh.run_dir / "nutellaboot.conf").write_text("NB_BOOT_KEY=nb3b_x\n")
    out = sh("NB_FATAL_WAIT=0; nb_read_usbconfig; echo NAO-DEVERIA-CHEGAR-AQUI")
    assert "REBOOT-CHAMADO" in out
    assert "does not say which image" in out or "NO IMAGE" in out or "IMAGEROOT" in out
    assert "NAO-DEVERIA-CHEGAR-AQUI" not in out


def test_nb_hosts_pin(sh):
    """NB_HOSTS vira linha de /etc/hosts — é o que permite testar em qemu
    (SLIRP, host em 10.0.2.2) sem abrir mão da validação de certificado."""
    (sh.run_dir / "nutellaboot.conf").write_text(
        "IMAGEROOT=x\nNB_BOOT_KEY=nb3b_x\nNB_HOSTS=nutellaboot.charge.naquadah.com.br 10.0.2.2\n"
    )
    sh("nb_read_usbconfig")
    assert "10.0.2.2 nutellaboot.charge.naquadah.com.br" in (sh.tmp / "hosts").read_text()


def test_no_interactive_read_in_client_scripts():
    """Regressão do nb2: `read` esperando teclado trava máquina desatendida —
    o boot da sala inteira parava num "Press ENTER to continue".

    Exceção única e deliberada: o hold do modo seed (50-seed.sh). É opt-in da
    sede (SEEDIMAGE), o `read` tem timeout de 1 s, e a saída desatendida é
    garantida pela liberação remota no configureitor — segurar o boot ali é a
    função, não um esquecimento. Qualquer outro `read` de teclado (sem
    redirecionamento, ou lendo de /dev/console ou /dev/tty) continua proibido,
    inclusive atrás de `if`. (`while read` fica de fora: é o padrão
    estabelecido de consumir pipe/arquivo, com o redirecionamento no `done`.)"""
    offenders = []
    for path in CLIENT_SH:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if not re.match(r"(?:if\s+|elif\s+)?read(?:\s|$)", s):
                continue
            if "<" in s and not re.search(r"<\s*/dev/(console|tty)", s):
                continue  # lê de arquivo/pipe, não de teclado
            if path.name == "50-seed.sh" and re.search(r"read\s+-r\s+-t\s+\d", s):
                continue  # a exceção documentada acima
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


def test_o_hook_leva_os_templates_de_crypto_do_wifi():
    """O mac80211 pede ccm(aes) por request_module ao instalar a chave do
    4-way: nenhuma dependência de símbolo os arrasta, e o MODULES=most não
    copia kernel/crypto/. Sem eles, WRONG_KEY com senha certa em todo chip —
    e rede aberta funcionando, porque não instala chave. Três rodadas de campo
    caçaram senha e driver antes de achar isto."""
    texto = HOOK.read_text(encoding="utf-8")
    linhas = [l for l in texto.splitlines() if "manual_add_modules" in l]
    juntas = " ".join(linhas)
    for mod in ("ccm", "cmac", "michael_mic"):
        assert f" {mod}" in juntas, f"o hook não leva o módulo {mod}"


def test_o_hook_leva_o_firmware_do_iwlwifi_pela_maior_api_disponivel():
    """O modinfo do iwlwifi declara o TOPO da faixa de API (...-hr-b0-100),
    que o linux-firmware da imagem-mestre ainda não publica; o dracut-install
    copia só o nome literal e cala (flag -o). Resultado de campo: um AX201 sem
    wifi num initrd com 74 MiB de firmware de rádio. A inclusão é por glob +
    sort -V — a maior API que EXISTE, combo a combo — mais todos os .pnvm; e o
    nb3-build-initrd recusa initrd sem os combos que já morderam."""
    hook = HOOK.read_text(encoding="utf-8")
    assert "sort -u -V" in hook, "o hook não escolhe a maior API por sort -V"
    assert ".ucode" in hook and ".pnvm" in hook, "o hook não copia ucode+pnvm"
    assert "intel/iwlwifi" in hook, "os combos novos vivem em /lib/firmware/intel/iwlwifi"

    ferramenta = (REPO / "tools" / "nb3-build-initrd").read_text(encoding="utf-8")
    for canario in ("iwlwifi-so-a0-hr-b0-", "iwlwifi-ty-a0-gf-a0-", "iwlwifi-QuZ-a0-hr-b0-"):
        assert canario in ferramenta, f"o build não confere o canário {canario}"


# --- a partição NB3CFG demora, ou não vem ------------------------------------
#
# Caso de campo: um SATA morrendo prendeu o `blkid -L` por 33 s, a partição do
# pendrive não foi lida em 10 s de tentativas, e o boot seguiu com a sede da
# cmdline, o servidor padrão (que era o do nb2!) e a chave vazia — dez
# tentativas de rede e uma tela NO NETWORK que mandava procurar cabo.


CONF_BOM = "IMAGEROOT=sala9\nNB_BOOT_KEY=nb3b_abc\nNB_SERVER=https://conf.test/\n"


def _pendrive_de_mentira(sh):
    """Um diretório com os arquivos do pendrive; o stub de mount copia dali."""
    fake = sh.tmp / "fakecfg"
    fake.mkdir()
    (fake / "nutellaboot.conf").write_text(CONF_BOM)
    (fake / "wifi.conf").write_text("Rede\tsenha-boa\n")
    sh.stub("mount", f'mkdir -p "$4"; cp "{fake}"/* "$4"/; exit 0\n')
    sh.stub("umount", "exit 0\n")
    return fake


def test_usbconfig_tenta_de_novo_ate_o_pendrive_aparecer(sh):
    _pendrive_de_mentira(sh)
    contador = sh.tmp / "blkid.count"
    sh.stub(
        "blkid",
        f'n=$(cat "{contador}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{contador}"\n'
        "[ $n -ge 3 ] && { echo /dev/falso; exit 0; }\nexit 2\n",
    )
    out = sh(
        'nb_read_usbconfig; echo "I=$IMAGEROOT K=$NB_BOOT_KEY"',
        NB_CFG_TRIES="5",
        NB_CFG_WAIT="0",
        NB_CFG_BYLABEL=str(sh.tmp / "nao-existe"),
    )
    # o harness silencia o nb_log; o marcador "pode retirar o pendrive" e o
    # wifi.conf copiado provam que a leitura chegou ao fim pelo /dev/falso
    assert contador.read_text().strip() == "3"
    assert "I=sala9 K=nb3b_abc" in out
    assert (sh.tmp / "usb-livre").is_file()
    assert (sh.run_dir / "wifi.conf").is_file()
    assert "REBOOT-CHAMADO" not in out


def test_usbconfig_acha_o_pendrive_pelo_link_do_udev(sh):
    """O link do udev nasce do evento do PRÓPRIO pendrive, sem varrer o disco
    doente — por isso vem antes do blkid."""
    _pendrive_de_mentira(sh)
    contador = sh.tmp / "blkid.count"
    sh.stub("blkid", f'echo x > "{contador}"; exit 2\n')
    alvo = sh.tmp / "dev-pelo-udev"
    alvo.write_text("")
    link = sh.tmp / "by-label"
    link.symlink_to(alvo)
    out = sh('nb_read_usbconfig; echo "I=$IMAGEROOT"', NB_CFG_BYLABEL=str(link))
    assert "I=sala9" in out and (sh.tmp / "usb-livre").is_file()
    assert not contador.exists(), "o blkid nem foi chamado"


def test_usbconfig_sem_particao_diz_que_nao_apareceu(sh):
    out = sh(
        "nb_read_usbconfig; echo NAO-DEVERIA-CHEGAR-AQUI",
        NB_CFG_TRIES="2",
        NB_CFG_WAIT="0",
        NB_CFG_BYLABEL=str(sh.tmp / "nao-existe"),
    )
    assert "the NB3CFG partition did not show up in 0s" in out
    assert "was not read" in out
    assert "REBOOT-CHAMADO" in out
    assert "NAO-DEVERIA-CHEGAR-AQUI" not in out


def test_usbconfig_com_particao_mas_mount_falhou(sh):
    sh.stub("blkid", "echo /dev/falso\n")
    out = sh("nb_read_usbconfig; echo NAO", NB_CFG_BYLABEL=str(sh.tmp / "nao-existe"))
    assert "found /dev/falso but mount failed" in out
    assert "REBOOT-CHAMADO" in out


def test_usbconfig_conf_sem_chave_e_pendrive_gravado_errado(sh):
    (sh.run_dir / "nutellaboot.conf").write_text("IMAGEROOT=sala9\n")
    out = sh("nb_read_usbconfig; echo NAO")
    assert "has no NB_BOOT_KEY line" in out
    assert "REBOOT-CHAMADO" in out


def test_usbconfig_cmdline_beats_pendrive_no_servidor(sh):
    """A mesma precedência do IMAGEROOT: o GRUB da imagem pré-configurada leva
    NB_SERVER na cmdline, e ele tem que vencer o conf e o padrão embutido."""
    (sh.tmp / "defaults").write_text("NB_SERVER=https://padrao.embutido\n")
    (sh.run_dir / "nutellaboot.conf").write_text(CONF_BOM)
    out = sh('NB_SERVER=https://cmdline.test; nb_read_usbconfig; echo "S=$NB_SERVER"')
    assert "S=https://cmdline.test" in out
    # a leitura consome a cópia em RAM (é o que tira a chave do /run)
    (sh.run_dir / "nutellaboot.conf").write_text(CONF_BOM)
    out = sh('nb_read_usbconfig; echo "S=$NB_SERVER"')
    assert "S=https://conf.test" in out


# --- boot pela rede ---------------------------------------------------------
#
# Uma sede que boota por DHCP + iPXE, como fazia no nb2, parava na tela NO CONF
# depois de 40 s procurando um pendrive que não existe. O carregador agora
# entrega o nutellaboot.conf como um arquivo a mais dentro do initrd.


def _netconf(sh, texto: str) -> Path:
    alvo = sh.tmp / "netboot" / "nutellaboot.conf"
    alvo.parent.mkdir(exist_ok=True)
    alvo.write_text(texto)
    return alvo


def test_netboot_le_o_conf_do_initrd_sem_procurar_o_pendrive(sh):
    _netconf(sh, CONF_BOM)
    contador = sh.tmp / "busca.count"
    sh.stub("blkid", f'echo x >> "{contador}"; exit 2\n')
    sh.stub("udevadm", f'echo x >> "{contador}"; exit 0\n')
    out = sh(
        'nb_read_usbconfig; echo "I=$IMAGEROOT K=$NB_BOOT_KEY S=$NB_SERVER NET=$NB_NETBOOT"',
        NB_CFG_TRIES="3",
        NB_CFG_BYLABEL=str(sh.tmp / "nao-existe"),
    )
    assert "I=sala9 K=nb3b_abc S=https://conf.test NET=1" in out
    assert not contador.exists(), "procurou o pendrive num boot pela rede"
    # nem a faixa de "pode retirar o pendrive": não há pendrive
    assert not (sh.tmp / "usb-livre").exists()
    assert "REBOOT-CHAMADO" not in out


def test_netboot_a_cmdline_continua_vencendo_o_conf(sh):
    _netconf(sh, CONF_BOM)
    out = sh(
        "IMAGEROOT=daCmdline; NB_SERVER=https://cmdline.test; nb_read_usbconfig; "
        'echo "I=$IMAGEROOT S=$NB_SERVER"'
    )
    assert "I=daCmdline S=https://cmdline.test" in out


def test_netboot_conf_vazio_para_com_a_causa(sh):
    """Arquivo vazio é carregador mal configurado. Cair no caminho do pendrive
    diria, 40 s depois, que a NB3CFG não apareceu — verdade que não ajuda."""
    _netconf(sh, "")
    out = sh("nb_read_usbconfig; echo NAO-DEVERIA-CHEGAR-AQUI")
    assert "loaded over the network is empty" in out
    assert "REBOOT-CHAMADO" in out
    assert "NAO-DEVERIA-CHEGAR-AQUI" not in out


def test_a_cmdline_nao_liga_o_netboot(sh):
    """`NB_NETBOOT=1` na linha do kernel chega como variável de ambiente e
    desligaria a regravação do pendrive em silêncio. Quem diz que o boot foi
    pela rede é o arquivo."""
    (sh.run_dir / "nutellaboot.conf").write_text(CONF_BOM)
    out = sh('NB_NETBOOT=1; nb_read_usbconfig; echo "NET=[$NB_NETBOOT]"')
    assert "NET=[]" in out


def test_a_chave_de_boot_nao_fica_no_run(sh):
    """O /run do initrd é movido para o sistema montado: a cópia do conf ali
    era a chave de boot legível por qualquer usuário da máquina de prova."""
    _netconf(sh, CONF_BOM)
    out = sh('nb_read_usbconfig; echo "K=$NB_BOOT_KEY"')
    assert "K=nb3b_abc" in out
    assert not (sh.run_dir / "nutellaboot.conf").exists()

    # o mesmo pelo pendrive
    _pendrive_de_mentira(sh)
    sh.stub("blkid", "echo /dev/falso\n")
    (sh.tmp / "netboot" / "nutellaboot.conf").unlink()
    out = sh('nb_read_usbconfig; echo "K=$NB_BOOT_KEY"', NB_CFG_BYLABEL=str(sh.tmp / "nao-existe"))
    assert "K=nb3b_abc" in out
    assert not (sh.run_dir / "nutellaboot.conf").exists()


def test_conf_salvo_no_windows(sh):
    """CRLF: o `\\r` grudado no valor vira IMAGEROOT e chave que o servidor não
    conhece. O conf do netboot mora num servidor que a sede mesma edita."""
    _netconf(
        sh,
        'set IMAGEROOT="sala9"\r\nset NB_BOOT_KEY="nb3b_abc"\r\n'
        'set NB_HOSTS="nome.test 10.0.2.2"\r\n',
    )
    out = sh('nb_read_usbconfig; echo "I=[$IMAGEROOT] K=[$NB_BOOT_KEY]"')
    assert "I=[sala9] K=[nb3b_abc]" in out
    assert (sh.tmp / "hosts").read_text() == "10.0.2.2 nome.test\n"


def test_o_stuff_tira_os_segredos_do_run(tmp_path):
    """Pendrive com initrd antigo ainda deixa o conf (chave de boot) e o
    wifi.conf (senhas) no /run, que vai inteiro para o sistema montado. O
    stuff apaga os dois depois do último consumidor, o 80-nm-wifi.sh."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "nutellaboot.conf").write_text(CONF_BOM)
    (run / "wifi.conf").write_text("Rede\tsenha-boa\n")
    main = REPO / "client" / "stuff" / "90-main.sh"
    r = subprocess.run(
        ["sh", "-c", f'. "{main}"; nb3_limpa_run'],
        env={"NB_RUN": str(run), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert not run.exists()

    texto = main.read_text()
    assert texto.index("    runpostmountconfigs\n") < texto.index("    nb3_limpa_run\n")


NB2 = "https://nutellaboot.naquadah.com.br"


def test_nenhum_padrao_do_cliente_aponta_para_o_servidor_do_nb2():
    """No campo, um pendrive cuja partição não foi lida bootou contra o nb2 e
    parou numa tela NO NETWORK enganosa: o padrão embutido era o host antigo,
    e os exemplos das docs o repetiam."""
    arquivos = [
        p for p in (REPO / "client").rglob("*") if p.is_file() and "build" not in p.parts
    ]
    arquivos += [p for p in (REPO / "tools").glob("nb3-*") if p.name != "nb3-import-nb2"]
    arquivos += list((REPO / "docs").glob("*.md"))
    ruins = [str(p.relative_to(REPO)) for p in arquivos if NB2 in p.read_text(errors="ignore")]
    assert ruins == [], ruins

    servico = (REPO / "systemd" / "nutellaboot3.service").read_text()
    base = re.search(r"NB3_BASE_URL=(\S+)", servico).group(1)
    assert f"NB_DEFAULT_SERVER='{base}'" in BOOTSTRAP.read_text()
    assert f"NB_SERVER={base}" in (REPO / "client" / "initramfs-tools" / "nutellaboot.defaults").read_text()
