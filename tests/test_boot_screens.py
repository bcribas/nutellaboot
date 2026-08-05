"""As telas fatais do boot: o que elas dizem e quando.

A tela de "sem disco" é a mais importante do sistema. Ela aparece quando a
máquina não tem onde guardar o sistema — e, na prática, quase sempre porque o
Windows foi hibernado em vez de desligado, o que trava o NTFS. Antes disso
sair explicado, a máquina reiniciava sozinha em 30 s com uma linha cinza, e a
sala não tinha como saber o que fazer.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUFF = REPO / "client" / "stuff"
BOOTSTRAP = REPO / "client" / "initramfs-tools" / "scripts" / "nutellaboot"

CABECALHO = f"""
cd {REPO}
. {STUFF}/00-header.sh
. {STUFF}/05-ui.sh
. {STUFF}/30-storage.sh
NB_FATAL_WAIT=0
NB_UI_PLAIN=1
reboot() {{ echo "REBOOT-CHAMADO"; }}
panic() {{ echo "PANIC"; }}
"""


def sh(script: str, diskslog: str | None = None, tmp: Path | None = None) -> str:
    prep = ""
    if diskslog is not None:
        alvo = (tmp or Path("/tmp")) / "diskslog"
        alvo.write_text(diskslog)
        prep = f"cp {alvo} /tmp/diskslog\n"
    r = subprocess.run(
        ["sh", "-c", CABECALHO + prep + script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.stdout


# --- diagnóstico do disco ---


def test_ntfs_travado_aponta_o_fast_startup(tmp_path):
    """O caso mais comum de todos. Sem esta explicação, a sede chama suporte
    para um problema que se resolve desligando o Windows direito."""
    saida = sh(
        "nb_disk_advice",
        "/dev/nvme0n1p3|ntfs|could not be mounted\n",
        tmp_path,
    )
    assert "WINDOWS FAST STARTUP" in saida
    assert "shutdown /s /t 0" in saida
    assert "Fast Startup" in saida


def test_ntfs_somente_leitura_tambem_e_fast_startup(tmp_path):
    saida = sh("nb_disk_advice", "/dev/sda2|ntfs|mounted read-only\n", tmp_path)
    assert "WINDOWS FAST STARTUP" in saida


def test_pouco_espaco_diz_quanto_falta(tmp_path):
    saida = sh(
        "nb_disk_advice",
        "/dev/sda1|ext4|only 3200 MB free, needs 14620 MB\n",
        tmp_path,
    )
    assert "NOT ENOUGH FREE SPACE" in saida
    assert "15 GB" in saida, "o texto tem que arredondar para cima, senao a pessoa libera de menos"


def test_nenhuma_particao_aponta_o_modo_raid_da_bios(tmp_path):
    """Disco invisível quase sempre é controladora em RAID/Intel RST. Quem não
    sabe disso troca o SSD achando que queimou."""
    saida = sh("nb_disk_advice", "", tmp_path)
    assert "NOT DETECTED" in saida
    assert "AHCI" in saida
    assert "BIOS" in saida


def test_so_sistema_nao_suportado_menciona_bitlocker(tmp_path):
    saida = sh(
        "nb_disk_advice",
        "/dev/nvme0n1p2|BitLocker|unsupported filesystem\n",
        tmp_path,
    )
    assert "NO SUPPORTED FILESYSTEM" in saida
    assert "BitLocker" in saida


def test_ntfs_travado_ganha_de_pouco_espaco(tmp_path):
    """Com os dois sintomas juntos, o NTFS travado é o que a pessoa consegue
    resolver — e resolver isso costuma liberar o espaço também."""
    saida = sh(
        "nb_disk_advice",
        "/dev/sda1|ext4|only 100 MB free, needs 14620 MB\n"
        "/dev/sda2|ntfs|could not be mounted\n",
        tmp_path,
    )
    assert "WINDOWS FAST STARTUP" in saida
    assert "NOT ENOUGH FREE SPACE" not in saida


# --- a tela inteira ---


def test_tela_de_disco_tem_o_que_a_sala_precisa(tmp_path):
    saida = sh(
        "nb_no_disk_screen",
        "/dev/nvme0n1p3|ntfs|could not be mounted\n",
        tmp_path,
    )
    # o que é
    assert "no disk where the system can be stored" in saida
    # o que NÃO é (o medo mais comum de quem vê a mensagem)
    assert "NOT erased" in saida and "NOT touched" in saida
    # o que foi encontrado
    assert "/dev/nvme0n1p3" in saida
    assert "ntfs" in saida
    # o que fazer
    assert "WINDOWS FAST STARTUP" in saida
    # e que reinicia mesmo
    assert "REBOOT-CHAMADO" in saida


def test_tela_de_disco_nao_espera_ninguem_apertar_tecla(tmp_path):
    """A regra de ouro do caminho de boot: nada de `read`. Uma sala com 40
    máquinas paradas esperando ENTER é pior que 40 máquinas reiniciando."""
    fonte = (STUFF / "30-storage.sh").read_text()
    for linha in fonte.splitlines():
        s = linha.strip()
        assert not (s == "read" or s.startswith("read ")), linha


# --- as demais telas ---


@pytest.mark.parametrize(
    "chamada,esperado",
    [
        ("checkminram", ["LOW RAM", "Installed", "Required"]),
        ("checkforvirtualization", ["NO VM", "real hardware"]),
    ],
)
def test_telas_de_checagem(chamada, esperado):
    ambiente = {
        "checkminram": "MINRAM=999999",
        "checkforvirtualization": "ALLOWVM=f; dmesg() { echo virtual; }",
    }[chamada]
    saida = sh(f"{ambiente}; {chamada}")
    for termo in esperado:
        assert termo in saida, f"{chamada}: faltou '{termo}' em {saida[:400]}"


def test_bootstrap_tem_tela_para_cada_falha_de_rede():
    """Sem rede e servidor mudo são problemas diferentes, e a ação de quem
    está na sala também é diferente: cabo/switch num caso, nome do servidor e
    relógio no outro."""
    texto = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'nb_fatal_screen "NO NETWORK"' in texto
    assert 'nb_fatal_screen "NO SERVER"' in texto
    assert 'nb_fatal_screen "NO IMAGE"' in texto
    # e wifi é um terceiro problema: mandar conferir cabo e switch quem está
    # tentando por rádio é mandar procurar no lugar errado
    assert 'nb_fatal_screen "NO WIFI"' in texto
    assert "$NB_WIFI_REASON" in texto
    # a de servidor menciona o relógio: bateria de CMOS morta dá exatamente
    # este sintoma e é diagnóstico que ninguém adivinha
    assert "CMOS" in texto


MAX_LINHAS = 25  # console VGA texto, o piso do que se encontra em sala


def altura(script: str, diskslog: str | None = None, tmp: Path | None = None) -> int:
    saida = sh(script.replace("NB_UI_PLAIN=1", ""), diskslog, tmp)
    return len(saida.splitlines())


@pytest.mark.parametrize(
    "nome,diskslog",
    [
        ("ntfs travado", "/dev/nvme0n1p3|ntfs|could not be mounted\n"),
        ("sem particao", ""),
        ("pouco espaco", "/dev/sda1|ext4|only 100 MB free, needs 14620 MB\n"),
        (
            "muitas particoes",
            "".join(
                f"/dev/sda{i}|ntfs|could not be mounted\n" for i in range(1, 9)
            ),
        ),
    ],
)
def test_tela_de_disco_cabe_na_tela(nome, diskslog, tmp_path):
    """Na primeira verificação em VM o banner rolou para fora: o texto era mais
    alto que o console e as letras grandes — a parte que faz a pessoa olhar —
    sumiram. O orçamento é 25 linhas, e o pior caso é muitas partições."""
    n = altura(
        "NB_UI_PLAIN=0\nreboot() { :; }\npanic() { :; }\nnb_no_disk_screen",
        diskslog,
        tmp_path,
    )
    assert n <= MAX_LINHAS, f"tela de disco ({nome}) usa {n} linhas"


@pytest.mark.parametrize(
    "preparo,chamada",
    [
        ("MINRAM=999999", "checkminram"),
        ("ALLOWVM=f; dmesg() { echo virtual; }", "checkforvirtualization"),
    ],
)
def test_demais_telas_cabem_na_tela(preparo, chamada):
    n = altura(f"NB_UI_PLAIN=0\nreboot() {{ exit 0; }}\npanic() {{ :; }}\n{preparo}\n{chamada}")
    assert n <= MAX_LINHAS, f"{chamada} usa {n} linhas"


def test_tela_fatal_limpa_o_console_antes_de_desenhar():
    """Sem limpar, o banner nasce embaixo da enxurrada de mensagens do kernel
    e some no scroll."""
    saida = sh('NB_UI_PLAIN=0; reboot() { :; }; panic() { :; }; nb_screen "NO DISK" "!x"')
    assert "\x1b[2J" in saida and "\x1b[H" in saida


def test_toda_tela_fatal_diz_o_que_fazer():
    """Uma tela que só informa o erro não serve para quem está na sala."""
    fontes = [BOOTSTRAP.read_text(), *(p.read_text() for p in STUFF.rglob("*.sh"))]
    blocos = []
    for texto in fontes:
        # sem comentários: o próprio kit documenta a assinatura da função e
        # cairia aqui como se fosse uma tela de verdade
        codigo = "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("#"))
        blocos += re.findall(r'nb_fatal_screen "([A-Z ]+)"(.*?)(?=\n\S|\Z)', codigo, re.S)
    assert blocos, "nenhuma tela fatal encontrada"
    for nome, corpo in blocos:
        assert re.search(r"What to (do|check)|-> ", corpo), (
            f"a tela '{nome}' nao diz o que fazer"
        )
