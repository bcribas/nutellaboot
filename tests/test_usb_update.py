"""O pendrive que se atualiza sozinho.

Esta é a parte do sistema que MEXE no pendrive de boot da sede. Se ela errar, o
resultado não é uma tela feia: é um pendrive que não liga mais, no meio de uma
sala de prova. Por isso o exercício aqui é o caminho inteiro, com um pendrive
de mentira em disco, e não a leitura do texto do script.

O que cada teste protege está no seu docstring; o resumo é:

  * checagem NÃO tem poder de veto — servidor fora do ar, resposta estranha ou
    initrd sem carimbo deixam o boot seguir;
  * o pendrive só é tocado depois de os arquivos novos estarem no disco local e
    com o md5 conferido;
  * falha de REDE não condena o pendrive (nada foi tocado); falha de ESCRITA
    condena, e por isso é marcada — uma tentativa por versão, ou um pendrive
    protegido contra escrita reiniciaria a máquina para sempre;
  * `nutellaboot.conf` e `wifi.conf` são da sede. Não se toca.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUFF = REPO / "client" / "stuff"

# O stuff como a máquina o recebe: os módulos concatenados, com as funções de
# log do initramfs-tools por cima.
HARNESS = """
export PATH="$FAKEBIN:$PATH"
log_begin_msg() { printf 'BEGIN %s\\n' "$*"; }
log_end_msg() { :; }
log_warning_msg() { printf 'WARN %s\\n' "$*"; }
log_failure_msg() { printf 'FAIL %s\\n' "$*"; }
# funções, não binários falsos: no initramfs de verdade `reboot -f` não volta,
# e um binário de mentira não tem como encerrar o shell que o chamou
reboot() { echo REBOOT >> "$ACOES"; exit 0; }
panic() { echo "PANIC $*" >> "$ACOES"; exit 0; }
. "$STUFF/00-header.sh"
. "$STUFF/05-ui.sh"
. "$STUFF/20-download.sh"
. "$STUFF/25-usbupdate.sh"
"""

VMLINUZ = b"kernel novo" * 100
INITRD = b"initrd novo" * 200


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


@pytest.fixture
def cenario(tmp_path):
    """Um pendrive de mentira (um diretório), um servidor de mentira (arquivos)
    e comandos de mentira para tudo que mexe no sistema."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    pendrive = tmp_path / "pendrive"
    pendrive.mkdir()
    # o que já estava gravado, incluindo o que é da sede
    (pendrive / "vmlinuz").write_bytes(b"kernel velho")
    (pendrive / "initrd.img").write_bytes(b"initrd velho")
    (pendrive / "nutellaboot.conf").write_text('set IMAGEROOT="sala1"\n')
    (pendrive / "wifi.conf").write_text("rede\tsenha\n")

    servidor = tmp_path / "servidor"
    servidor.mkdir()
    (servidor / "vmlinuz").write_bytes(VMLINUZ)
    (servidor / "initrd.img").write_bytes(INITRD)

    storage = tmp_path / "storage"
    storage.mkdir()

    def falso(nome, corpo):
        p = fakebin / nome
        p.write_text("#!/bin/sh\n" + corpo)
        p.chmod(0o755)

    # `blkid -L NB3CFG` responde o "dispositivo" quando o arquivo-sentinela
    # existe: é assim que o teste liga e desliga o pendrive da máquina
    falso("blkid", f'[ -e "{tmp_path}/plugado" ] && echo "{pendrive}" || exit 2\n')
    # mount/umount viram no-op: o "dispositivo" já é o diretório montado
    falso("mount", f'[ -e "{tmp_path}/somenteleitura" ] && exit 1\nexit 0\n')
    falso("umount", "exit 0\n")
    falso("sync", "exit 0\n")
    # nb_get: a resposta da rota /boot/v3/<img>/usb
    falso("wget.good", f'cat "{tmp_path}/resposta" 2>/dev/null || exit 1\n')
    # aria2c: copia do "servidor" para o destino, como o de verdade faria
    falso(
        "aria2c",
        f"""
dir=. ; base=saida ; url=
while [ $# -gt 0 ]; do
    case $1 in
        -d) dir=$2; shift 2 ;;
        -o) base=$2; shift 2 ;;
        http*) url=$1; shift ;;
        *) shift ;;
    esac
done
nome=${{url##*/}}
[ -f "{servidor}/$nome" ] || exit 3
cp "{servidor}/$nome" "$dir/$base"
""",
    )

    (tmp_path / "plugado").write_text("")

    class C:
        pass

    c = C()
    c.tmp, c.fakebin, c.pendrive, c.servidor, c.storage = (
        tmp_path,
        fakebin,
        pendrive,
        servidor,
        storage,
    )
    c.acoes = tmp_path / "acoes"
    c.resposta = tmp_path / "resposta"
    c.responder = lambda texto: c.resposta.write_text(texto)
    c.responder(
        "BUILD novo-1\n"
        f"{md5(VMLINUZ)} vmlinuz https://s/boot/v3/sala1/usbfile/vmlinuz\n"
        f"{md5(INITRD)} initrd.img https://s/boot/v3/sala1/usbfile/initrd.img\n"
    )
    return c


