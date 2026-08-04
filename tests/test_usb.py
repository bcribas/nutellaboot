"""O pendrive pela interface.

Criar uma sede entregava token, chaves e links — e nada sobre o pendrive, que é
o único jeito de a máquina ligar. O gerador só existia na linha de comando da
máquina de gestão, então quem coordena uma sede não tinha acesso nenhum a ele.

São três coisas, e a ordem importa: a imagem genérica (uma só, igual para todas
as sedes, sem segredo dentro), o `nutellaboot.conf` da sala (quatro linhas, com
a chave de boot) e a imagem já configurada, para quem prefere não copiar nada.

O que estes testes protegem, além de "funciona": que o `conf` gerado é o que o
initrd sabe ler, que a imagem genérica não carrega segredo (ela vai para um
diretório público), e que a da sala nunca sai sem credencial.
"""

import asyncio
import json
import os

import pytest

from pathlib import Path

from server.app import fsdb
from server.app.services import usb

REPO = Path(__file__).resolve().parents[1]
CONSOLE = {"X-NB-Console": "1"}

# um "nb3-genusb" de mentira: gerar de verdade precisa de mtools, grub2 e de um
# initrd que só sai com root. O que interessa aqui é o contrato — quais
# argumentos a ferramenta recebe e o que o serviço faz com o resultado.
FALSO = """#!/bin/bash
set -e
saida=""
while [ $# -gt 0 ]; do
    case "$1" in
        --output) saida=$2; shift 2 ;;
        *) echo "arg: $1" >> "${NB3_GENUSB_LOG:-/dev/null}"; shift ;;
    esac
done
mkdir -p "$(dirname "$saida")"
printf 'imagem de mentira' > "$saida"
echo "pronto: $saida"
"""


@pytest.fixture
def build(tmp_path, monkeypatch):
    """Um client/build com kernel e initrd de mentira."""
    d = tmp_path / "build"
    d.mkdir()
    (d / "vmlinuz").write_bytes(b"kernel")
    (d / "initrd.img").write_bytes(b"initrd")
    monkeypatch.setenv("NB3_BUILD_DIR", str(d))
    return d


@pytest.fixture
def genusb(tmp_path, monkeypatch):
    p = tmp_path / "genusb-falso"
    p.write_text(FALSO)
    p.chmod(0o755)
    log = tmp_path / "args.log"
    monkeypatch.setenv("NB3_GENUSB_CMD", str(p))
    monkeypatch.setenv("NB3_GENUSB_LOG", str(log))
    return log


@pytest.fixture
def client(data_root):
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


