"""Construção de camada extra SEM ROOT, de ponta a ponta.

Este é o teste que protege a parte mais delicada do sistema: no NutellaBoot 2
a camada era feita à mão (tar do overlay em RAM, poda manual, mksquashfs,
md5, edição do template.extra) e camadas reais chegaram a ser publicadas com
/etc/shadow dentro. Aqui montamos uma base sintética, rodamos o worker de
verdade e conferimos o que foi parar na camada.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "tools" / "nb3-layer-worker"
FERRAMENTAS = ["unshare", "squashfuse", "fuse-overlayfs", "bwrap", "mksquashfs", "unsquashfs"]

pytestmark = pytest.mark.skipif(
    any(shutil.which(t) is None for t in FERRAMENTAS),
    reason="faltam ferramentas rootless (bubblewrap, squashfuse, fuse-overlayfs, squashfs-tools)",
)

# apt-get de mentira: cria arquivos como um pacote real criaria, incluindo o
# lixo que a poda precisa remover e um hash de senha que não pode vazar.
FAKE_APT = """#!/bin/sh
[ "$1" = update ] && echo "Lendo listas... Pronto" && exit 0
shift 2
mkdir -p /usr/share/pacote-teste /var/cache/apt /var/log
echo "arquivo entregue pelo pacote $*" > /usr/share/pacote-teste/instalado.txt
echo lixo > /var/cache/apt/pkgcache.bin
echo log > /var/log/apt-teste.log
echo 'root:$6$SEGREDO$naoPodeVazar:20000:0:99999:7:::' > /etc/shadow
echo 'servico:$6$OUTRO$tambemNao:20000:0:99999:7:::' >> /etc/shadow
echo "instalado: $*"
"""


def _copiar_binario(origem: str, rootfs: Path) -> None:
    destino = rootfs / "bin" / Path(origem).name
    shutil.copy(origem, destino)
    saida = subprocess.run(["ldd", origem], capture_output=True, text=True).stdout
    for linha in saida.splitlines():
        partes = linha.split()
        for p in partes:
            if p.startswith("/") and Path(p).is_file():
                alvo = rootfs / "lib64" / Path(p).name
                if not alvo.exists():
                    shutil.copy(Path(p).resolve(), alvo)


@pytest.fixture(scope="module")
def base_squash(tmp_path_factory):
    """Rootfs mínimo (sh + utilitários) empacotado como squashfs."""
    tmp = tmp_path_factory.mktemp("base")
    rootfs = tmp / "rootfs"
    for d in ("bin", "lib64", "usr/bin", "usr/sbin", "usr/share", "etc", "var", "proc", "dev", "tmp", "run"):
        (rootfs / d).mkdir(parents=True, exist_ok=True)
    for prog in ("/bin/sh", "/bin/mkdir", "/bin/cat", "/bin/echo", "/bin/ls", "/bin/rm"):
        if Path(prog).is_file():
            _copiar_binario(prog, rootfs)
    ld = Path("/lib64/ld-linux-x86-64.so.2")
    if ld.exists():
        shutil.copy(ld.resolve(), rootfs / "lib64" / ld.name)
    (rootfs / "usr" / "bin" / "apt-get").write_text(FAKE_APT)
    (rootfs / "usr" / "bin" / "apt-get").chmod(0o755)
    # o PATH do sandbox precisa achar mkdir & cia.
    for prog in ("mkdir", "cat", "echo", "ls", "rm"):
        alvo = rootfs / "usr" / "bin" / prog
        if (rootfs / "bin" / prog).exists() and not alvo.exists():
            alvo.symlink_to(f"/bin/{prog}")

    squash = tmp / "base.squash"
    subprocess.run(
        ["mksquashfs", str(rootfs), str(squash), "-comp", "zstd", "-noappend", "-quiet", "-all-root"],
        check=True,
        capture_output=True,
    )
    return squash


@pytest.fixture
def ambiente(tmp_path, base_squash):
    data = tmp_path / "data"
    (data / "blobs").mkdir(parents=True)
    (data / "layerbuilds" / "queue").mkdir(parents=True)
    shutil.copy(base_squash, data / "blobs" / "base.squash")
    md5 = hashlib.md5((data / "blobs" / "base.squash").read_bytes()).hexdigest()
    tpl = data / "templates" / "tteste"
    tpl.mkdir(parents=True)
    (tpl / "template.json").write_text(
        json.dumps({"layers": [{"md5": md5, "file": "base.squash", "cdn_url": "file:///inexistente"}]})
    )
    return {"data": data, "build": tmp_path / "build"}


def rodar_worker(ambiente, job: dict) -> subprocess.CompletedProcess:
    fila = ambiente["data"] / "layerbuilds" / "queue"
    (fila / f"{job['id']}.json").write_text(json.dumps(job))
    return subprocess.run(
        [str(WORKER), "--once"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "NB3_DATA_ROOT": str(ambiente["data"]),
            "NB3_BUILD_DIR": str(ambiente["build"]),
        },
    )


def conteudo_da_camada(squash: Path) -> list[str]:
    saida = subprocess.run(
        ["unsquashfs", "-ll", str(squash)], capture_output=True, text=True
    ).stdout
    return [
        linha.split("squashfs-root/", 1)[1]
        for linha in saida.splitlines()
        if "squashfs-root/" in linha
    ]


def test_worker_anexa_camada_sozinho(ambiente):
    """Build com attach_to preenchido (caminho do auto-atendimento): o worker
    anexa a camada à imagem ao terminar, sem passo manual do admin."""
    data = ambiente["data"]
    (data / "server.json").write_text(json.dumps({"base_url": "https://exemplo.test"}))
    img = data / "images" / "labauto"
    img.mkdir(parents=True)
    (img / "image.json").write_text(json.dumps({"id": "labauto", "template": "tteste"}))
    (img / "layers-extra.json").write_text("[]")

    job = {
        "id": "ja",
        "name": "camada-auto",
        "template": "tteste",
        "packages": ["htop"],
        "created_at": 0,
        "image": "labauto",
        "attach_to": ["labauto"],
    }
    proc = rodar_worker(ambiente, job)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    extras = json.loads((img / "layers-extra.json").read_text())
    assert len(extras) == 1
    assert extras[0]["file"].startswith("camada-auto-")
    # a URL de download saiu absoluta, com a base do server.json
    assert extras[0]["cdn_url"].startswith("https://exemplo.test/blobs/")
    assert extras[0]["from_build"] == "ja"


def test_build_completo_sem_root(ambiente):
    job = {
        "id": "j1",
        "name": "camada-teste",
        "template": "tteste",
        "packages": ["htop", "tmux"],
        "requested_by": "pytest",
        "created_at": 0,
    }
    proc = rodar_worker(ambiente, job)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    feito = ambiente["data"] / "layerbuilds" / "done" / "j1.json"
    assert feito.is_file(), f"job não concluiu: {proc.stdout}\n{proc.stderr}"
    resultado = json.loads(feito.read_text())["output"]

    squash = ambiente["data"] / "blobs" / resultado["file"]
    assert squash.is_file()
    assert hashlib.md5(squash.read_bytes()).hexdigest() == resultado["md5"]

    arquivos = conteudo_da_camada(squash)

    # 1) o que o "pacote" instalou está na camada
    assert any(a.startswith("usr/share/pacote-teste") for a in arquivos), arquivos

    # 2) o lixo foi podado automaticamente (no nb2 isso era manual e falhava)
    for lixo in ("var/cache/apt/pkgcache.bin", "var/log/apt-teste.log",
                 "etc/resolv.conf", "usr/sbin/policy-rc.d"):
        assert lixo not in arquivos, f"{lixo} vazou para a camada"

    # 3) nenhum hash de senha sai daqui
    shadow = subprocess.run(
        ["unsquashfs", "-cat", str(squash), "etc/shadow"], capture_output=True, text=True
    ).stdout
    assert "SEGREDO" not in shadow and "OUTRO" not in shadow, shadow
    if shadow.strip():
        for linha in shadow.strip().splitlines():
            assert linha.split(":")[1] in ("*", "!", "!*", ""), linha


def test_pacote_invalido_e_recusado_pela_api(client, admin_key, data_root):
    """Nome de pacote não pode virar linha de comando: a API valida antes."""
    from server.app import fsdb

    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    h = {"Authorization": f"Bearer {admin_key}"}
    for ruim in ["htop; rm -rf /", "--option", "pacote com espaço", "$(whoami)"]:
        r = client.post(
            "/api/v1/layerbuilds",
            json={"name": "x", "template": "t", "packages": [ruim]},
            headers=h,
        )
        assert r.status_code == 400, ruim


def test_attach_coloca_camada_na_frente(client, admin_key, data_root):
    """Camada extra precisa ter prioridade sobre a imagem base — é ela que
    sobrepõe arquivos (mesma semântica do template.extra do nb2)."""
    from server.app import fsdb

    fsdb.write_json(
        data_root / "templates" / "t" / "template.json",
        {"layers": [{"md5": "a" * 32, "file": "base.squash", "cdn_url": "https://cdn/base.squash"}]},
    )
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    h = {"Authorization": f"Bearer {admin_key}"}
    criada = client.post(
        "/api/v1/images", json={"id": "alvo", "fullname": "Alvo", "template": "t"}, headers=h
    ).json()
    bk = {"X-NB-Boot-Key": criada["boot_key"]}

    job = {
        "id": "j2",
        "name": "extra",
        "template": "t",
        "packages": ["htop"],
        "created_at": 0,
        "output": {"file": "extra.squash", "md5": "b" * 32, "size": 123},
    }
    fsdb.write_json(data_root / "layerbuilds" / "done" / "j2.json", job)

    r = client.post("/api/v1/layerbuilds/j2/attach", json={"image_ids": ["alvo"]}, headers=h)
    assert r.status_code == 200, r.text

    manifest = client.get("/boot/v3/alvo/manifest", headers=bk).text.strip().splitlines()
    assert manifest[0].split()[1] == "extra.squash"
    assert manifest[1].split()[1] == "base.squash"

    # anexar de novo não duplica
    client.post("/api/v1/layerbuilds/j2/attach", json={"image_ids": ["alvo"]}, headers=h)
    assert len(client.get("/boot/v3/alvo/manifest", headers=bk).text.strip().splitlines()) == 2

    r = client.delete("/api/v1/images/alvo/layers/extra.squash", headers=h)
    assert r.status_code == 204
    assert len(client.get("/boot/v3/alvo/manifest", headers=bk).text.strip().splitlines()) == 1