def roda(c, *, build="velho-0", extra="", **env):
    corpo = HARNESS + f"""
IMAGEROOT=sala1
NB_SERVER=https://s
NB_INITRD_BUILD={build}
STORAGEDIR="{c.storage}"
NB_USB_MNT="{c.pendrive}"
NB_USB_TRIES=1
NB_USB_WAIT=0
NB_USB_REBOOT_WAIT=0
NB_FATAL_WAIT=0
{extra}
nb_usb_update
echo "SAIU=$?"
"""
    e = {
        "STUFF": str(STUFF),
        "FAKEBIN": str(c.fakebin),
        "ACOES": str(c.acoes),
        "PATH": "/usr/bin:/bin",
        "NB_UI_PLAIN": "1",
        "NB_DOWNLOAD_TRIES": "1",
        **{k: str(v) for k, v in env.items()},
    }
    return subprocess.run(
        ["sh", "-c", corpo], capture_output=True, text=True, env=e, cwd=str(c.tmp)
    )


def test_pendrive_em_dia_nao_faz_nada(cenario):
    r = roda(cenario, build="novo-1")
    assert "SAIU=0" in r.stdout, r.stdout
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == b"kernel velho"
    assert not cenario.acoes.exists(), "reiniciou sem precisar"


def test_initrd_sem_carimbo_nao_confere_nada(cenario):
    """Initrd anterior a esta mudança não sabe a própria versão. Recusá-lo
    seria recusar todos os pendrives já gravados de uma vez."""
    r = roda(cenario, build="")
    assert "SAIU=0" in r.stdout, r.stdout
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == b"kernel velho"


def test_servidor_fora_do_ar_deixa_o_boot_seguir(cenario):
    """Verificação não tem poder de veto — foi a lição da barra de progresso,
    e aqui o custo de errar é a sala inteira."""
    cenario.resposta.unlink()
    r = roda(cenario)
    assert "SAIU=0" in r.stdout, r.stdout
    assert not cenario.acoes.exists()


def test_servidor_sem_build_json_nao_exige_nada(cenario):
    """Construção anterior a isto responde `BUILD unknown`: não dá para exigir
    que um pendrive se atualize para uma versão que ninguém sabe nomear."""
    cenario.responder("BUILD unknown\n")
    r = roda(cenario)
    assert "SAIU=0" in r.stdout, r.stdout
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == b"kernel velho"


def test_atualiza_e_reinicia(cenario):
    """O caminho feliz: baixa, confere o md5, grava e reinicia."""
    r = roda(cenario)
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == VMLINUZ, r.stdout
    assert cenario.pendrive.joinpath("initrd.img").read_bytes() == INITRD
    assert "REBOOT" in cenario.acoes.read_text()


def test_o_que_e_da_sede_nao_e_tocado(cenario):
    """`nutellaboot.conf` tem a sede e a chave de boot; `wifi.conf`, a senha da
    rede. Sobrescrever qualquer um dos dois transforma a atualização num
    pendrive genérico — e a sala não liga mais."""
    roda(cenario)
    assert cenario.pendrive.joinpath("nutellaboot.conf").read_text() == 'set IMAGEROOT="sala1"\n'
    assert cenario.pendrive.joinpath("wifi.conf").read_text() == "rede\tsenha\n"


def test_md5_errado_nao_chega_perto_do_pendrive(cenario):
    """Conferir DEPOIS de gravar seria conferir tarde: os arquivos antigos já
    teriam saído para os novos caberem."""
    cenario.responder(
        "BUILD novo-1\n"
        f"{'0' * 32} vmlinuz https://s/boot/v3/sala1/usbfile/vmlinuz\n"
        f"{md5(INITRD)} initrd.img https://s/boot/v3/sala1/usbfile/initrd.img\n"
    )
    r = roda(cenario)
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == b"kernel velho", r.stdout
    assert "SAIU=0" in r.stdout, "falha de download tem que deixar o boot seguir"


def test_falha_de_rede_nao_condena_o_pendrive(cenario):
    """Nada foi tocado ainda, e queda de rede é transitória: marcar aqui
    transformaria um blip em máquina condenada para sempre."""
    cenario.servidor.joinpath("initrd.img").unlink()
    r = roda(cenario)
    assert "SAIU=0" in r.stdout, r.stdout
    assert not (cenario.storage / ".usbupd-tried").exists(), "marcou uma falha de rede"
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == b"kernel velho"


