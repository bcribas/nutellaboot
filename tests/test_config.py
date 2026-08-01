import pytest

from server.app import fsdb
from server.app.services import config as cfg
from server.app.services.default_schema import build_default_schema


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "templates" / "t" / "template.json", {"layers": []})
    fsdb.write_json(data_root / "templates" / "t" / "schema.json", build_default_schema())
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    return image_testes3


@pytest.fixture
def h_img(img):
    return {"Authorization": f"Bearer {img['token']}"}


def test_get_config_returns_schema_and_defaults(client, img, h_img):
    r = client.get("/api/v1/images/testes3/config", headers=h_img)
    assert r.status_code == 200
    body = r.json()
    assert body["values"]["TIMEZONE"] == "America/Sao_Paulo"
    assert body["values"]["ICPC_AUTOLOGIN"] is True
    assert any(f["key"] == "LOCK_THEME" for f in body["schema"]["fields"])
    # senha nunca volta pela API
    assert "LOCK_FALLBACK_PASSWORD" not in body["values"]


def test_put_config_saves_and_validates(client, img, h_img):
    r = client.put(
        "/api/v1/images/testes3/config",
        json={"values": {"TIMEZONE": "America/Santiago", "SEEDIMAGE": True}},
        headers=h_img,
    )
    assert r.status_code == 200, r.text
    assert r.json()["values"]["TIMEZONE"] == "America/Santiago"

    r = client.put(
        "/api/v1/images/testes3/config",
        json={"values": {"TIMEZONE": "Marte/Olympus"}},
        headers=h_img,
    )
    assert r.status_code == 400
    assert "TIMEZONE" in r.json()["detail"]


def test_unknown_field_is_rejected(client, img, h_img):
    r = client.put(
        "/api/v1/images/testes3/config", json={"values": {"RM_RF": "/"}}, headers=h_img
    )
    assert r.status_code == 400


def test_locked_field_blocked_for_image_token(client, data_root, img, h_img):
    """O 'perfil bloqueado' da maratona: o dono da imagem não muda o firewall."""
    info = fsdb.read_json(data_root / "images" / "testes3" / "image.json")
    info["unlocked"] = False
    fsdb.write_json(data_root / "images" / "testes3" / "image.json", info)

    r = client.put(
        "/api/v1/images/testes3/config", json={"values": {"DISABLE_FIREWALL": True}}, headers=h_img
    )
    assert r.status_code == 400
    assert "bloqueado" in r.json()["detail"]


def test_locked_field_allowed_for_admin(client, data_root, img, admin_key):
    info = fsdb.read_json(data_root / "images" / "testes3" / "image.json")
    info["unlocked"] = False
    fsdb.write_json(data_root / "images" / "testes3" / "image.json", info)

    r = client.put(
        "/api/v1/images/testes3/config",
        json={"values": {"DISABLE_FIREWALL": True}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 200


def test_locked_field_value_ignored_when_relocked(data_root, img):
    """Valor salvo enquanto a imagem estava desbloqueada não pode vazar para a
    máquina depois que o campo volta a ser bloqueado."""
    cfg.write_values("testes3", {"DISABLE_FIREWALL": True}, is_admin=True)
    info = fsdb.read_json(data_root / "images" / "testes3" / "image.json")
    info["unlocked"] = False
    fsdb.write_json(data_root / "images" / "testes3" / "image.json", info)
    assert cfg.effective_values("testes3")["DISABLE_FIREWALL"] is False


def test_password_is_hashed_never_stored_plain(data_root, img, client, h_img):
    r = client.put(
        "/api/v1/images/testes3/config",
        json={"values": {"LOCK_FALLBACK_PASSWORD": "abrete-sesamo"}},
        headers=h_img,
    )
    assert r.status_code == 200
    raw = (data_root / "images" / "testes3" / "config.json").read_text()
    assert "abrete-sesamo" not in raw
    stored = fsdb.read_json(data_root / "images" / "testes3" / "config.json")["values"][
        "LOCK_FALLBACK_PASSWORD_HASH"
    ]
    assert cfg.check_password(stored, "abrete-sesamo")
    assert not cfg.check_password(stored, "outra")


def test_empty_password_keeps_current(data_root, img):
    cfg.write_values("testes3", {"LOCK_FALLBACK_PASSWORD": "senha1"}, is_admin=False)
    antes = fsdb.read_json(data_root / "images" / "testes3" / "config.json")["values"]
    cfg.write_values("testes3", {"LOCK_FALLBACK_PASSWORD": ""}, is_admin=False)
    depois = fsdb.read_json(data_root / "images" / "testes3" / "config.json")["values"]
    assert antes["LOCK_FALLBACK_PASSWORD_HASH"] == depois["LOCK_FALLBACK_PASSWORD_HASH"]


def test_text_field_rejects_newline(img):
    with pytest.raises(cfg.ConfigError):
        cfg.write_values("testes3", {"DEFAULTBROWSERURL": "http://x\nrm -rf /"}, is_admin=True)


def test_wallpaper_upload_and_serve(client, img, h_img):
    png = b"\x89PNG\r\n\x1a\n" + b"conteudo-de-teste"
    r = client.put(
        "/api/v1/images/testes3/wallpaper",
        files={"file": ("fundo.png", png, "image/png")},
        headers=h_img,
    )
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["size"] == len(png)

    r = client.get("/boot/v3/testes3/wallpaper")
    assert r.status_code == 200
    assert r.content == png
    assert r.headers["etag"] == f'"{meta["md5"]}"'

    # o md5 precisa chegar ao stuff para a máquina validar o download
    assert f"NB_WALLPAPER_MD5='{meta['md5']}'" in client.get("/boot/v3/testes3/stuff").text

    assert client.delete("/api/v1/images/testes3/wallpaper", headers=h_img).status_code == 204
    assert client.get("/boot/v3/testes3/wallpaper").status_code == 404


def test_wallpaper_rejects_non_image(client, img, h_img):
    r = client.put(
        "/api/v1/images/testes3/wallpaper",
        files={"file": ("x.png", b"#!/bin/sh\nrm -rf /", "image/png")},
        headers=h_img,
    )
    assert r.status_code == 400


def test_stuff_uses_effective_values(client, img, h_img):
    client.put(
        "/api/v1/images/testes3/config",
        json={"values": {"TIMEZONE": "America/Santiago", "SEEDIMAGE": True}},
        headers=h_img,
    )
    text = client.get("/boot/v3/testes3/stuff").text
    assert "TIMEZONE='America/Santiago'" in text
    assert "SEEDIMAGE='t'" in text  # booleano vira t/f para o shell
    assert "ALLOWVM='f'" in text
