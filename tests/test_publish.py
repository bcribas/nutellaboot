"""Publicação de arquivos grandes no servidor de arquivos.

Usa um transporte falso (NB3_PUBLISH_CMD) para não depender de rede nem de
SSH: o que importa aqui é o estado, a URL pública e o comportamento quando o
envio falha (o boot não pode ficar sem fonte).
"""

import stat

import pytest

from server.app import fsdb
from server.app.services import publish


@pytest.fixture
def fake_rsync(tmp_path, monkeypatch):
    """Transporte falso: copia para um diretório local em vez de enviar."""
    destino = tmp_path / "remoto"
    destino.mkdir()
    script = tmp_path / "fake-rsync"
    script.write_text(
        "#!/bin/sh\n"
        "# $1 = origem, $2 = user@host:/caminho/ (ignoramos o host)\n"
        f'cp "$1" "{destino}/" && exit 0\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("NB3_PUBLISH_CMD", str(script))
    return destino


@pytest.fixture
def conf_publish(data_root):
    fsdb.write_json(
        data_root / "server.json",
        {
            "base_url": "https://gestao.exemplo",
            "publish": {
                "enabled": True,
                "host": "files.exemplo",
                "user": "root",
                "paths": {"layers": "/var/www/html/maratonalinux", "usb": "/var/www/html/mlbootimages"},
                "base_urls": {
                    "layers": "https://files.exemplo/maratonalinux",
                    "usb": "https://files.exemplo/mlbootimages",
                },
            },
        },
    )


def _blob(data_root, nome="camada.squash", conteudo=b"squashfs"):
    p = data_root / "blobs" / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(conteudo)
    return p


def test_publica_e_devolve_url_publica(data_root, conf_publish, fake_rsync):
    local = _blob(data_root)
    estado = publish.publish_file(local, "layers")
    assert estado["status"] == "done"
    assert estado["url"] == "https://files.exemplo/maratonalinux/camada.squash"
    # chegou "do outro lado"
    assert (fake_rsync / "camada.squash").read_bytes() == b"squashfs"
    # e o estado ficou registrado para a tela
    assert publish.state("camada.squash")["status"] == "done"


def test_usb_vai_para_o_outro_diretorio(data_root, conf_publish, fake_rsync):
    p = data_root / "usb" / "pendrive.img"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"img")
    estado = publish.publish_file(p, "usb")
    assert estado["url"] == "https://files.exemplo/mlbootimages/pendrive.img"


def test_falha_fica_pendente_com_motivo(data_root, conf_publish, tmp_path, monkeypatch):
    falho = tmp_path / "falha"
    falho.write_text("#!/bin/sh\necho 'sem rota para o host' >&2\nexit 12\n")
    falho.chmod(0o755)
    monkeypatch.setenv("NB3_PUBLISH_CMD", str(falho))

    estado = publish.publish_file(_blob(data_root), "layers")
    assert estado["status"] == "failed"
    assert "rota" in estado["error"]
    assert "url" not in estado


def test_retry_reenvia_o_que_falhou(data_root, conf_publish, tmp_path, monkeypatch, fake_rsync):
    # primeiro falha...
    falho = tmp_path / "falha"
    falho.write_text("#!/bin/sh\nexit 1\n")
    falho.chmod(0o755)
    monkeypatch.setenv("NB3_PUBLISH_CMD", str(falho))
    _blob(data_root)
    publish.publish_file(data_root / "blobs" / "camada.squash", "layers")
    assert publish.state("camada.squash")["status"] == "failed"

    # ...depois o transporte volta e o retry resolve
    monkeypatch.setenv("NB3_PUBLISH_CMD", str(fake_rsync.parent / "fake-rsync"))
    resultados = publish.retry_failed()
    assert [r["status"] for r in resultados] == ["done"]
    assert publish.state("camada.squash")["status"] == "done"


def test_desligado_nao_envia(data_root, fake_rsync):
    fsdb.write_json(data_root / "server.json", {"publish": {"enabled": False}})
    estado = publish.publish_file(_blob(data_root), "layers")
    assert estado["status"] == "disabled"
    assert not (fake_rsync / "camada.squash").exists()


def test_arquivo_inexistente(data_root, conf_publish, fake_rsync):
    estado = publish.publish_file(data_root / "blobs" / "nao-existe.squash", "layers")
    assert estado["status"] == "failed"


# --- rotas ---


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def test_rota_lista_estado(client, data_root, conf_publish, fake_rsync, ha):
    publish.publish_file(_blob(data_root), "layers")
    r = client.get("/api/v1/publish", headers=ha)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["paths"]["layers"] == "/var/www/html/maratonalinux"
    assert body["files"][0]["file"] == "camada.squash"


def test_rota_publica_arquivo_por_nome(client, data_root, conf_publish, fake_rsync, ha):
    _blob(data_root, "outra.squash", b"x")
    r = client.post("/api/v1/publish/file", json={"file": "outra.squash"}, headers=ha)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert (fake_rsync / "outra.squash").exists()


def test_rota_recusa_caminho_arbitrario(client, data_root, conf_publish, fake_rsync, ha):
    """Só nome de arquivo: nada de publicar /etc/passwd."""
    r = client.post("/api/v1/publish/file", json={"file": "/etc/passwd"}, headers=ha)
    assert r.status_code == 404  # vira "passwd" e não existe em data/blobs
    assert not (fake_rsync / "passwd").exists()


def test_rotas_exigem_admin(client, conf_publish):
    assert client.get("/api/v1/publish").status_code == 401
    assert client.post("/api/v1/publish/retry").status_code == 401


def test_manifest_usa_a_url_publicada(client, data_root, conf_publish, fake_rsync, admin_key, ha):
    """Depois de publicada, a camada é baixada do servidor de arquivos — não
    da máquina de gestão."""
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    criada = client.post(
        "/api/v1/images", json={"id": "img1", "fullname": "I", "template": "t"}, headers=ha
    ).json()
    _blob(data_root, "extra.squash", b"conteudo")
    publish.publish_file(data_root / "blobs" / "extra.squash", "layers")

    job = {
        "id": "j1",
        "name": "extra",
        "template": "t",
        "packages": ["htop"],
        "created_at": 0,
        "output": {"file": "extra.squash", "md5": "a" * 32, "size": 8},
    }
    fsdb.write_json(data_root / "layerbuilds" / "done" / "j1.json", job)
    client.post("/api/v1/layerbuilds/j1/attach", json={"image_ids": ["img1"]}, headers=ha)

    linha = client.get(
        "/boot/v3/img1/manifest", headers={"X-NB-Boot-Key": criada["boot_key"]}
    ).text.splitlines()[0]
    assert "https://files.exemplo/maratonalinux/extra.squash" in linha