def test_sem_pendrive_na_maquina_para_com_instrucao(cenario):
    """O boot manda retirar o pendrive assim que a configuração é lida, então
    este é o caso comum — e a instrução é 'coloque de volta e ligue de novo'."""
    (cenario.tmp / "plugado").unlink()
    r = roda(cenario)
    assert "OLD USB" in r.stdout, r.stdout
    assert "plug the usb drive back in" in r.stdout.lower()
    assert "REBOOT" in cenario.acoes.read_text()


def test_uma_tentativa_de_escrita_por_versao(cenario):
    """Sem esta trava, um pendrive protegido contra escrita reinicia a máquina
    para sempre."""
    (cenario.tmp / "somenteleitura").write_text("")
    r1 = roda(cenario)
    assert "USB FAILED" in r1.stdout, r1.stdout
    assert (cenario.storage / ".usbupd-tried").read_text().strip() == "novo-1"

    # segunda vez: nem tenta montar
    r2 = roda(cenario)
    assert "already tried once" in r2.stdout, r2.stdout


def test_a_escotilha_da_linha_de_comando(cenario):
    """Para o dia em que a prova começou e não dá para esperar um reinício."""
    r = roda(cenario, extra="nousbupdate=y")
    assert "SAIU=0" in r.stdout, r.stdout
    assert cenario.pendrive.joinpath("vmlinuz").read_bytes() == b"kernel velho"


# --- o lado do servidor ---


@pytest.fixture
def sede_com_build(data_root, tmp_path, monkeypatch):
    """Uma sede com chave de boot e uma construção carimbada em client/build."""
    from server.app import fsdb
    from server.app.services import store

    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    store.create_site_image("sala1", "Sala 1", "t", unlocked=True)
    fsdb.write_text(data_root / "site-images" / "sala1" / "boot.key", "nb3b_chave\n")

    build = tmp_path / "build"
    build.mkdir()
    (build / "vmlinuz").write_bytes(VMLINUZ)
    (build / "initrd.img").write_bytes(INITRD)
    monkeypatch.setenv("NB3_BUILD_DIR", str(build))
    return build


@pytest.fixture
def cliente(data_root):
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


BK = {"X-NB-Boot-Key": "nb3b_chave"}


def test_a_rota_diz_a_versao_e_como_baixar(cliente, sede_com_build):
    """Primeira linha `BUILD <id>`, depois o MESMO formato do manifest de
    camadas — o cliente reaproveita nb_download e nutella_md5sum sem parser
    novo."""
    from server.app import fsdb

    fsdb.write_json(
        sede_com_build / "build.json",
        {
            "build": "20260803-2038-abcd",
            "files": {
                "vmlinuz": {"md5": md5(VMLINUZ), "size": len(VMLINUZ)},
                "initrd.img": {"md5": md5(INITRD), "size": len(INITRD)},
            },
        },
    )
    linhas = cliente.get("/boot/v3/sala1/usb", headers=BK).text.strip().splitlines()
    assert linhas[0] == "BUILD 20260803-2038-abcd"
    assert linhas[1].startswith(f"{md5(VMLINUZ)} vmlinuz http")
    assert linhas[2].startswith(f"{md5(INITRD)} initrd.img http")


def test_sem_build_json_a_rota_diz_unknown(cliente, sede_com_build):
    """Construção anterior a isto. Exigir atualização para uma versão que o
    servidor não sabe nomear travaria a sala por nada."""
    assert cliente.get("/boot/v3/sala1/usb", headers=BK).text.strip() == "BUILD unknown"


def test_a_rota_entrega_os_arquivos(cliente, sede_com_build):
    r = cliente.get("/boot/v3/sala1/usbfile/initrd.img", headers=BK)
    assert r.status_code == 200
    assert r.content == INITRD


def test_o_nome_do_arquivo_sai_de_uma_lista_fechada(cliente, sede_com_build):
    """É caminho vindo da URL indo para o disco, e o diretório vizinho tem a
    chave de boot de todas as sedes."""
    for nome in ("build.json", "..%2f..%2fetc%2fpasswd", "boot.key"):
        r = cliente.get(f"/boot/v3/sala1/usbfile/{nome}", headers=BK)
        assert r.status_code == 404, nome


def test_a_rota_exige_a_chave_de_boot(cliente, sede_com_build):
    assert cliente.get("/boot/v3/sala1/usb").status_code == 401
    assert cliente.get("/boot/v3/sala1/usbfile/vmlinuz").status_code == 401


def test_o_stuff_chama_a_verificacao_antes_das_camadas():
    """Depois do disco (é onde os arquivos são conferidos) e antes dos 6 GB de
    camada — senão a máquina baixa tudo para reiniciar em seguida."""
    main = (STUFF / "90-main.sh").read_text()
    assert "nb_usb_update" in main
    assert main.index("runpremountconfigs\n") < main.index("nb_usb_update")
    assert main.index("nb_usb_update") < main.index("mount_layers")
