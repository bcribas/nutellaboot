"""A senha de emergência da tela de bloqueio, ponta a ponta no lado do agente.

A arquitetura antiga nunca poderia funcionar: a tela (rodando como icpc)
tentava ler o hash de /etc/.nb3 — 0600 root, junto com a chave de máquina — o
readFile devolvia null em silêncio e NENHUMA senha destravava. E mesmo que
lesse: o `unlock-request` que ela escrevia não era lido por ninguém, e o
watchdog relançava a tela em 3 segundos.

Agora a tela só coleta as teclas e escreve no FIFO; o agente (root) confere o
hash e destrava. Estes testes exercitam as funções do agente de verdade, com
`bash` (o agente é bash), no padrão do test_agent_mac.
"""

import subprocess
from pathlib import Path

import pytest

from server.app.services import config

REPO = Path(__file__).resolve().parents[1]
AGENTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"
TELA = REPO / "client" / "telemetry" / "usr" / "bin" / "maratona-wait"


def _funcoes(*nomes: str) -> str:
    texto = AGENTE.read_text()
    partes = []
    for nome in nomes:
        inicio = texto.index(f"{nome}() {{")
        fim = texto.index("\n}\n", inicio) + 3
        partes.append(texto[inicio:fim])
    return "\n".join(partes)


def _roda(script: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **{k: str(v) for k, v in env.items()}},
        timeout=30,
    )


# --- a verificação em shell aceita o hash que o SERVIDOR grava ---------------


def test_a_senha_certa_passa_com_o_hash_do_servidor():
    """Paridade dos dois lados: o hash sai de config.hash_password (Python,
    sha256(salt+senha) em salt$hex) e a conferência é o sha256sum do agente.
    Se um dos lados mudar de algoritmo, caixa ou formato, este teste cai."""
    h = config.hash_password("Segredo da Sede 42!")
    corpo = _funcoes("verify_lock_password") + (
        '\nif verify_lock_password "Segredo da Sede 42!"; then echo ACEITA; else echo RECUSA; fi'
    )
    r = _roda(corpo, NB_LOCK_FALLBACK_HASH=h)
    assert r.returncode == 0, r.stderr
    assert "ACEITA" in r.stdout


@pytest.mark.parametrize(
    "digitada",
    ["errada", "", "Segredo da Sede 42", "segredo da sede 42!"],
)
def test_a_senha_errada_nao_passa(digitada):
    h = config.hash_password("Segredo da Sede 42!")
    corpo = _funcoes("verify_lock_password") + (
        f'\nif verify_lock_password "{digitada}"; then echo ACEITA; else echo RECUSA; fi'
    )
    r = _roda(corpo, NB_LOCK_FALLBACK_HASH=h)
    assert "RECUSA" in r.stdout


def test_sem_hash_configurado_nada_destrava():
    corpo = _funcoes("verify_lock_password") + (
        '\nif verify_lock_password "qualquer"; then echo ACEITA; else echo RECUSA; fi'
    )
    r = _roda(corpo, NB_LOCK_FALLBACK_HASH="")
    assert "RECUSA" in r.stdout


# --- o FIFO destrava e o override segura o destravamento ----------------------


def test_a_linha_certa_no_fifo_destrava(tmp_path):
    """O caminho inteiro do agente: a senha entra pelo FIFO, o hash confere, o
    `locked` sai e o override local aparece — é ele que impede o long-poll de
    retravar em segundos."""
    h = config.hash_password("senha-de-emergencia")
    fifo = tmp_path / "unlock.fifo"
    state = tmp_path / "state"
    state.mkdir()
    (state / "locked").touch()

    corpo = (
        _funcoes("verify_lock_password", "unlock_listener")
        + f"""
log() {{ echo "LOG: $*"; }}
ensure_unlocked() {{ rm -f "$STATE_DIR/locked"; echo DESTRAVOU; }}
mkfifo "$NB_UNLOCK_FIFO"
unlock_listener &
listener=$!
printf '%s\\n' "senha-de-emergencia" > "$NB_UNLOCK_FIFO"
sleep 0.3
kill "$listener" 2>/dev/null
wait 2>/dev/null
"""
    )
    r = _roda(corpo, NB_LOCK_FALLBACK_HASH=h, NB_UNLOCK_FIFO=fifo, STATE_DIR=state)
    assert "DESTRAVOU" in r.stdout, r.stdout + r.stderr
    assert not (state / "locked").exists()
    assert (state / "local-unlock").exists(), "sem o override o long-poll retrava"


