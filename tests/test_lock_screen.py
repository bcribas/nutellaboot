"""A tela de bloqueio (maratona-wait) e o que a fez morrer em 1 s.

O `activate` busca o lockinfo por um curl assíncrono e só cria as janelas no
callback. Um GApplication cujo `activate` volta sem janela e sem `hold()`
encerra ali mesmo. Até setembro de 2026 o `mac` vinha vazio (pendrive sem
BOOTIF), o caminho era síncrono, e a tela nascia dentro do activate por acaso;
o `--mac` do agente novo virou o caminho assíncrono e a tela sumiu em toda
máquina, em silêncio (o stderr do agente vai para /dev/null).
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TELA = REPO / "client" / "telemetry" / "usr" / "bin" / "maratona-wait"
AGENTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"


def test_o_activate_segura_o_app_ate_a_janela_existir():
    js = TELA.read_text(encoding="utf-8")
    ativa = js[js.index('app.connect("activate"'):]
    assert ativa.index("app.hold()") < ativa.index("loadLockInfo("), "o hold vem antes do trabalho assíncrono"
    assert "finally {" in ativa and "app.release()" in ativa[ativa.index("finally {"):]
    assert "app.quit()" in ativa[ativa.index("} catch (e) {"):ativa.index("finally {")], (
        "exceção ao montar a tela tem de encerrar: senão fica um processo invisível que o pgrep toma por tela"
    )
    assert ativa.index("win.show_all()") < ativa.index("finally {")


def test_o_que_a_tela_diz_vai_para_o_journal():
    sh = AGENTE.read_text(encoding="utf-8")
    inicio = sh.index("ensure_locked() {")
    fim = sh.index("ensure_unlocked() {")
    bloco = sh[inicio:fim]
    assert "2>&1 | logger -t nb3-lock" in bloco
    tag = bloco.split("logger -t ")[1].split()[0]
    assert "maratona-wait" not in tag, "o pgrep -f maratona-wait casaria o logger"


@pytest.mark.skipif(shutil.which("gjs") is None, reason="sem gjs")
def test_gapplication_sem_hold_encerra_antes_do_callback(tmp_path):
    """O mecanismo, não o texto: sem hold o app volta em milissegundos e o
    callback nunca roda; com hold, espera."""
    roteiro = textwrap.dedent("""
        const { Gio, GLib } = imports.gi;
        const comHold = ARGV[0] === "hold";
        const app = new Gio.Application({ application_id: "br.com.naquadah.TesteLock",
                                          flags: Gio.ApplicationFlags.NON_UNIQUE });
        let rodou = false;
        app.connect("activate", () => {
            if (comHold) app.hold();
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
                rodou = true;
                if (comHold) app.release();
                return GLib.SOURCE_REMOVE;
            });
        });
        app.run([]);
        print(rodou ? "callback rodou" : "encerrou antes");
    """)
    arq = tmp_path / "t.js"
    arq.write_text(roteiro)
    sem = subprocess.run(["gjs", str(arq), "nada"], capture_output=True, text=True, timeout=20)
    com = subprocess.run(["gjs", str(arq), "hold"], capture_output=True, text=True, timeout=20)
    assert "encerrou antes" in sem.stdout, sem.stdout + sem.stderr
    assert "callback rodou" in com.stdout, com.stdout + com.stderr
