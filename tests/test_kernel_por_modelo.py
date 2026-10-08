"""O kernel por modelo: cada sede recebe o par kernel+initrd do modelo dela.

O kernel tem de casar com os módulos da base (`usr/lib/modules/<versão>`). Com
um par só para o servidor inteiro, uma base nova com kernel novo obrigava toda
sede a trocar junto: o pendrive de uma sede da base antiga se regravava com o
kernel novo e subia sem som, vídeo e wifi, sem erro em lugar nenhum. O modelo
sem `boot_build` continua exatamente como era (o par de `client/build`).
"""

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from server.app import fsdb
from server.app.services import store, usb

REPO = Path(__file__).resolve().parents[1]
BK = {"X-NB-Boot-Key": "nb3b_chave"}


def _par(d: Path, build: str, kernel: str = "") -> dict:
    """Um par kernel+initrd carimbado, como o `nb3-build-initrd` deixa."""
    d.mkdir(parents=True)
    (d / "vmlinuz").write_bytes(f"vmlinuz {build}".encode())
    (d / "initrd.img").write_bytes(f"initrd {build}".encode() * 10)
    arquivos = {
        n: {"md5": hashlib.md5((d / n).read_bytes()).hexdigest(), "size": (d / n).stat().st_size}
        for n in usb.ARQUIVOS_DE_BOOT
    }
    carimbo = {"build": build, "files": arquivos}
    if kernel:
        carimbo["kernel"] = kernel
    fsdb.write_json(d / "build.json", carimbo)
    return arquivos


def _base(blobs: Path, nome: str, versoes: list[str], tmp_path: Path) -> str:
    """Uma camada base de verdade (squashfs), só com os diretórios de módulos."""
    if not shutil.which("mksquashfs") or not shutil.which("unsquashfs"):
        pytest.skip("sem squashfs-tools")
    raiz = tmp_path / f"raiz-{nome}"
    for v in versoes:
        (raiz / "usr" / "lib" / "modules" / v).mkdir(parents=True)
        (raiz / "usr" / "lib" / "modules" / v / "modules.dep").write_text("")
    blobs.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["mksquashfs", str(raiz), str(blobs / nome), "-noappend", "-comp", "gzip"],
        check=True, stdout=subprocess.DEVNULL,
    )
    return nome


@pytest.fixture
def pares(data_root, tmp_path, monkeypatch):
    """O padrão (`client/build`) com o kernel velho e o par `novo`."""
    padrao = tmp_path / "build-padrao"
    monkeypatch.setenv("NB3_BUILD_DIR", str(padrao))
    return {
        "padrao": _par(padrao, "20260101-padrao", kernel="1.0-velho"),
        "novo": _par(usb.builds_dir() / "novo", "20261008-novo", kernel="9.9-novo"),
    }


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def sedes(data_root, pares):
    """Uma sede no modelo antigo (sem boot_build) e uma no modelo novo."""
    fsdb.write_json(data_root / "models" / "velho" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "novo" / "model.json", {"layers": [], "boot_build": "novo"})
    for sede, modelo in (("sala-velha", "velho"), ("sala-nova", "novo")):
        store.create_site_image(sede, sede, modelo, unlocked=True)
        fsdb.write_text(data_root / "site-images" / sede / "boot.key", "nb3b_chave\n")
    return ("sala-velha", "sala-nova")


# --- o que a máquina recebe no boot ---


def test_sem_boot_build_a_sede_continua_no_padrao(client, sedes, pares):
    """É a garantia do deploy: as sedes que já existem não mudam de kernel."""
    r = client.get("/boot/v3/sala-velha/usb", headers=BK)
    assert r.status_code == 200
    linhas = r.text.splitlines()
    assert linhas[0] == "BUILD 20260101-padrao"
    assert pares["padrao"]["initrd.img"]["md5"] in r.text


def test_a_sede_do_modelo_novo_recebe_o_par_do_modelo(client, sedes, pares):
    r = client.get("/boot/v3/sala-nova/usb", headers=BK)
    assert r.text.splitlines()[0] == "BUILD 20261008-novo"
    assert pares["novo"]["vmlinuz"]["md5"] in r.text
    assert pares["padrao"]["vmlinuz"]["md5"] not in r.text
    # e o arquivo que ela baixa é o do par dela, não o do padrão
    arq = client.get("/boot/v3/sala-nova/usbfile/vmlinuz", headers=BK)
    assert arq.status_code == 200
    assert arq.content == b"vmlinuz 20261008-novo"