@pytest.fixture(autouse=True)
def sem_limite():
    from server.app.services import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def sede(client, data_root, ha):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    r = client.post(
        "/api/v1/site-images", json={"id": "sala1", "fullname": "Sala 1", "model": "t"}, headers=ha
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- o nutellaboot.conf: contrato com o initrd ---


def test_o_conf_tem_o_que_o_initrd_procura(data_root, sede):
    """O initrd extrai com `sed -n "s/^\\(set \\)\\{0,1\\}CHAVE=//p"`. Um arquivo
    que ele não entende é a tela "NO IMAGE" na sede, com a fila esperando."""
    texto = usb.conf_text("sala1")
    linhas = {
        l.split("=", 1)[0].removeprefix("set "): l.split("=", 1)[1].strip('"')
        for l in texto.splitlines()
        if l and not l.startswith("#") and "=" in l
    }
    assert linhas["IMAGEROOT"] == "sala1"
    assert linhas["NB_BOOT_KEY"] == sede["boot_key"]
    assert linhas["NB_SERVER"].startswith("http")


def test_o_conf_e_o_que_o_bootstrap_le_de_verdade(data_root, sede, tmp_path):
    """Roda o mesmo `sed` do `nb_conf_value` sobre o arquivo gerado."""
    import subprocess

    arq = tmp_path / "nutellaboot.conf"
    arq.write_text(usb.conf_text("sala1"))
    for chave, esperado in (("IMAGEROOT", "sala1"), ("NB_BOOT_KEY", sede["boot_key"])):
        r = subprocess.run(
            ["sed", "-n", rf"s/^\(set \)\{{0,1\}}{chave}=//p", str(arq)],
            capture_output=True,
            text=True,
        )
        assert r.stdout.strip().strip("\"'") == esperado, chave


# --- kernel e initrd ---


def test_sem_kernel_a_mensagem_traz_o_comando(data_root, tmp_path, monkeypatch):
    """É o único passo do sistema que precisa de root: dizer "veja a
    documentação" não ajuda quem está com a sala parada."""
    monkeypatch.setenv("NB3_BUILD_DIR", str(tmp_path / "nao-existe"))
    k = usb.kernel_state()
    assert k["ok"] is False
    assert "nb3-build-initrd" in k["hint"]


def test_com_kernel_o_estado_fica_ok(build, data_root):
    k = usb.kernel_state()
    assert k["ok"] is True
    assert k["files"]["vmlinuz"]["size"] == 6
    assert k["hint"] == ""


# --- geração ---


def test_gera_a_imagem_da_sala(build, genusb, data_root, sede):
    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    assert estado["status"] == "done", estado
    assert estado["file"].startswith("sala1-")
    assert estado["file"].endswith(".img")
    assert (data_root / "usb" / estado["file"]).is_file()
    # o nome não é adivinhável: o arquivo carrega a chave de boot dentro
    assert estado["file"] != "sala1.img"
    assert len(estado["suffix"]) == 8


def test_a_ferramenta_recebe_a_sede_e_a_chave(build, genusb, data_root, sede):
    asyncio.run(usb.gerar_da_sala("sala1"))
    args = genusb.read_text()
    assert "arg: --imageroot" in args and "arg: sala1" in args
    assert f"arg: {sede['boot_key']}" in args


def test_a_generica_nao_leva_sede_nem_chave(build, genusb, data_root, sede):
    """É o ponto do pendrive genérico: uma imagem serve todas as sedes. E é ela
    que pode ir para um diretório público do servidor de arquivos."""
    asyncio.run(usb.gerar_generica())
    # sem argumento nenhum além do --output, o log nem chega a ser criado
    args = genusb.read_text() if genusb.exists() else ""
    assert "--imageroot" not in args
    assert "--boot-key" not in args
    assert sede["boot_key"] not in args
    assert usb.generic_state()["file"] == "nutellaboot3.img"


def test_regerar_mantem_o_nome(build, genusb, data_root, sede):
    """Se o nome mudasse a cada geração, ficariam cópias antigas no servidor de
    arquivos para sempre — o rsync não apaga o que ficou para trás."""
    primeiro = asyncio.run(usb.gerar_da_sala("sala1"))["file"]
    segundo = asyncio.run(usb.gerar_da_sala("sala1"))["file"]
    assert primeiro == segundo


def test_falha_da_ferramenta_vira_estado_e_nao_excecao(build, data_root, sede, tmp_path, monkeypatch):
    ruim = tmp_path / "ruim"
    ruim.write_text("#!/bin/bash\necho 'faltando: mformat' >&2\nexit 1\n")
    ruim.chmod(0o755)
    monkeypatch.setenv("NB3_GENUSB_CMD", str(ruim))
    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    assert estado["status"] == "failed"
    assert "mformat" in estado["error"]


def test_sem_kernel_nao_tenta_gerar(data_root, sede, tmp_path, monkeypatch):
    monkeypatch.setenv("NB3_BUILD_DIR", str(tmp_path / "vazio"))
    monkeypatch.setenv("NB3_GENUSB_CMD", "/bin/false")
    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    assert estado["status"] == "unavailable"
    assert "nb3-build-initrd" in estado["hint"]


# --- desatualização ---


def test_rotacionar_a_chave_marca_desatualizada(build, genusb, client, data_root, sede, ha):
    asyncio.run(usb.gerar_da_sala("sala1"))
    assert usb.image_state("sala1")["stale"] is False

    r = client.post("/api/v1/site-images/sala1/boot-key/rotate", headers=ha)
    assert r.status_code == 200, r.text

    estado = usb.image_state("sala1")
    assert estado["stale"] is True
    assert "boot_key" in estado["stale_reason"]


def test_initrd_novo_marca_desatualizada(build, genusb, data_root, sede):
    asyncio.run(usb.gerar_da_sala("sala1"))
    assert usb.image_state("sala1")["stale"] is False

    (build / "initrd.img").write_bytes(b"initrd novo e maior")
    estado = usb.image_state("sala1")
    assert estado["stale"] is True
    assert "kernel" in estado["stale_reason"]


def test_regerar_limpa_o_aviso(build, genusb, client, data_root, sede, ha):
    asyncio.run(usb.gerar_da_sala("sala1"))
    client.post("/api/v1/site-images/sala1/boot-key/rotate", headers=ha)
    assert usb.image_state("sala1")["stale"] is True

    asyncio.run(usb.gerar_da_sala("sala1"))
    assert usb.image_state("sala1")["stale"] is False


# --- as rotas ---


def test_o_console_ve_o_estado_geral(build, client, data_root, sede, ha):
    r = client.get("/api/v1/usb", headers=ha)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["kernel"]["ok"] is True
    assert [i["id"] for i in corpo["images"]] == ["sala1"]


def test_estado_geral_e_so_do_admin(client, data_root, sede):
    assert client.get("/api/v1/usb").status_code == 401


def test_a_sede_ve_o_estado_com_o_proprio_token(build, genusb, client, data_root, sede):
    asyncio.run(usb.gerar_da_sala("sala1"))
    r = client.get(
        "/api/v1/site-images/sala1/usb", headers={"Authorization": f"Bearer {sede['token']}"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["image"]["status"] == "done"


def test_baixar_o_conf_com_o_token_da_url(client, data_root, sede):
    """`<a download>` não manda cabeçalho: vale o `tk` que já está na URL da
    tela de sede."""
    r = client.get(f"/api/v1/site-images/sala1/usb/conf?tk={sede['token']}")
    assert r.status_code == 200, r.text
    assert 'set IMAGEROOT="sala1"' in r.text
    assert sede["boot_key"] in r.text
    assert "attachment" in r.headers["content-disposition"]


def test_baixar_o_conf_com_a_sessao_do_console(client, data_root, sede, admin_key):
    client.post("/api/v1/session", json={"key": admin_key}, headers=CONSOLE)
    r = client.get("/api/v1/site-images/sala1/usb/conf")
    assert r.status_code == 200, r.text


def test_o_conf_nao_sai_sem_credencial(client, data_root, sede):
    assert client.get("/api/v1/site-images/sala1/usb/conf").status_code == 401
    assert client.get("/api/v1/site-images/sala1/usb/conf?tk=nb3i_errado").status_code == 401


def test_baixar_a_imagem_da_sala(build, genusb, client, data_root, sede):
    import gzip

    asyncio.run(usb.gerar_da_sala("sala1"))
    r = client.get(f"/api/v1/site-images/sala1/usb/image?tk={sede['token']}")
    assert r.status_code == 200, r.text
    # compactada: a rota nunca mais transmite os 400 MB crus da máquina que
    # atende o boot
    assert gzip.decompress(r.content) == b"imagem de mentira"


def test_a_imagem_da_sala_nao_sai_sem_credencial(build, genusb, client, data_root, sede):
    asyncio.run(usb.gerar_da_sala("sala1"))
    assert client.get("/api/v1/site-images/sala1/usb/image").status_code == 401


def test_token_de_outra_sede_nao_baixa(build, genusb, client, data_root, sede, ha):
    outra = client.post(
        "/api/v1/site-images", json={"id": "sala2", "fullname": "S2", "model": "t"}, headers=ha
    ).json()
    asyncio.run(usb.gerar_da_sala("sala1"))
    r = client.get(f"/api/v1/site-images/sala1/usb/image?tk={outra['token']}")
    assert r.status_code == 401


def test_sede_de_outro_dono_responde_404(build, client, data_root, sede, ha):
    code = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    r = client.get("/api/v1/site-images/sala1/usb", headers={"Authorization": f"Bearer {code}"})
    assert r.status_code == 404


def test_gerar_pela_rota_devolve_na_hora(build, genusb, client, data_root, sede, ha):
    """A rota não pode esperar a geração: o servidor tem um worker só, e
    segurar a requisição congela o SSE e o long-poll da sala inteira."""
    r = client.post("/api/v1/site-images/sala1/usb", headers=ha)
    assert r.status_code == 202, r.text
    assert r.json()["status"] in ("building", "done")


def test_baixar_a_generica_pela_tela_de_sede(build, genusb, client, data_root, sede):
    asyncio.run(usb.gerar_generica())
    r = client.get(f"/api/v1/usb/generic/image?id=sala1&tk={sede['token']}")
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/usb/generic/image").status_code == 401


def test_a_generica_ainda_nao_gerada_responde_404(build, client, data_root, sede, admin_key):
    client.post("/api/v1/session", json={"key": admin_key}, headers=CONSOLE)
    assert client.get("/api/v1/usb/generic/image").status_code == 404


# --- geração automática na criação ---


def test_criar_a_sede_agenda_o_pendrive(build, genusb, client, data_root, ha):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    client.post(
        "/api/v1/site-images", json={"id": "nova", "fullname": "N", "model": "t"}, headers=ha
    )
    # o TestClient roda o laço até o fim da requisição; a tarefa em segundo
    # plano pode ficar em "building" ou já ter terminado
    assert usb.image_state("nova")["status"] in ("building", "done", "unavailable")


def test_o_interruptor_desliga_o_automatico(build, genusb, client, data_root, ha):
    fsdb.write_json(data_root / "server.json", {"usb": {"auto_generate": False}})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    client.post(
        "/api/v1/site-images", json={"id": "nova", "fullname": "N", "model": "t"}, headers=ha
    )
    assert usb.image_state("nova")["status"] == "missing"
    # mas o botão continua funcionando
    r = client.post("/api/v1/site-images/nova/usb", headers=ha)
    assert r.status_code == 202


# --- a ferramenta ---


def test_genusb_nao_embarca_senha_de_exemplo():
    """Sem --wifi, ele copiava o wifi.conf.example inteiro — com
    `ICPC-BR<TAB>senha-da-rede-da-maratona` dentro. A imagem genérica vai para
    um diretório público do servidor de arquivos."""
    from pathlib import Path

    texto = (Path(__file__).resolve().parents[1] / "tools" / "nb3-genusb").read_text()
    assert 'cp "$REPO/client/usb/wifi.conf.example"' not in texto
    assert "grep -E '^[[:space:]]*(#|$)'" in texto


def test_genusb_confere_o_que_usa():
    from pathlib import Path

    texto = (Path(__file__).resolve().parents[1] / "tools" / "nb3-genusb").read_text()
    linha = [l for l in texto.splitlines() if l.startswith("for t in ")][0]
    for ferramenta in ("mdir", "truncate", "dd"):
        assert ferramenta in linha, ferramenta


def test_genusb_respeita_a_raiz_de_dados():
    """Ele copiava para `$REPO/data/usb` na mão; com NB3_DATA_ROOT apontando
    para outro lugar, o servidor não achava o arquivo para reenviar."""
    from pathlib import Path

    texto = (Path(__file__).resolve().parents[1] / "tools" / "nb3-genusb").read_text()
    assert "DATA=${NB3_DATA_ROOT:-$REPO/data}" in texto
    assert "$REPO/data/usb" not in texto


# --- o mesmo arquivo serve ao initrd E ao menu do GRUB ---


def test_o_conf_e_script_valido_do_grub(data_root, sede, tmp_path):
    """O GRUB não entende `IMAGEROOT=26spsp` — para ele isso é o nome de um
    comando. Com `set` na frente o MESMO arquivo diz a sede ao sistema e ao
    menu, sem um segundo arquivo para o operador copiar."""
    import shutil
    import subprocess

    check = shutil.which("grub2-script-check") or shutil.which("grub-script-check")
    if not check:
        pytest.skip("sem grub-script-check para validar")
    arq = tmp_path / "nutellaboot.conf"
    arq.write_text(usb.conf_text("sala1"))
    r = subprocess.run([check, str(arq)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_o_parser_do_initrd_aceita_as_duas_formas(tmp_path):
    """Pendrive já gravado tem o formato antigo e não pode parar de bootar.
    (O caminho inverso — initrd antigo com arquivo novo — é o risco conhecido
    e está avisado dentro do próprio arquivo.)"""
    import re
    import subprocess

    bootstrap = (
        REPO / "client" / "initramfs-tools" / "scripts" / "nutellaboot"
    ).read_text()
    sed = re.search(r'sed -n "(s/\^.*IMAGEROOT.*?)"', bootstrap.replace("$1", "IMAGEROOT"))
    assert sed, "não achei o sed do nb_conf_value"

    for texto, esperado in (("IMAGEROOT=antigo\n", "antigo"), ('set IMAGEROOT="novo"\n', "novo")):
        arq = tmp_path / "c.conf"
        arq.write_text(texto)
        r = subprocess.run(
            ["sh", "-c", f'sed -n "{sed.group(1)}" "{arq}" | tr -d "\\"\'" | sed -n 1p'],
            capture_output=True,
            text=True,
        )
        assert r.stdout.strip() == esperado, (texto, r.stdout)


def test_o_grub_cfg_mostra_a_sede():
    ferramenta = (REPO / "tools" / "nb3-genusb").read_text()
    assert "source /nutellaboot.conf" in ferramenta
    assert "nb3_sede" in ferramenta


# --- o nome de exibição da sede ---


def test_o_conf_leva_o_nome_de_exibicao(data_root, sede):
    """O GRUB não tem rede: o `nutellaboot.conf` é o único caminho para o nome
    da sede chegar ao menu de boot."""
    linhas = usb.conf_text("sala1").splitlines()
    assert 'set NB_SITE_NAME="Sala 1"' in linhas
    assert 'set IMAGEROOT="sala1"' in linhas


def test_o_menu_do_grub_usa_o_nome_e_cai_para_o_id():
    """Pendrive genérico editado à mão não tem nome nenhum, e mostrar o
    identificador é melhor que não mostrar nada."""
    ferramenta = (REPO / "tools" / "nb3-genusb").read_text()
    assert "NB_SITE_NAME" in ferramenta
    trecho = ferramenta[ferramenta.index("set nb3_sede=") :]
    trecho = trecho[: trecho.index("menuentry")]
    # os três degraus: com nome, só com id, e nada
    assert trecho.count("set nb3_sede=") == 3, trecho


def test_a_ferramenta_aceita_o_nome_de_exibicao():
    ferramenta = (REPO / "tools" / "nb3-genusb").read_text()
    assert "--fullname" in ferramenta


# --- a ferramenta rodando de verdade ---
#
# Não havia teste nenhum que EXECUTASSE o nb3-genusb: os que existiam liam o
# texto do arquivo. Foi por essa fresta que o `NB_SITE_NAME` saiu ausente do
# pendrive gerado à mão — a ferramenta escrevia a linha, mas só quando alguém
# passava `--fullname`, e quem gera o pendrive da sede não passa.
#
# Uma imagem de 40 MB com kernel e initrd de mentira sai em 0,4 s. Barato o
# bastante para rodar sempre, e é o único teste que olha o arquivo que a sede
# recebe de verdade.

FERRAMENTAS_USB = ("sfdisk", "mformat", "mcopy", "mmd", "mdir", "truncate", "dd", "grub2-mkstandalone")


def _gera_pendrive(tmp_path, imagem: str, fullname: str, *extra: str):
    import shutil
    import subprocess

    faltando = [t for t in FERRAMENTAS_USB if not shutil.which(t)]
    if faltando:
        pytest.skip(f"sem {', '.join(faltando)} para gerar a imagem")

    data = tmp_path / "data"
    (data / "site-images" / imagem).mkdir(parents=True)
    (data / "site-images" / imagem / "image.json").write_text(
        json.dumps({"id": imagem, "fullname": fullname, "model": "t"}), encoding="utf-8"
    )
    (tmp_path / "vmlinuz").write_bytes(b"kernel")
    (tmp_path / "initrd.img").write_bytes(b"initrd")
    saida = tmp_path / "p.img"
    r = subprocess.run(
        [
            str(REPO / "tools" / "nb3-genusb"),
            "--output", str(saida),
            "--imageroot", imagem,
            "--no-bios",
            "--size", "40",
            "--kernel", str(tmp_path / "vmlinuz"),
            "--initrd", str(tmp_path / "initrd.img"),
            *extra,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "NB3_DATA_ROOT": str(data)},
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    def ler(nome: str) -> str:
        p = subprocess.run(
            ["mcopy", "-i", f"{saida}@@{2048 * 512}", f"::/{nome}", "-"],
            capture_output=True,
            text=True,
        )
        assert p.returncode == 0, p.stderr
        return p.stdout

    return r.stdout, ler


def test_a_ferramenta_busca_o_nome_da_sede_sozinha(tmp_path):
    """Quem gera o pendrive da sede não digita `--fullname` — e não deveria
    precisar: a ferramenta já recebeu o `--imageroot` e sabe onde fica o
    registro. Sem isto o menu do GRUB fica sem o nome, sem ninguém errar nada."""
    saida, ler = _gera_pendrive(tmp_path, "sala1", "Sede São Paulo")
    assert 'set NB_SITE_NAME="Sede São Paulo"' in ler("nutellaboot.conf")
    assert 'set IMAGEROOT="sala1"' in ler("nutellaboot.conf")
    assert "Sede São Paulo" in saida, "a saída não diz qual sede foi gravada"


def test_a_linha_de_comando_ganha_do_registro(tmp_path):
    _, ler = _gera_pendrive(tmp_path, "sala1", "Do registro", "--fullname", "Da linha")
    assert 'set NB_SITE_NAME="Da linha"' in ler("nutellaboot.conf")


def test_sem_nome_no_registro_a_ferramenta_avisa(tmp_path):
    """Silêncio foi o que deixou o pendrive sair sem o nome no menu."""
    saida, ler = _gera_pendrive(tmp_path, "sala1", "")
    assert "NB_SITE_NAME" not in ler("nutellaboot.conf")
    assert "sem nome de exibição" in saida, saida


def test_o_pendrive_gerado_tem_grub_valido(tmp_path):
    """O grub.cfg é gerado por concatenação de texto; um erro ali só aparece na
    máquina, com o menu vazio."""
    import shutil
    import subprocess

    check = shutil.which("grub2-script-check") or shutil.which("grub-script-check")
    _, ler = _gera_pendrive(tmp_path, "sala1", 'R$ 10 "x" \\ `y`')
    conf = ler("nutellaboot.conf")
    cfg = ler("grub.cfg")
    if not check:
        pytest.skip("sem grub-script-check")
    for nome, texto in (("nutellaboot.conf", conf), ("grub.cfg", cfg)):
        p = tmp_path / nome
        p.write_text(texto, encoding="utf-8")
        r = subprocess.run([check, str(p)], capture_output=True, text=True)
        assert r.returncode == 0, f"{nome}: {r.stderr}\n{texto}"


@pytest.mark.parametrize(
    "nome",
    [
        'R$ 10 "Escola" \\ `x`',
        "Sede São Paulo — nº 3",
        "linha\ncom\nquebra",
        "",
    ],
)
def test_um_nome_hostil_nao_derruba_o_source_do_grub(data_root, sede, tmp_path, nome):
    """`set NB_SITE_NAME="R$ 10"` faz o `source` do GRUB FALHAR — e, junto com
    ele, o IMAGEROOT some: o menu inteiro perde a sede por causa do nome.

    Acento tem que sobreviver: transliterar deixaria o nome errado na tela por
    medo de um problema que não existe."""
    import shutil
    import subprocess

    p = data_root / "site-images" / "sala1" / "image.json"
    info = fsdb.read_json(p, {})
    info["fullname"] = nome
    fsdb.write_json(p, info)

    texto = usb.conf_text("sala1")
    arq = tmp_path / "nutellaboot.conf"
    arq.write_text(texto)

    check = shutil.which("grub2-script-check") or shutil.which("grub-script-check")
    if check:
        r = subprocess.run([check, str(arq)], capture_output=True, text=True)
        assert r.returncode == 0, f"{r.stderr}\n---\n{texto}"

    # e o initrd continua lendo o IMAGEROOT depois dele
    r = subprocess.run(
        ["sh", "-c", rf'sed -n "s/^\(set \)\{{0,1\}}IMAGEROOT=//p" "{arq}" | tr -d "\"\'" | sed -n 1p'],
        capture_output=True,
        text=True,
    )
    assert r.stdout.strip() == "sala1", texto

    if "São" in nome:
        assert "São Paulo" in texto, "o acento foi embora"


def test_o_bios_legado_tem_o_modulo_test():
    """O grub-embed.cfg usa `[ -z "$root" ]`, e `test` não estava na lista de
    módulos do core.img: em BIOS legado a busca reserva pela label morria com
    "can't find command '['"."""
    ferramenta = (REPO / "tools" / "nb3-genusb").read_text()
    linha = [l for l in ferramenta.splitlines() if "biosdisk part_msdos" in l][0]
    assert " test" in linha, linha


def test_a_ferramenta_acha_o_grub_das_duas_distribuicoes():
    """`grub2-*` no Fedora, `grub-*` no Debian/Ubuntu.

    Este script nasceu numa máquina Fedora e só funcionava lá: no servidor de
    produção a geração do pendrive falhava com "faltando: grub2-mkstandalone",
    e o botão da interface só dizia isso depois de tentar a imagem inteira."""
    ferramenta = (REPO / "tools" / "nb3-genusb").read_text()
    assert "grub-mkstandalone" in ferramenta and "grub2-mkstandalone" in ferramenta
    # e nenhuma chamada direta ao nome do Fedora
    codigo = "\n".join(
        l for l in ferramenta.splitlines() if not l.lstrip().startswith("#")
    )
    for linha in codigo.splitlines():
        assert not linha.strip().startswith(("grub2-mkstandalone", "grub2-mkimage")), linha


# --- o download: redirecionar, ou compactar aqui ------------------------------
#
# A rota transmitia os 400 MB CRUS do disco local, pela mesma máquina que
# atende o boot de 1600 computadores — o tráfego que a publicação existe para
# tirar dali. Agora ela redireciona para o `.gz` do servidor de arquivos, e só
# compacta na hora quando não há cópia lá.


def _publica(data_root, nome, *, quando, url="https://files.exemplo/mlbootimages/x.img.gz"):
    fsdb.write_json(
        data_root / "publish" / f"{nome}.json",
        {"file": nome, "kind": "usb", "status": "done", "url": url, "published_at": quando},
    )


def _mtime(data_root, nome):
    return (data_root / "usb" / nome).stat().st_mtime


def test_publicada_e_atual_redireciona(client, build, genusb, data_root, sede):
    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    _publica(data_root, estado["file"], quando=_mtime(data_root, estado["file"]) + 10)

    r = client.get(f"/api/v1/site-images/sala1/usb/image?tk={sede['token']}", follow_redirects=False)
    assert r.status_code == 302, r.text
    assert r.headers["location"].endswith(".img.gz"), r.headers["location"]


def test_publicada_e_velha_nao_redireciona(client, build, genusb, data_root, sede):
    """O arquivo de lá tem a chave de boot ANTERIOR: quem o gravar fica com uma
    sede que não boota e nada explicando. Regerar sem republicar é o caminho
    comum para isso — o botão apontava para o velho."""
    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    _publica(data_root, estado["file"], quando=_mtime(data_root, estado["file"]) - 10)

    r = client.get(f"/api/v1/site-images/sala1/usb/image?tk={sede['token']}", follow_redirects=False)
    assert r.status_code == 200, r.text
    assert usb.image_state("sala1")["publish_stale"] is True
    assert usb.image_state("sala1")["public_url"] == ""


def test_sem_publicacao_vem_compactado_daqui(client, build, genusb, data_root, sede):
    import gzip

    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    original = (data_root / "usb" / estado["file"]).read_bytes()

    r = client.get(f"/api/v1/site-images/sala1/usb/image?tk={sede['token']}", follow_redirects=False)
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"\x1f\x8b", "não veio gzip"
    assert gzip.decompress(r.content) == original
    assert r.headers["content-disposition"].endswith('.img.gz"'), r.headers["content-disposition"]


def test_a_generica_segue_a_mesma_regra(client, build, genusb, data_root, sede):
    estado = asyncio.run(usb.gerar_generica())
    r = client.get(f"/api/v1/usb/generic/image?id=sala1&tk={sede['token']}", follow_redirects=False)
    assert r.status_code == 200
    assert r.content[:2] == b"\x1f\x8b"

    _publica(data_root, estado["file"], quando=_mtime(data_root, estado["file"]) + 10)
    r = client.get(f"/api/v1/usb/generic/image?id=sala1&tk={sede['token']}", follow_redirects=False)
    assert r.status_code == 302


def test_publicar_dentro_da_geracao_nao_conta_como_velha(client, build, genusb, data_root, sede):
    """O `nb3-genusb --publish` envia DENTRO da geração, e o `built_at` só é
    carimbado quando a ferramenta volta. Comparando com ele, toda imagem
    publicada do jeito normal aparecia velha por alguns microssegundos — e o
    redirecionamento nunca disparava. Aconteceu nas 54 sedes da produção.

    A comparação é com o mtime do arquivo, que responde à pergunta certa: o
    arquivo daqui mudou depois de eu mandá-lo?"""
    estado = asyncio.run(usb.gerar_da_sala("sala1"))
    # publicado uma fração ANTES do fim da geração, como acontece de verdade
    _publica(data_root, estado["file"], quando=estado["built_at"] - 0.001)

    e = usb.image_state("sala1")
    assert e["publish_stale"] is False, "publicação normal marcada como velha"
    assert e["public_url"]
    r = client.get(f"/api/v1/site-images/sala1/usb/image?tk={sede['token']}", follow_redirects=False)
    assert r.status_code == 302


def test_o_download_continua_pedindo_credencial(client, build, genusb, data_root, sede):
    """Mesmo redirecionando: o nome do arquivo publicado é imprevisível de
    propósito, e é a credencial que decide quem o descobre."""
    asyncio.run(usb.gerar_da_sala("sala1"))
    assert client.get("/api/v1/site-images/sala1/usb/image", follow_redirects=False).status_code == 401
    assert client.get("/api/v1/usb/generic/image", follow_redirects=False).status_code == 401
