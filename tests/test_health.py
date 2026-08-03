def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body and "disk_free_gb" in body


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_health_conta_as_site_images_de_verdade(client, data_root, admin_key):
    """A contagem lia `data/images/`, que deixou de existir na renomeação, e
    respondia 0 com o servidor cheio — a métrica que se usa para saber se o
    serviço está vivo mentia em silêncio."""
    from server.app import fsdb

    fsdb.write_json(data_root / "models" / "m1" / "model.json", {"layers": []})
    for i in ("a", "b"):
        fsdb.write_json(data_root / "site-images" / i / "image.json", {"id": i, "model": "m1"})

    corpo = client.get("/api/v1/health").json()
    assert corpo["images"] == 2
    assert corpo["models"] == 1
