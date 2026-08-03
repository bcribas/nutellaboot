"""O kit de interface do boot e a regra de que a tela do boot fala inglês.

O caminho de boot é a única parte do sistema que não pode ser traduzida em
tempo de execução: quando a mensagem aparece, muitas vezes não há rede, nem
disco, nem forma de carregar um dicionário. A escolha foi inglês fixo, e este
arquivo é o que impede o português de voltar aos poucos.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UI = REPO / "client" / "stuff" / "05-ui.sh"
BOOTSTRAP = REPO / "client" / "initramfs-tools" / "scripts" / "nutellaboot"
STUFF = sorted((REPO / "client" / "stuff").rglob("*.sh"))

# funções cuja saída vai para a tela da máquina
IMPRIME = re.compile(
    r"\b(nb_log|nb_warn|nb_fatal|nb_fatal_screen|nb_screen|nb_phase|nb_ui_text|"
    r"nb_ui_dim|log_begin_msg|log_warning_msg|log_failure_msg)\b"
)
ACENTO = re.compile(r"[À-ÿ]")


def linhas_de_codigo(path: Path):
    for n, linha in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if linha.lstrip().startswith("#"):
            continue
        yield n, linha


def sh(script: str, *, ui: bool = True) -> str:
    """Roda um trecho com o kit carregado, no /bin/sh do sistema."""
    prefixo = f". {UI}\n" if ui else ""
    return subprocess.run(
        ["sh", "-c", prefixo + script],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


# --- a regra do idioma ---


@pytest.mark.parametrize("path", [BOOTSTRAP, *STUFF], ids=lambda p: p.name)
def test_mensagem_de_tela_nao_tem_acento(path):
    """Acento é o sinal mais barato de 'sobrou português'. Não pega texto sem
    acento, mas pega a esmagadora maioria — e nunca dá falso positivo, porque
    inglês não usa acento."""
    ruins = [
        f"{path.name}:{n}: {linha.strip()}"
        for n, linha in linhas_de_codigo(path)
        if IMPRIME.search(linha) and ACENTO.search(linha)
    ]
    assert ruins == [], "mensagem de tela em portugues: " + "; ".join(ruins)


def test_aviso_do_pendrive_continua_trilingue():
    """A única exceção: quem lê essa caixa ainda não tem contexto nenhum, e a
    sala inteira depende de recolher os pendrives cedo."""
    texto = BOOTSTRAP.read_text(encoding="utf-8")
    assert "PODE RETIRAR O PENDRIVE AGORA" in texto
    assert "YOU CAN REMOVE THE USB DRIVE NOW" in texto
    assert "YA PUEDE RETIRAR LA MEMORIA USB" in texto


# --- o kit em si ---


def test_kit_e_sh_valido():
    r = subprocess.run(["sh", "-n", str(UI)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_nenhum_temporario_e_usado_por_duas_funcoes():
    """Em sh POSIX não existe `local`: toda variável é global. nb_banner usava
    a mesma variável de laço que o nb_fatal_screen usava para o tempo de
    espera, e o resultado era `sleep RAM` — a tela de erro sumia na hora, sem
    ninguém ler. A regra é: cada temporário pertence a uma função só."""
    texto = UI.read_text(encoding="utf-8")
    funcoes = re.findall(r"^(\w+)\(\) \{(.*?)^\}", texto, re.S | re.M)
    dono = {}
    for nome, corpo in funcoes:
        for var in set(re.findall(r"^\s*(?:for )?(_nbu_\w+)[= ]", corpo, re.M)):
            dono.setdefault(var, []).append(nome)
    colisoes = {v: f for v, f in dono.items() if len(f) > 1}
    assert colisoes == {}, f"temporario compartilhado entre funcoes: {colisoes}"


def test_tela_fatal_espera_o_tempo_certo():
    """A espera vem de nb_screen_wait; se uma variável for atropelada no meio,
    o `sleep` recebe lixo e a tela desaparece antes de ser lida."""
    saida = sh(
        'NB_FATAL_WAIT=30; NB_SCREEN_WAIT=45;'
        'reboot() { echo REBOOT; }; panic() { :; };'
        'sleep() { echo "SLEEP=$1"; };'
        'nb_fatal_screen "NO DISK" "!x"'
    )
    assert "SLEEP=45" in saida, saida


def test_fatal_wait_zero_zera_tambem_a_tela():
    """Sem isso cada teste de erro custaria um minuto de suíte, e depurar em
    VM viraria uma sessão de paciência."""
    saida = sh(
        'NB_FATAL_WAIT=0; reboot() { :; }; panic() { :; };'
        'sleep() { echo "SLEEP=$1"; }; nb_fatal_screen "NO DISK" "!x"'
    )
    assert "SLEEP=0" in saida, saida


def test_kit_nao_usa_echo_com_escape():
    """`echo -e` se comporta diferente entre dash e busybox ash; o desenho
    inteiro sairia errado justamente no console do initrd."""
    texto = UI.read_text(encoding="utf-8")
    assert "echo -e" not in texto
    assert "echo -n" not in texto


@pytest.mark.parametrize("ch", list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
def test_todo_caractere_tem_glifo_de_cinco_linhas(ch):
    """Um glifo faltando vira letra em branco no meio da palavra, e só se
    descobre na sala."""
    linhas = sh(f'eval "g=\\$NB_G_{ch}"; printf "%s" "$g"').split("|")
    assert len(linhas) == 5, f"{ch}: {len(linhas)} linhas"
    assert all(len(x) == 4 for x in linhas), f"{ch}: larguras {[len(x) for x in linhas]}"
    assert all(set(x) <= {"#", "."} for x in linhas), f"{ch}: caractere estranho"


def pixels(linha: str) -> str:
    """O banner desenha com ESPAÇOS em fundo colorido — depois de remover o
    ANSI, aceso e apagado viram o mesmo espaço. Aqui o fundo é reconstruído a
    partir dos códigos de cor: '#' aceso (47), '.' apagado."""
    saida = []
    fundo = "."
    i = 0
    while i < len(linha):
        m = re.match(r"\x1b\[([0-9;]*)m", linha[i:])
        if m:
            fundo = {"47": "#"}.get(m.group(1), ".")
            i += m.end()
            continue
        saida.append(fundo if linha[i] == " " else linha[i])
        i += 1
    return "".join(saida)


def test_banner_desenha_letra_reconhecivel():
    """Renderiza 'I' e confere o formato: barra em cima, haste no meio, barra
    embaixo. Se a tabela de bitmap se desalinhar, isto quebra."""
    saida = sh('NB_UI_COLS=40; nb_banner "$NB_C_RED" I')
    linhas = [pixels(x) for x in saida.splitlines() if x.strip()]
    # 2 barras + 5 linhas de glifo
    assert len(linhas) == 7, linhas
    # 2 de margem externa + 2 de margem interna do banner
    glifo = [x[4:12] for x in linhas[1:6]]
    assert glifo[0] == "..####..", glifo
    assert glifo[2] == "....##..", glifo
    assert glifo[4] == "..####..", glifo


def test_banner_quebra_em_varias_linhas_quando_nao_cabe():
    """Sem quebra, uma palavra longa sai truncada ou embrulhada pelo console —
    e a tela de erro fica ilegível."""
    estreito = sh('NB_UI_COLS=40; nb_banner "$NB_C_RED" NO DISK FOUND')
    assert estreito.count("\n") > sh('NB_UI_COLS=200; nb_banner "$NB_C_RED" NO DISK FOUND').count("\n")


def test_modo_sem_cor_nao_emite_escape():
    """NB_UI_PLAIN existe para quando a saída do boot está sendo capturada
    para arquivo (e para estes testes)."""
    saida = sh('NB_UI_PLAIN=1; . ' + str(UI) + '; nb_banner "" NO DISK; log_begin_msg oi; log_end_msg')
    assert "\x1b" not in saida


def test_passo_fecha_a_linha_antes_de_um_aviso():
    """Sem isso, o aviso sai grudado no fim da linha do passo em andamento e
    ninguém lê nem um nem outro."""
    saida = remover_ansi(sh('log_begin_msg "baixando"; log_warning_msg "deu ruim"'))
    linhas = [x for x in saida.splitlines() if x.strip()]
    assert len(linhas) == 2, linhas
    assert "WARN" in linhas[1]


def test_tela_de_erro_mostra_banner_e_texto():
    saida = remover_ansi(sh('NB_UI_COLS=60; nb_screen "NO DISK" "!linha forte" "linha fraca"'))
    assert "linha forte" in saida
    assert "linha fraca" in saida
    assert "!" not in saida, "o marcador de destaque nao pode vazar para a tela"


def remover_ansi(texto: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", texto)


# --- integração com o initrd ---


def test_bootstrap_carrega_o_kit_de_forma_condicional():
    """Condicional de propósito: um initrd gerado antes do kit existir tem que
    continuar bootando, só sem o visual."""
    texto = BOOTSTRAP.read_text(encoding="utf-8")
    assert "[ -r /scripts/nb3-ui ] && . /scripts/nb3-ui" in texto
    assert "command -v nb_phase" in texto, "faltou o fallback para initrd antigo"


def test_hook_copia_o_kit_para_o_initrd():
    hook = (REPO / "client" / "initramfs-tools" / "hooks" / "nutellaboot").read_text()
    assert "/scripts/nb3-ui" in hook


def test_build_initrd_leva_o_kit_para_dentro_da_imagem():
    build = (REPO / "tools" / "nb3-build-initrd").read_text()
    assert "client/stuff/05-ui.sh" in build, (
        "sem esta cópia o hook não acha o kit e o initrd sai sem as telas"
    )


def test_kit_e_o_mesmo_arquivo_nos_dois_caminhos():
    """Uma fonte só: o servidor concatena client/stuff/05-ui.sh no stuff e o
    initrd recebe uma cópia do MESMO arquivo. Se alguém criar uma segunda
    cópia para 'ajustar só no initrd', as telas divergem em silêncio."""
    copias = [p for p in REPO.rglob("*.sh") if p.name == "05-ui.sh"]
    assert len(copias) == 1, [str(p) for p in copias]