def test_a_linha_errada_no_fifo_nao_destrava(tmp_path):
    h = config.hash_password("senha-de-emergencia")
    fifo = tmp_path / "unlock.fifo"
    state = tmp_path / "state"
    state.mkdir()
    (state / "locked").touch()

    corpo = (
        _funcoes("verify_lock_password", "unlock_listener")
        + f"""
log() {{ echo "LOG: $*"; }}
ensure_unlocked() {{ echo DESTRAVOU; }}
mkfifo "$NB_UNLOCK_FIFO"
unlock_listener &
listener=$!
printf '%s\\n' "chute-errado" > "$NB_UNLOCK_FIFO"
sleep 0.3
kill "$listener" 2>/dev/null
wait 2>/dev/null
"""
    )
    r = _roda(corpo, NB_LOCK_FALLBACK_HASH=h, NB_UNLOCK_FIFO=fifo, STATE_DIR=state)
    assert "DESTRAVOU" not in r.stdout
    assert "recusada" in r.stdout
    assert (state / "locked").exists()


def test_servidor_locked_com_override_nao_retrava(tmp_path):
    """O trecho do long-poll que decide travar, isolado: estado `locked` do
    servidor com o override presente NÃO relança a tela; sem o override,
    relança. E o `unlocked` do servidor limpa o override (ressincroniza)."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "local-unlock").touch()

    trecho = """
ensure_locked() { echo TRAVOU; }
ensure_unlocked() { echo DESTRAVOU; }
# o mesmo if do commands_loop
if [ "$RESP_LOCKED" = true ]; then
    [ -e "$STATE_DIR/local-unlock" ] || ensure_locked
else
    rm -f "$STATE_DIR/local-unlock"
    ensure_unlocked
fi
"""
    r = _roda(trecho, STATE_DIR=state, RESP_LOCKED="true")
    assert "TRAVOU" not in r.stdout

    r = _roda(trecho, STATE_DIR=state, RESP_LOCKED="false")
    assert "DESTRAVOU" in r.stdout
    assert not (state / "local-unlock").exists()

    r = _roda(trecho, STATE_DIR=state, RESP_LOCKED="true")
    assert "TRAVOU" in r.stdout


def test_comando_novo_de_travar_anula_o_override(tmp_path):
    """A organização retrava por cima do destravamento local, e vale ela."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "local-unlock").touch()
    corpo = _funcoes("cmd_donottouch") + "\nensure_locked() { echo TRAVOU; }\ncmd_donottouch"
    r = _roda(corpo, STATE_DIR=state)
    assert "TRAVOU" in r.stdout
    assert not (state / "local-unlock").exists()


def test_o_if_do_commands_loop_respeita_o_override():
    """O trecho de verdade do agente contém a guarda — se alguém 'simplificar'
    o if de volta para ensure_locked incondicional, a senha de emergência
    vira um piscar de olhos de novo."""
    corpo = AGENTE.read_text()
    trecho = corpo.split("nb3-json locked")[1].split("fi")[0]
    assert "local-unlock" in trecho


# --- o contrato entre o agente e a tela --------------------------------------


def test_a_tela_nao_le_o_arquivo_de_segredos():
    """/etc/.nb3 guarda a chave de máquina e é 0600 root; a tela roda como
    icpc. A leitura era a raiz do defeito — e voltar a ela seria ou quebrar a
    senha de novo, ou abrir o arquivo para o competidor."""
    # sem comentários: eles explicam a história e citariam o caminho
    js = "\n".join(
        l for l in TELA.read_text().splitlines() if not l.lstrip().startswith("//")
    )
    assert "/etc/.nb3" not in js
    assert "NB_LOCK_FALLBACK_HASH" not in js, "o hash não é assunto da tela"
    assert "checkPassword" not in js, "quem confere é o agente"


def test_o_agente_lanca_a_tela_com_argumentos():
    corpo = AGENTE.read_text()
    lanca = corpo.split("abrindo a tela de bloqueio")[1].split("disown")[0]
    for arg in ("--image", "--server", "--theme", "--lang", "--fifo"):
        assert arg in lanca, f"a tela não recebe {arg}"
    # a chave de boot vai por ambiente (não aparece no ps de outros usuários)
    assert "NB_BOOT_KEY=" in lanca


def test_a_tela_escuta_teclado_em_todas_as_janelas():
    """Só a janela do monitor 0 escutava: bastava o foco cair na outra para a
    senha ir para o nada."""
    js = TELA.read_text()
    bloco = js.split("for (let i = 0; i < nMonitors; i++)")[1]
    assert 'win.connect("key-press-event"' in bloco
    assert 'if (i === 0)' not in bloco.split("key-press-event")[0]


def test_a_tela_aceita_o_teclado_numerico():
    js = TELA.read_text()
    assert "Gdk.KEY_KP_0" in js and "Gdk.KEY_KP_9" in js


def test_a_senha_vai_pelo_fifo_e_nunca_por_argumento():
    js = TELA.read_text()
    assert "sendPassword" in js
    assert "STDIN_PIPE" in js, "a senha vai pelo stdin do cat, nunca no argv"
    # e não há mais NUL literal dentro de string (era corrompível por qualquer
    # normalização de texto)
    assert "\x00" not in js