def test_par_que_sumiu_nao_cai_no_padrao(client, sedes, data_root):
    """Cair no padrão regravaria o pendrive com um kernel sem módulos na base
    deste modelo: a sala subiria sem som, vídeo e wifi."""
    shutil.rmtree(usb.builds_dir() / "novo")
    r = client.get("/boot/v3/sala-nova/usb", headers=BK)
    assert r.text == "BUILD unknown\n"
    assert client.get("/boot/v3/sala-nova/usbfile/vmlinuz", headers=BK).status_code == 404


def test_nome_com_caminho_nao_vira_arquivo(client, sedes, data_root):
    """O nome vira caminho numa rota que só pede a chave de boot, e o diretório
    de dados ao lado tem a chave de todas as sedes."""
    fsdb.write_json(data_root / "models" / "novo" / "model.json", {"layers": [], "boot_build": "../build-padrao"})
    assert client.get("/boot/v3/sala-nova/usb", headers=BK).text == "BUILD unknown\n"
    assert client.get("/boot/v3/sala-nova/usbfile/vmlinuz", headers=BK).status_code == 404
    with pytest.raises(ValueError):
        usb.build_dir("../data")


# --- escolher o kernel do modelo ---


def test_patch_escolhe_e_volta_ao_padrao(client, sedes, ha):
    r = client.patch("/api/v1/models/velho", json={"boot_build": "novo"}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["boot_build"] == "novo"
    assert client.get("/boot/v3/sala-velha/usb", headers=BK).text.startswith("BUILD 20261008-novo")
    r = client.patch("/api/v1/models/velho", json={"boot_build": ""}, headers=ha)
    assert "boot_build" not in r.json()
    assert client.get("/boot/v3/sala-velha/usb", headers=BK).text.startswith("BUILD 20260101-padrao")


@pytest.mark.parametrize("nome", ["../data", "a/b", ".oculto", "Maiusculo"])
def test_patch_recusa_nome_invalido(client, sedes, ha, nome):
    r = client.patch("/api/v1/models/velho", json={"boot_build": nome}, headers=ha)
    assert r.status_code == 400


def test_patch_recusa_par_que_nao_existe(client, sedes, ha):
    r = client.patch("/api/v1/models/velho", json={"boot_build": "nao-existe"}, headers=ha)
    assert r.status_code == 400
    assert "--name nao-existe" in r.json()["detail"]
    assert "boot_build" not in (store.get_model("velho") or {})


def test_so_a_administracao_escolhe_o_kernel(client, sedes, ha, data_root):
    """Trocar o kernel regrava o pendrive de toda sede do modelo."""
    r = client.post("/api/v1/invites", json={"max_images": 1, "max_models": 1, "count": 1}, headers=ha)
    code = r.json()["invites"][0]["code"]
    hs = {"Authorization": f"Bearer {code}"}
    assert client.post("/api/v1/models", json={"name": "meu"}, headers=hs).status_code == 201
    r = client.patch("/api/v1/models/meu", json={"boot_build": "novo"}, headers=hs)
    assert r.status_code == 403
    # o resto do PATCH continua dele
    assert client.patch("/api/v1/models/meu", json={"description": "x"}, headers=hs).status_code == 200


def test_patch_recusa_kernel_sem_modulos_na_base(client, sedes, ha, data_root, tmp_path):
    base = _base(data_root / "blobs", "base-velha.squash", ["1.0-velho"], tmp_path)
    fsdb.write_json(
        data_root / "models" / "velho" / "model.json",
        {"layers": [{"file": base, "md5": "0" * 32, "role": "base"}]},
    )
    r = client.patch("/api/v1/models/velho", json={"boot_build": "novo"}, headers=ha)
    assert r.status_code == 400
    assert "9.9-novo" in r.json()["detail"] and "1.0-velho" in r.json()["detail"]
    # com a base nova no lugar, o mesmo pedido passa
    nova = _base(data_root / "blobs", "base-nova.squash", ["9.9-novo"], tmp_path)
    fsdb.write_json(
        data_root / "models" / "velho" / "model.json",
        {"layers": [{"file": nova, "md5": "0" * 32, "role": "base"}]},
    )
    assert client.patch("/api/v1/models/velho", json={"boot_build": "novo"}, headers=ha).status_code == 200


def test_o_modelo_mostra_o_kernel_e_se_casa_com_a_base(client, sedes, ha, data_root, tmp_path):
    base = _base(data_root / "blobs", "base-nova.squash", ["9.9-novo"], tmp_path)
    fsdb.write_json(
        data_root / "models" / "velho" / "model.json",
        {"layers": [{"file": base, "md5": "0" * 32, "role": "base"}]},
    )
    k = client.get("/api/v1/models/velho", headers=ha).json()["boot_kernel"]
    assert k["kernel"] == "1.0-velho"
    assert k["base_kernels"] == ["9.9-novo"]
    assert k["match"] is False
    client.patch("/api/v1/models/velho", json={"boot_build": "novo"}, headers=ha)
    k = client.get("/api/v1/models/velho", headers=ha).json()["boot_kernel"]
    assert (k["name"], k["kernel"], k["match"]) == ("novo", "9.9-novo", True)


def test_a_copia_do_modelo_leva_o_kernel(client, sedes, ha):
    """A cópia leva a base, então leva o par que tem os módulos dela. É como o
    modelo de um sub-admin nasce."""
    r = client.post("/api/v1/models", json={"name": "copia", "from": "novo"}, headers=ha)
    assert r.status_code == 201, r.text
    assert r.json()["boot_build"] == "novo"


def test_a_lista_de_pares_diz_quem_usa_cada_um(client, sedes, ha, data_root):
    fsdb.write_json(data_root / "models" / "orfao" / "model.json", {"layers": [], "boot_build": "sumiu"})
    pares = {k["name"]: k for k in client.get("/api/v1/usb/kernels", headers=ha).json()["kernels"]}
    assert pares[""]["default"] is True and pares[""]["kernel"] == "1.0-velho"
    assert pares[""]["models"] == ["velho"]
    assert pares["novo"]["models"] == ["novo"] and pares["novo"]["ok"] is True
    # o par citado que não existe aparece, e aparece quebrado: é o aviso
    assert pares["sumiu"]["ok"] is False and pares["sumiu"]["models"] == ["orfao"]
    assert "--name sumiu" in pares["sumiu"]["hint"]


# --- o pendrive gerado pelo servidor ---


FALSO = """#!/bin/bash
saida=""
while [ $# -gt 0 ]; do
    case "$1" in
        --output) saida=$2; shift 2 ;;
        *) echo "arg: $1" >> "$NB3_GENUSB_LOG"; shift ;;
    esac
done
printf 'imagem' > "$saida"
"""


@pytest.fixture
def genusb(tmp_path, monkeypatch):
    p = tmp_path / "genusb-falso"
    p.write_text(FALSO)
    p.chmod(0o755)
    log = tmp_path / "args.log"
    monkeypatch.setenv("NB3_GENUSB_CMD", str(p))
    monkeypatch.setenv("NB3_GENUSB_LOG", str(log))
    return log


def test_o_pendrive_da_sede_sai_com_o_par_do_modelo(sedes, genusb):
    """O padrão do nb3-genusb é client/build: sem o par explícito, a sede do
    modelo novo ganharia o kernel velho no pendrive gravado."""
    estado = asyncio.run(usb.gerar_da_sala("sala-nova"))
    assert estado["status"] == "done", estado
    assert f"arg: {usb.builds_dir() / 'novo' / 'vmlinuz'}" in genusb.read_text()
    assert estado["boot_build"] == "novo"


def test_trocar_de_modelo_marca_o_pendrive_desatualizado(sedes, genusb, data_root):
    asyncio.run(usb.gerar_da_sala("sala-velha"))
    assert usb.image_state("sala-velha")["stale"] is False
    info = store.get_site_image("sala-velha")
    fsdb.write_json(data_root / "site-images" / "sala-velha" / "image.json", {**info, "model": "novo"})
    assert "kernel" in usb.image_state("sala-velha")["stale_reason"]


def test_a_impressao_do_padrao_nao_muda(pares):
    """As imagens de pendrive já geradas guardaram a impressão do padrão sem
    nome. Se ela mudasse, todas apareceriam desatualizadas depois do deploy."""
    assert usb._kernel_fingerprint("").startswith("vmlinuz:")
    assert usb._kernel_fingerprint("novo").startswith("build:novo|")


def test_versao_do_kernel_sai_do_cabecalho_sem_carimbo(tmp_path, monkeypatch):
    """Par gerado antes do carimbo: a versão vem do cabeçalho do bzImage."""
    d = tmp_path / "antigo"
    d.mkdir()
    cab = bytearray(0x400)
    cab[0x202:0x206] = b"HdrS"
    cab[0x20E:0x210] = (0x100).to_bytes(2, "little")
    cab[0x300:0x300 + 30] = b"7.0.0-28-generic (buildd@x) #2"
    (d / "vmlinuz").write_bytes(bytes(cab))
    monkeypatch.setenv("NB3_BUILD_DIR", str(d))
    assert usb.versao_do_kernel() == "7.0.0-28-generic"


# --- o aviso no boot ---


def test_boot_avisa_kernel_sem_modulos_na_base(tmp_path):
    """A única detecção que vale qualquer que seja a causa do descasamento."""
    versao = Path("/proc/sys/kernel/osrelease").read_text().strip()
    script = (
        'nb_warn() { echo "AVISO: $*"; }\n'
        f'. "{REPO}/client/stuff/40-mount.sh"\n'
        'rootmnt=$1\nNB_KERNEL_WARN_WAIT=0\n'
        "nb_kernel_modules_check\n"
    )
    com = tmp_path / "com"
    (com / "usr" / "lib" / "modules" / versao).mkdir(parents=True)
    sem = tmp_path / "sem"
    (sem / "usr" / "lib" / "modules" / "0.0-outro").mkdir(parents=True)
    r = subprocess.run(["sh", "-c", script, "sh", str(com)], capture_output=True, text=True)
    assert r.returncode == 0 and "AVISO" not in r.stdout
    r = subprocess.run(["sh", "-c", script, "sh", str(sem)], capture_output=True, text=True)
    assert r.returncode == 0
    assert f"kernel {versao} has no modules" in r.stdout
    assert r.stdout.isascii()


# --- as ferramentas ---


def test_build_initrd_carimba_o_kernel_e_aceita_nome():
    texto = (REPO / "tools" / "nb3-build-initrd").read_text()
    assert '"kernel": "$KVER"' in texto
    assert 'OUT="$REPO/client/builds/$2"' in texto
    # o mesmo formato de nome que o servidor aceita
    assert usb.NOME_BUILD_RE.pattern.strip("^$") in texto


def _rodar(servidor, *args):
    base, chave = servidor
    return subprocess.run(
        [".venv/bin/python", str(REPO / "tools" / "nb3-nova-temporada"),
         "--server", base, "--admin-key", chave, *args],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )


@pytest.fixture
def anterior(data_root):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(
        data_root / "models" / "ano2025" / "model.json",
        {"name": "ano2025", "owner": "admin", "layers": [
            {"file": "telemetria.squash", "md5": "a" * 32, "role": "telemetry"},
            {"file": "base-2025.squash", "md5": "c" * 32, "role": "base"},
        ]},
    )
    return "ano2025"


def test_temporada_recusa_base_sem_os_modulos_do_kernel(pares, anterior, servidor, tmp_path, data_root):
    """Sem `--boot-build`, o modelo fica no padrão (kernel 1.0-velho), e a base
    nova só tem o 9.9-novo: recusa antes de criar ou enviar qualquer coisa."""
    base = tmp_path / "blobs-locais"
    _base(base, "base-2026.squash", ["9.9-novo"], tmp_path)
    r = _rodar(servidor, "--de", "ano2025", "--para", "ano2026", "--base", str(base / "base-2026.squash"))
    assert r.returncode != 0
    assert "1.0-velho" in r.stderr and "novo" in r.stderr
    assert not (data_root / "models" / "ano2026").exists()


def test_temporada_grava_o_kernel_do_modelo(pares, anterior, servidor, tmp_path, data_root):
    base = tmp_path / "blobs-locais"
    _base(base, "base-2026.squash", ["9.9-novo"], tmp_path)
    r = _rodar(
        servidor, "--de", "ano2025", "--para", "ano2026",
        "--base", str(base / "base-2026.squash"), "--boot-build", "novo",
    )
    assert r.returncode == 0, r.stderr or r.stdout
    modelo = fsdb.read_json(data_root / "models" / "ano2026" / "model.json")
    assert modelo["boot_build"] == "novo"
    assert [c["file"] for c in modelo["layers"] if c["role"] == "base"] == ["base-2026.squash"]
    # o modelo de origem não muda de kernel
    assert "boot_build" not in fsdb.read_json(data_root / "models" / "ano2025" / "model.json")


def test_temporada_recusa_par_que_nao_existe(pares, anterior, servidor, tmp_path, data_root):
    base = tmp_path / "blobs-locais"
    _base(base, "base-2026.squash", ["9.9-novo"], tmp_path)
    r = _rodar(
        servidor, "--de", "ano2025", "--para", "ano2026",
        "--base", str(base / "base-2026.squash"), "--boot-build", "digitado-errado",
    )
    assert r.returncode != 0
    assert "--name digitado-errado" in r.stderr
    assert not (data_root / "models" / "ano2026").exists()
