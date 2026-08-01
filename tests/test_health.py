def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body and "disk_free_gb" in body


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}
