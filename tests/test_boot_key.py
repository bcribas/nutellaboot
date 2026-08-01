"""Chave de boot: os endpoints do initrd deixaram de ser abertos.

No NutellaBoot 2 bastava saber o nome da sede para baixar o script de boot
(que é executado como root na máquina) e a lista de camadas. Agora o pendrive
carrega uma chave no nutellaboot.conf e a envia por POST.
"""

import pytest

from server.app import auth, fsdb
from server.app.services import store

MAC = "52-54-00-12-34-56"


@pytest.fixture
def img(data_root, admin_key):
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    return store.create_image("comchave", "Com chave", "t")


def test_nova_imagem_ja_nasce_com_chave_de_boot(img, data_root):
    assert img["boot_key"].startswith("nb3b_")
    arquivo = data_root / "images" / "comchave" / "boot.key"
    assert arquivo.is_file()
    assert (arquivo.stat().st_mode & 0o777) == 0o600
    assert auth.boot_key_required("comchave")


def test_sem_chave_o_servidor_recusa(client, img):
    for rota in ("manifest", "stuff"):
        r = client.get(f"/boot/v3/comchave/{rota}")
        assert r.status_code == 401, rota


def test_chave_errada_recusada(client, img):
    r = client.post("/boot/v3/comchave/stuff", data={"key": "nb3b_errada"})
    assert r.status_code == 401


def test_chave_por_post_funciona(client, img):
    """É assim que o initrd busca: POST com key no corpo."""
    r = client.post("/boot/v3/comchave/stuff", data={"key": img["boot_key"]})
    assert r.status_code == 200
    assert "IMAGEROOT='comchave'" in r.text

    r = client.post("/boot/v3/comchave/manifest", data={"key": img["boot_key"]})
    assert r.status_code == 200


def test_chave_por_cabecalho_funciona(client, img):
    """É assim que o aria2c e o curl da tela de bloqueio buscam."""
    h = {"X-NB-Boot-Key": img["boot_key"]}
    assert client.get("/boot/v3/comchave/manifest", headers=h).status_code == 200
    assert client.get("/boot/v3/comchave/stuff", headers=h).status_code == 200


def test_stuff_entrega_a_chave_para_o_sistema(client, img):
    """A chave precisa chegar ao sistema montado: o agente e a tela de
    bloqueio também falam com endpoints autenticados."""
    texto = client.post("/boot/v3/comchave/stuff", data={"key": img["boot_key"]}).text
    assert f"NB_BOOT_KEY='{img['boot_key']}'" in texto


def test_wallpaper_e_lockinfo_tambem_exigem_chave(client, img, admin_key):
    ha = {"Authorization": f"Bearer {admin_key}"}
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 20
    client.put(
        "/api/v1/images/comchave/wallpaper",
        files={"file": ("f.png", png, "image/png")},
        headers=ha,
    )
    assert client.get("/boot/v3/comchave/wallpaper").status_code == 401
    assert client.get(f"/boot/v3/comchave/lockinfo/{MAC}").status_code == 401
    assert client.get(f"/boot/v3/comchave/machines/{MAC}/lockstate").status_code == 401

    h = {"X-NB-Boot-Key": img["boot_key"]}
    assert client.get("/boot/v3/comchave/wallpaper", headers=h).content == png
    assert client.get(f"/boot/v3/comchave/lockinfo/{MAC}", headers=h).status_code == 200
    assert client.get(f"/boot/v3/comchave/machines/{MAC}/lockstate", headers=h).text.strip() == "unlocked"


def test_seeder_usa_chave_de_boot(client, img):
    r = client.post(f"/boot/v3/comchave/seeders/join?ip=10.0.0.5&key={img['boot_key']}")
    assert r.status_code == 200
    r = client.post("/boot/v3/comchave/seeders/join?ip=10.0.0.6&key=nb3b_errada")
    assert r.status_code == 401


def test_imagem_sem_boot_key_continua_aberta(client, data_root):
    """Modo de depuração: apagar boot.key reabre a imagem. Documentado."""
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    d = data_root / "images" / "aberta"
    fsdb.write_json(d / "image.json", {"id": "aberta", "template": "t", "namespace": "personal"})
    fsdb.write_text(d / "machine.key", "nb3m_x\n")
    assert not auth.boot_key_required("aberta")
    assert client.get("/boot/v3/aberta/manifest").status_code == 200


def test_rotacao_invalida_a_chave_antiga(client, img, admin_key):
    ha = {"Authorization": f"Bearer {admin_key}"}
    r = client.post("/api/v1/images/comchave/boot-key/rotate", headers=ha)
    nova = r.json()["boot_key"]
    assert nova != img["boot_key"]
    assert client.post("/boot/v3/comchave/stuff", data={"key": img["boot_key"]}).status_code == 401
    assert client.post("/boot/v3/comchave/stuff", data={"key": nova}).status_code == 200


def test_sanity_e_time_continuam_abertos(client):
    """São os dois passos que acontecem ANTES de haver TLS confiável e
    contexto de imagem: teste de conectividade e acerto de relógio."""
    assert client.get("/boot/v3/sanity").status_code == 200
    assert client.get("/boot/v3/time").status_code == 200


def test_bulk_exporta_a_chave_de_boot(client, admin_key, data_root):
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    r = client.post(
        "/api/v1/images/bulk?format=csv",
        content="26spsp\tSede SP\tt\n",
        headers={
            "Authorization": f"Bearer {admin_key}",
            "Content-Type": "text/tab-separated-values",
        },
    )
    assert "boot_key" in r.text.splitlines()[0]
    assert "nb3b_" in r.text.splitlines()[1]
