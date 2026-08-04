"""A barra de progresso não pode derrubar o download.

Ela derrubou. O `stdbuf` foi para o initrd sem a `libstdbuf.so` no caminho que
ele espera, saiu 125 ANTES de executar o aria2c, e a mensagem de erro morreu no
filtro do awk que alimenta a barra. Nenhuma máquina baixou mais nada, e a única
coisa na tela era "attempt 1/5 failed (125)".

Aqui o `stdbuf` quebrado e o `awk` ausente viram teste: nos dois casos o
download tem que acontecer. Perder o enfeite é aceitável; perder o boot não.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUFF = REPO / "client" / "stuff"
DOWNLOAD = STUFF / "20-download.sh"

# O stuff é concatenado pelo servidor nesta ordem; o 20-download usa nb_warn do
# header e nb_ui_progress do kit de tela.
HARNESS = """
export PATH="$FAKEBIN:$PATH"
log_begin_msg() { echo "BEGIN: $*"; }
log_end_msg() { :; }
log_warning_msg() { echo "WARN: $*"; }
log_failure_msg() { echo "FAIL: $*"; }
. "$STUFF/00-header.sh"
. "$STUFF/05-ui.sh"
. "$STUFF/20-download.sh"
"""

# Uma linha de leitura do aria2 e uma de erro, como saem de verdade.
LINHA_PROGRESSO = "[#fbbee4 2.0MiB/300MiB(0%) CN:1 DL:1.0MiB ETA:4m56s]"
LINHA_ERRO = "05/08 12:00:00 [ERROR] CUID#7 - Download aborted. URI=https://x/y"

# 6,1 GiB: o tamanho da camada base. É acima de 2^31, que é onde o awk do
# busybox trunca.
LINHA_GRANDE = "[#a1b2c3 1.5GiB/6.1GiB(24%) CN:10 DL:112MiB ETA:1m2s]"


def _fakebin(tmp_path, *, stdbuf: str, aria: str) -> Path:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    (d / "stdbuf").write_text(stdbuf)
    (d / "aria2c").write_text(aria)
    for f in ("stdbuf", "aria2c"):
        (d / f).chmod(0o755)
    return d


# `-o0` some do $@ porque o aria2 falso é chamado direto quando não há prefixo;
# o que importa é que ele escreva o arquivo de destino.
ARIA_QUE_FUNCIONA = f"""#!/bin/sh
dir=.
base=saida
while [ $# -gt 0 ]; do
    case $1 in
        -d) dir=$2; shift 2 ;;
        -o) base=$2; shift 2 ;;
        *) shift ;;
    esac
done
echo '{LINHA_PROGRESSO}'
echo 'camada baixada' > "$dir/$base"
exit 0
"""

STDBUF_QUEBRADO = """#!/bin/sh
echo "stdbuf: failed to find 'libstdbuf.so'" >&2
exit 125
"""

STDBUF_BOM = """#!/bin/sh
while [ $# -gt 0 ]; do
    case $1 in
        -o0 | -i0 | -e0 | -o* | -i* | -e*) shift ;;
        *) break ;;
    esac
