import time

import pytest

from server.app import fsdb
from server.app.services import seeders, store

# chave de boot da imagem de teste (as imagens criadas pela API ganham a sua)
BK = {"X-NB-Boot-Key": "nb3b_chavedeteste"}


@pytest.fixture
def image_with_template(data_root, image_testes3):
    # imagem de teste com chave de boot, como as criadas pela API
    fsdb.write_text(data_root / "site-images" / "testes3" / "boot.key", "nb3b_chavedeteste\n")
    fsdb.write_json(
        data_root / "models" / "tpl" / "model.json",
        {
            "layers": [
                {"md5": "a" * 32, "file": "base.squash", "cdn_url": "https://cdn/base.squash"}
            ]
        },
    )
    img = data_root / "site-images" / "testes3"
    info = fsdb.read_json(img / "image.json")
    info["model"] = "tpl"
    fsdb.write_json(img / "image.json", info)
    fsdb.write_json(
        img / "layers-extra.json",
        [{"md5": "b" * 32, "file": "extra.squash", "cdn_url": "https://cdn/extra.squash"}],
    )
    fsdb.write_json(img / "config.json", {"values": {"TIMEZONE": "America/Sao_Paulo"}})
    return image_testes3


def test_sanity_and_time(client):
    assert client.get("/boot/v3/sanity").text == "penguin\n"
    t = int(client.get("/boot/v3/time").text)
    assert abs(t - time.time()) < 5


def test_manifest_extra_first_cdn_last(client, image_with_template):
    lines = client.get("/boot/v3/testes3/manifest", headers=BK).text.strip().splitlines()
    assert lines[0].startswith("b" * 32 + " extra.squash ")
    assert lines[1].startswith("a" * 32 + " base.squash ")
    assert lines[0].endswith("https://cdn/extra.squash")


def test_manifest_includes_all_live_seeders(client, image_with_template):
    key = "nb3b_chavedeteste"
    for ip in ("10.0.0.5", "10.0.0.6"):
        r = client.post(f"/boot/v3/testes3/seeders/join?ip={ip}&key={key}")
        assert r.status_code == 200
    line = client.get("/boot/v3/testes3/manifest", headers=BK).text.splitlines()[0]
    urls = line.split()[2:]
    assert "http://10.0.0.5/extra.squash" in urls
    assert "http://10.0.0.6/extra.squash" in urls
    assert urls[-1] == "https://cdn/extra.squash"  # CDN sempre por último


def test_seeder_join_requires_boot_key(client, image_with_template):
    r = client.post("/boot/v3/testes3/seeders/join?ip=10.0.0.9&key=nb3b_errada")
    assert r.status_code == 401
    r = client.post("/boot/v3/testes3/seeders/join?ip=lixo&key=nb3b_chavedeteste")
    assert r.status_code == 400


def test_seeder_ttl_expires(client, image_with_template, data_root):
    key = "nb3b_chavedeteste"
    client.post(f"/boot/v3/testes3/seeders/join?ip=10.0.0.5&key={key}")
    assert seeders.live("testes3") == ["10.0.0.5"]
    # envelhece o heartbeat além do TTL
    pool_path = data_root / "site-images" / "testes3" / "seeders.json"
    pool = fsdb.read_json(pool_path)
    pool["10.0.0.5"]["last_seen"] = time.time() - 9999
    fsdb.write_json(pool_path, pool)
    assert seeders.live("testes3") == []
    line = client.get("/boot/v3/testes3/manifest", headers=BK).text.splitlines()[0]
    assert line.split()[2:] == ["https://cdn/extra.squash"]


def test_seeder_leave_unauth_ok(client, image_with_template):
    key = "nb3b_chavedeteste"
    client.post(f"/boot/v3/testes3/seeders/join?ip=10.0.0.5&key={key}")
    client.post("/boot/v3/testes3/seeders/leave?ip=10.0.0.5")
    assert seeders.live("testes3") == []


def test_stuff_renders_vars_and_modules(client, image_with_template):
    text = client.get("/boot/v3/testes3/stuff", headers=BK).text
    assert "IMAGEROOT='testes3'" in text
    assert "NB_MACHINE_KEY='nb3m_" in text
    assert "TIMEZONE='America/Sao_Paulo'" in text
    assert "NBUID=" in text


def test_stuff_quotes_hostile_values(client, image_with_template, data_root):
    img = data_root / "site-images" / "testes3"
    # `unlocked`: o esquema padrão marca DEFAULTBROWSERURL como travado, e
    # travado o stuff leva o padrão do modelo, não o que está salvo. Isto mudou
    # quando `_com_padroes` passou a acrescentar os campos do esquema padrão a
    # modelos que não os têm — antes, modelo sem schema.json repassava o que
    # estivesse gravado, cadeado nenhum. A tranca valer também ali é o
    # comportamento certo; o que este teste prende é o ASPEAMENTO, e para
    # exercitá-lo o valor precisa chegar ao stuff.
    info = fsdb.read_json(img / "image.json")
    fsdb.write_json(img / "image.json", {**info, "unlocked": True})
    fsdb.write_json(
        img / "config.json",
        {"values": {"DEFAULTBROWSERURL": "x'; rm -rf / #", "não-vale": "y", "lower": "z"}},
    )
    text = client.get("/boot/v3/testes3/stuff", headers=BK).text
    assert "DEFAULTBROWSERURL='x'\\''; rm -rf / #'" in text
    assert "não-vale" not in text
    assert "lower" not in text.split("# =====")[0].replace("NB_", "")


def test_manifest_404_unknown_image(client, data_root):
    assert client.get("/boot/v3/nao-existe/manifest").status_code == 404


def test_image_lifecycle_via_api(client, admin_key, data_root):
    fsdb.write_json(data_root / "models" / "tpl" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    h = {"Authorization": f"Bearer {admin_key}"}

    r = client.post("/api/v1/site-images", json={"id": "unbteste", "fullname": "UnB", "model": "tpl"}, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["namespace"] == "personal"
    assert body["token"].startswith("nb3i_")

    r = client.post("/api/v1/site-images", json={"id": "26brbr", "fullname": "Finals", "model": "tpl"}, headers=h)
    assert r.json()["namespace"] == "contest"

    r = client.post("/api/v1/site-images", json={"id": "unbteste", "fullname": "dup", "model": "tpl"}, headers=h)
    assert r.status_code == 400

    r = client.get("/api/v1/site-images?prefix=26", headers=h)
    assert [i["id"] for i in r.json()["images"]] == ["26brbr"]

    r = client.post("/api/v1/site-images/unbteste/token/rotate", headers=h)
    assert r.json()["token"].startswith("nb3i_")

    assert client.delete("/api/v1/site-images/unbteste", headers=h).status_code == 204
    assert not store.site_image_exists("unbteste")


def test_bulk_tsv_csv(client, admin_key, data_root):
    fsdb.write_json(data_root / "models" / "tpl" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    tsv = "26spsp\tSede São Paulo\ttpl\n26mgbh\tSede BH\ttpl\nruim id\tX\ttpl\n"
    r = client.post(
        "/api/v1/site-images/bulk?format=csv",
        content=tsv,
        headers={"Authorization": f"Bearer {admin_key}", "Content-Type": "text/tab-separated-values"},
    )
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,ok,token")
    assert len(lines) == 4
    assert "26spsp,True,nb3i_" in lines[1]
    assert lines[3].startswith("ruim id,False")
