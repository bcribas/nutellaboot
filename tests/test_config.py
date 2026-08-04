import json

import pytest

from server.app import fsdb
from server.app.services import config as cfg
from server.app.services.default_schema import build_default_schema


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    return image_testes3


@pytest.fixture
def h_img(img):
    return {"Authorization": f"Bearer {img['token']}"}


def test_get_config_returns_schema_and_defaults(client, img, h_img):
    r = client.get("/api/v1/site-images/testes3/config", headers=h_img)
    assert r.status_code == 200
    body = r.json()
    assert body["values"]["TIMEZONE"] == "America/Sao_Paulo"
    assert body["values"]["ICPC_AUTOLOGIN"] is True
    assert any(f["key"] == "LOCK_THEME" for f in body["schema"]["fields"])
    # senha nunca volta pela API
    assert "LOCK_FALLBACK_PASSWORD" not in body["values"]


def test_put_config_saves_and_validates(client, img, h_img):
    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"TIMEZONE": "America/Santiago", "SEEDIMAGE": True}},
        headers=h_img,
    )
    assert r.status_code == 200, r.text
    assert r.json()["values"]["TIMEZONE"] == "America/Santiago"

    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"TIMEZONE": "Marte/Olympus"}},
        headers=h_img,
    )
    assert r.status_code == 400
    assert "TIMEZONE" in r.json()["detail"]


def test_unknown_field_is_rejected(client, img, h_img):
    r = client.put(
        "/api/v1/site-images/testes3/config", json={"values": {"RM_RF": "/"}}, headers=h_img
    )
    assert r.status_code == 400


def test_locked_field_blocked_for_image_token(client, data_root, img, h_img):
    """O 'perfil bloqueado' da maratona: o dono da imagem não muda o firewall."""
    info = fsdb.read_json(data_root / "site-images" / "testes3" / "image.json")
    info["unlocked"] = False
    fsdb.write_json(data_root / "site-images" / "testes3" / "image.json", info)

    r = client.put(
        "/api/v1/site-images/testes3/config", json={"values": {"DISABLE_FIREWALL": True}}, headers=h_img
    )
    assert r.status_code == 400
    assert "bloqueado" in r.json()["detail"]


def test_locked_field_allowed_for_admin(client, data_root, img, admin_key):
    info = fsdb.read_json(data_root / "site-images" / "testes3" / "image.json")
    info["unlocked"] = False
    fsdb.write_json(data_root / "site-images" / "testes3" / "image.json", info)

    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"DISABLE_FIREWALL": True}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 200


def test_locked_field_value_ignored_when_relocked(data_root, img):
    """Valor salvo enquanto a imagem estava desbloqueada não pode vazar para a
    máquina depois que o campo volta a ser bloqueado."""
    cfg.write_values("testes3", {"DISABLE_FIREWALL": True}, is_admin=True)
    info = fsdb.read_json(data_root / "site-images" / "testes3" / "image.json")
    info["unlocked"] = False
    fsdb.write_json(data_root / "site-images" / "testes3" / "image.json", info)
    assert cfg.effective_values("testes3")["DISABLE_FIREWALL"] is False


def test_password_is_hashed_never_stored_plain(data_root, img, client, h_img):
    r = client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"LOCK_FALLBACK_PASSWORD": "abrete-sesamo"}},
        headers=h_img,
    )
    assert r.status_code == 200
    raw = (data_root / "site-images" / "testes3" / "config.json").read_text()
    assert "abrete-sesamo" not in raw
    stored = fsdb.read_json(data_root / "site-images" / "testes3" / "config.json")["values"][
        "LOCK_FALLBACK_PASSWORD_HASH"
    ]
    assert cfg.check_password(stored, "abrete-sesamo")
    assert not cfg.check_password(stored, "outra")


def test_empty_password_keeps_current(data_root, img):
    cfg.write_values("testes3", {"LOCK_FALLBACK_PASSWORD": "senha1"}, is_admin=False)
    antes = fsdb.read_json(data_root / "site-images" / "testes3" / "config.json")["values"]
    cfg.write_values("testes3", {"LOCK_FALLBACK_PASSWORD": ""}, is_admin=False)
    depois = fsdb.read_json(data_root / "site-images" / "testes3" / "config.json")["values"]
    assert antes["LOCK_FALLBACK_PASSWORD_HASH"] == depois["LOCK_FALLBACK_PASSWORD_HASH"]


def test_text_field_rejects_newline(img):
    with pytest.raises(cfg.ConfigError):
        cfg.write_values("testes3", {"DEFAULTBROWSERURL": "http://x\nrm -rf /"}, is_admin=True)


def test_wallpaper_upload_and_serve(client, img, h_img):
    png = b"\x89PNG\r\n\x1a\n" + b"conteudo-de-teste"
    r = client.put(
        "/api/v1/site-images/testes3/wallpaper",
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

    assert client.delete("/api/v1/site-images/testes3/wallpaper", headers=h_img).status_code == 204
    assert client.get("/boot/v3/testes3/wallpaper").status_code == 404


def test_wallpaper_rejects_non_image(client, img, h_img):
    r = client.put(
        "/api/v1/site-images/testes3/wallpaper",
        files={"file": ("x.png", b"#!/bin/sh\nrm -rf /", "image/png")},
        headers=h_img,
    )
    assert r.status_code == 400


def test_stuff_uses_effective_values(client, img, h_img):
    client.put(
        "/api/v1/site-images/testes3/config",
        json={"values": {"TIMEZONE": "America/Santiago", "SEEDIMAGE": True}},
        headers=h_img,
    )
    text = client.get("/boot/v3/testes3/stuff").text
    assert "TIMEZONE='America/Santiago'" in text
    assert "SEEDIMAGE='t'" in text  # booleano vira t/f para o shell
    assert "ALLOWVM='f'" in text


# --- senha de root: dois hashes com destinos diferentes ----------------------
#
# O cliente aplica `NB_ROOT_PW_HASH` no /etc/shadow desde sempre
# (`60-polkit.sh`), e o servidor nunca produziu essa variável. Ao produzi-la, o
# risco é usar o hash ERRADO: o da tela de bloqueio é sha256(sal+senha), que o
# agente confere sozinho; o /etc/shadow só entende crypt(3). Trocar um pelo
# outro dá uma conta cuja senha nunca casa — e o erro aparece na sala.


def _modelo_padrao(data_root, nome="t"):
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data_root / "models" / nome / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / nome / "schema.json", build_default_schema())