done
exec "$@"
"""


def _run(tmp_path, fakebin, script, **env):
    e = {
        "STUFF": str(STUFF),
        "FAKEBIN": str(fakebin),
        "PATH": "/usr/bin:/bin",
        "NB_UI_PLAIN": "1",
        "NB_DOWNLOAD_TRIES": "2",
        **{k: str(v) for k, v in env.items()},
    }
    return subprocess.run(
        ["sh", "-c", HARNESS + "\n" + script],
        capture_output=True,
        text=True,
        env=e,
        cwd=tmp_path,
    )


def test_stdbuf_quebrado_nao_impede_o_download(tmp_path):
    """O boot de 3 de agosto de 2026, virado teste.

    `stdbuf` existe mas não acha a biblioteca dele: sai 125 sem executar o
    aria2c. O download TEM que acontecer assim mesmo, sem a barra ao vivo."""
    fakebin = _fakebin(tmp_path, stdbuf=STDBUF_QUEBRADO, aria=ARIA_QUE_FUNCIONA)
    alvo = tmp_path / "camada.squash"
    r = _run(
        tmp_path,
        fakebin,
        f'nb_download "{alvo}" 4 https://exemplo.test/c.squash; echo "RC=$?"',
        NB_DL_PROGRESS="1",
    )
    assert "RC=0" in r.stdout, f"{r.stdout}\n{r.stderr}"
    assert alvo.is_file(), "o arquivo não foi baixado"
    assert "bursts" in r.stdout, "o aviso de barra degradada não apareceu"


def test_sem_awk_nao_impede_o_download(tmp_path):
    """Sem `awk` não há como ler os números do aria2 — e ainda assim o download
    acontece, porque a barra é enfeite."""
    fakebin = _fakebin(tmp_path, stdbuf=STDBUF_BOM, aria=ARIA_QUE_FUNCIONA)
    # PATH mínimo sem awk: um diretório só com o essencial
    magro = tmp_path / "magro"
    magro.mkdir()
    for cmd in ("sh", "cat", "rm", "mkdir", "dirname", "basename", "sleep", "printf"):
        origem = shutil.which(cmd)
        if origem:
            os.symlink(origem, magro / cmd)
    alvo = tmp_path / "camada.squash"
    r = _run(
        tmp_path,
        fakebin,
        f'nb_download "{alvo}" 4 https://exemplo.test/c.squash; echo "RC=$?"',
        PATH=str(magro),
        NB_DL_PROGRESS="1",
    )
    assert "RC=0" in r.stdout, f"{r.stdout}\n{r.stderr}"
    assert alvo.is_file(), "o arquivo não foi baixado"


def test_com_stdbuf_bom_a_barra_anda(tmp_path):
    fakebin = _fakebin(tmp_path, stdbuf=STDBUF_BOM, aria=ARIA_QUE_FUNCIONA)
    alvo = tmp_path / "camada.squash"
    r = _run(
        tmp_path,
        fakebin,
        f'nb_download "{alvo}" 4 https://exemplo.test/c.squash; echo "RC=$?"',
        NB_DL_PROGRESS="1",
    )
    assert "RC=0" in r.stdout, f"{r.stdout}\n{r.stderr}"
    # NB_UI_PLAIN=1 imprime "2.0 MB of 300.0 MB"
    assert "of 300" in r.stdout, r.stdout


def test_o_que_o_aria_diz_chega_na_tela(tmp_path):
    """O filtro da barra descartava TUDO que não fosse progresso: erro de TLS,
    404, DNS e o próprio "failed to find libstdbuf.so". Cegar o boot é como um
    pendrive certo virou "could not download" sem explicação."""
    fakebin = _fakebin(tmp_path, stdbuf=STDBUF_BOM, aria=ARIA_QUE_FUNCIONA)
    r = _run(
        tmp_path,
        fakebin,
        f"printf '%s\\n%s\\n' '{LINHA_ERRO}' '{LINHA_PROGRESSO}' | nb_aria_progress",
    )
    assert "[ERROR]" in r.stderr, f"a mensagem do aria2 sumiu: {r.stderr!r}"


def test_a_tabela_de_sucesso_do_aria_nao_e_impressa():
    """Repassar o que não é progresso é o que impede o boot de ficar cego — mas
    o aria2 fecha CADA camada com oito linhas de relatório de sucesso
    ("Download Results:", cabeçalho, régua, linha OK, legenda, mais as vazias).
    Três camadas enchem um console VGA de 25 linhas e empurram para fora
    justamente o que serve para diagnosticar.

    A saída certa é não emitir, não filtrar depois: filtrar por texto é como se
    volta a engolir erro."""
    codigo = "\n".join(
        l for l in DOWNLOAD.read_text().splitlines() if not l.lstrip().startswith("#")
    )
    assert "--download-result=hide" in codigo
    assert "Download Results" not in codigo, (
        "a tabela está sendo filtrada por texto; use --download-result=hide"
    )


def test_o_total_de_uma_camada_de_6gb_nao_estoura(tmp_path):
    """A camada base tem 6,1 GiB — acima de 2^31."""
    fakebin = _fakebin(tmp_path, stdbuf=STDBUF_BOM, aria=ARIA_QUE_FUNCIONA)
    r = _run(
        tmp_path,
        fakebin,
        f"echo '{LINHA_GRANDE}' | nb_aria_progress",
    )
    assert "-" not in r.stdout, f"número negativo na barra: {r.stdout!r}"
    assert "6.1 GB" in r.stdout, r.stdout


def test_a_barra_nao_usa_percent_d_para_bytes():
    """`printf "%d"` do awk do busybox — que É o awk do initrd — converte para
    inteiro de 32 BITS: 6,1 GiB vira -2147483648.

    Este é o guarda que roda em qualquer máquina. O teste de valor acima usa o
    awk do host, que é de 64 bits e passaria com `%d` — foi assim que o defeito
    entrou."""
    corpo = "\n".join(
        l for l in DOWNLOAD.read_text().splitlines() if not l.lstrip().startswith("#")
    )
    trecho = corpo[corpo.index("nb_aria_progress()") :]
    trecho = trecho[: trecho.index("nb_download()")]
    assert "%d %d" not in trecho and "%i" not in trecho, (
        "campo de bytes com %d: acima de 2 GiB o awk do busybox trunca em 32 bits"
    )
    assert "%.0f" in trecho


@pytest.mark.skipif(shutil.which("busybox") is None, reason="sem busybox nesta máquina")
def test_o_parser_roda_no_awk_do_busybox(tmp_path):
    """Quando há busybox por perto, roda o parser NELE — é o awk que o initrd
    usa de verdade."""
    fakebin = _fakebin(tmp_path, stdbuf=STDBUF_BOM, aria=ARIA_QUE_FUNCIONA)
    bb = tmp_path / "bb"
    bb.mkdir()
    os.symlink(shutil.which("busybox"), bb / "awk")
    r = _run(
        tmp_path,
        fakebin,
        f"echo '{LINHA_GRANDE}' | nb_aria_progress",
        PATH=f"{bb}:/usr/bin:/bin",
    )
    assert "-" not in r.stdout, f"o awk do busybox truncou: {r.stdout!r}"
    assert "6.1 GB" in r.stdout, r.stdout
