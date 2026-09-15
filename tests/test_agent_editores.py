"""A contagem de uso dos editores sabe desde quando conta.

`editors_time` era acumulado desde a instalação (7.972 minutos numa máquina
do MOJ), e quem lia não tinha como saber quando foi o último reset. Agora o
arquivo leva `since=`: o reset apaga o arquivo e a passada seguinte recomeça
com um `since` novo, que o coletor expõe como `editors_time_since`.
"""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"
PARTE = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "parts.d" / "30-operacoes.sh"


def _tick(tmp_path, abertos="vim\nbash\n"):
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok=True)
    ps = fakebin / "ps"
    ps.write_text(f"#!/bin/sh\nprintf '{abertos}'\n")
    ps.chmod(0o755)
    texto = AGENTE.read_text()
    inicio = texto.index("editors_tick() {")
    fim = texto.index("\n}\n", inicio) + 3
    script = (
        f'EDITORES_ARQ="{tmp_path}/editores"\nEDITORES_LISTA="emacs vim geany code"\n'
        f"{texto[inicio:fim]}\neditors_tick\n"
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": f"{fakebin}:/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    return (tmp_path / "editores").read_text()


def _linhas(texto):
    return dict(l.split("=", 1) for l in texto.splitlines() if "=" in l)


def test_o_tick_conta_e_preserva_o_since(tmp_path):
    a = _linhas(_tick(tmp_path))
    assert a["vim"] == "1" and a["total"] == "1" and a["since"].isdigit()
    b = _linhas(_tick(tmp_path))
    assert b["vim"] == "2" and b["total"] == "2"
    assert b["since"] == a["since"], "o since é de quando a contagem começou"
    c = _linhas(_tick(tmp_path, abertos="bash\n"))
    assert c["vim"] == "2" and c["total"] == "3"


def test_o_reset_apaga_e_a_passada_seguinte_recomeca(tmp_path):
    a = _linhas(_tick(tmp_path))
    (tmp_path / "editores").unlink()  # cmd_resetcontaeditores
    import time

    time.sleep(1.1)
    b = _linhas(_tick(tmp_path))
    assert b["vim"] == "1" and b["total"] == "1"
    assert int(b["since"]) > int(a["since"])


def test_o_coletor_expoe_desde_quando_conta(tmp_path):
    arq = tmp_path / "editores"
    arq.write_text("since=1700000000\nvim=40\ntotal=42\n")
    r = subprocess.run(
        ["bash", str(PARTE)],
        capture_output=True,
        text=True,
        env={**os.environ, "NB_EDITORES_ARQ": str(arq)},
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    ops = json.loads("{" + r.stdout + "}")["operations"]
    assert ops["editors_time"] == {"vim": 40, "total": 42}, "o since não entra no acumulado"
    assert ops["editors_time_since"] == 1700000000


def test_sem_arquivo_os_dois_ficam_nulos(tmp_path):
    r = subprocess.run(
        ["bash", str(PARTE)],
        capture_output=True,
        text=True,
        env={**os.environ, "NB_EDITORES_ARQ": str(tmp_path / "nao-existe")},
        timeout=30,
    )
    ops = json.loads("{" + r.stdout + "}")["operations"]
    assert ops["editors_time"] is None and ops["editors_time_since"] is None