def test_o_hash_do_root_e_de_shadow_e_o_da_tela_nao(data_root):
    from server.app.services import config as cfg

    campo_root = {"type": "password", "hash": "crypt"}
    campo_tela = {"type": "password"}
    h_root = cfg.hash_do_campo(campo_root, "senha-boa")
    h_tela = cfg.hash_do_campo(campo_tela, "senha-boa")

    assert h_root.startswith("$6$"), h_root
    assert not h_tela.startswith("$"), h_tela
    # e o da tela continua conferindo pelo caminho dele
    assert cfg.check_password(h_tela, "senha-boa")
    assert not cfg.check_password(h_tela, "outra")


def test_a_senha_de_root_da_sede_vira_hash_de_shadow(data_root):
    from server.app.services import config as cfg, store

    _modelo_padrao(data_root)
    store.create_site_image("sala1", "S", "t", unlocked=True)
    cfg.write_values("sala1", {"ROOT_PASSWORD": "abc123"}, is_admin=True)

    guardado = store.config_values("sala1")["ROOT_PASSWORD_HASH"]
    assert guardado.startswith("$6$")
    # a senha em claro não fica em lugar nenhum
    assert "abc123" not in json.dumps(store.config_values("sala1"))


def test_o_padrao_do_modelo_nao_guarda_senha_em_claro(data_root):
    from server.app.services import store

    _modelo_padrao(data_root)
    store.set_schema_field("t", "ROOT_PASSWORD", {"default": "senha-da-organizacao"})
    bruto = (data_root / "models" / "t" / "schema.json").read_text(encoding="utf-8")
    assert "senha-da-organizacao" not in bruto, "senha em claro no schema.json"
    assert "$6$" in bruto


def test_o_stuff_leva_o_padrao_do_modelo_quando_trancado(data_root):
    from server.app.services import store, stuffgen

    _modelo_padrao(data_root)
    store.set_schema_field("t", "ROOT_PASSWORD", {"default": "da-organizacao", "locked": True})
    store.create_site_image("sala2", "S", "t")

    linhas = [l for l in stuffgen.render("sala2").splitlines() if l.startswith("NB_ROOT_PW_HASH=")]
    assert linhas, "o stuff não leva a senha de root"
    assert "$6$" in linhas[0]


def test_sem_senha_configurada_o_shadow_nao_e_tocado(data_root):
    from server.app.services import store, stuffgen

    _modelo_padrao(data_root)
    store.create_site_image("sala3", "S", "t")
    # a ATRIBUIÇÃO, não a menção: o stuff carrega o 60-polkit.sh, que cita
    # `$NB_ROOT_PW_HASH` no próprio código
    linhas = [l for l in stuffgen.render("sala3").splitlines() if l.startswith("NB_ROOT_PW_HASH=")]
    assert not linhas, linhas


def test_a_sede_so_troca_a_senha_de_root_quando_destrancada(data_root):
    from server.app.services import config as cfg, store

    _modelo_padrao(data_root)
    store.create_site_image("sala4", "S", "t")  # trancada (o campo nasce locked)
    with pytest.raises(cfg.ConfigError):
        cfg.write_values("sala4", {"ROOT_PASSWORD": "da-sede"}, is_admin=False)

    store.set_schema_field("t", "ROOT_PASSWORD", {"locked": False})
    cfg.write_values("sala4", {"ROOT_PASSWORD": "da-sede"}, is_admin=False)
    assert store.config_values("sala4")["ROOT_PASSWORD_HASH"].startswith("$6$")


def test_campo_novo_do_esquema_padrao_chega_a_modelo_antigo(data_root):
    """O `schema.json` é gravado na criação e nunca mais revisto. Sem isto,
    acrescentar um campo só valeria para modelo criado depois dele — e o modelo
    da temporada, que está em produção, ficaria sem ele para sempre.

    Foi exatamente o que aconteceu com a senha de root: o campo existia no
    esquema padrão e não aparecia no modelo real."""
    from server.app.services import config as cfg, store

    # um modelo "antigo": esquema com um campo só, como se tivesse sido gravado
    # antes de metade dos campos existirem
    fsdb.write_json(data_root / "models" / "velho" / "model.json", {"layers": []})
    fsdb.write_json(
        data_root / "models" / "velho" / "schema.json",
        {"fields": [{"key": "TIMEZONE", "type": "select", "default": "America/Bahia"}]},
    )
    store.create_site_image("sala9", "S", "velho")

    campos = {f["key"]: f for f in cfg.schema_for("sala9").get("fields", [])}
    assert "ROOT_PASSWORD" in campos, "campo novo não chegou ao modelo antigo"
    assert campos["ROOT_PASSWORD"]["hash"] == "crypt"
    # e o que o modelo já tinha continua sendo dele
    assert campos["TIMEZONE"]["default"] == "America/Bahia"
    assert campos["TIMEZONE"]["options"], "os metadados do padrão também entram"
