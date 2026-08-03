"""Integração com o MOJ: chaves de serviço com escopo e webhooks assinados."""

import hashlib
import hmac
import json

import pytest

from server.app import fsdb
from server.app.services import webhook_push

MAC = "52-54-00-12-34-56"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "keys" / "services.json", {})
    return image_testes3


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def moj_key(client, ha, scopes, images=None):
    r = client.post(
        "/api/v1/service-keys",
        json={"name": "moj", "scopes": scopes, "images": images or []},
        headers=ha,
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['key']}"}


def test_service_key_scope_enforced(client, img, ha):
    hs = moj_key(client, ha, ["machines:read"])
    # leitura permitida
    assert client.get("/api/v1/site-images/testes3/machines", headers=hs).status_code == 200
    # escrever comando não está no escopo
    r = client.post(
        "/api/v1/site-images/testes3/commands", json={"command": "cantouch", "target": "all"}, headers=hs
    )
    assert r.status_code == 403


def test_service_key_image_filter(client, img, ha, data_root):
    fsdb.write_json(
        data_root / "site-images" / "26brbr" / "image.json",
        {"id": "26brbr", "model": "t", "namespace": "contest"},
    )
    hs = moj_key(client, ha, ["machines:read"], images=["26*"])
    assert client.get("/api/v1/site-images/26brbr/machines", headers=hs).status_code == 200
    assert client.get("/api/v1/site-images/testes3/machines", headers=hs).status_code == 403


def test_moj_can_lock_and_bind_with_scopes(client, img, ha):
    hm = {"X-NB-Machine-Key": img["machine_key"]}
    client.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)
    hs = moj_key(client, ha, ["commands:write", "bindings:write", "roster:write", "machines:read"])

    client.put(
        "/api/v1/site-images/testes3/roster",
        json={"roster": [{"user_id": "t1", "name": "Time 1"}]},
        headers=hs,
    )
    r = client.put(
        f"/api/v1/site-images/testes3/machines/{MAC}/binding", json={"user_id": "t1"}, headers=hs
    )
    assert r.status_code == 200

    r = client.post(f"/api/v1/site-images/testes3/machines/{MAC}/lock", headers=hs)
    assert r.status_code == 200
    assert client.get(f"/boot/v3/testes3/machines/{MAC}/lockstate").text.strip() == "locked"


def test_service_key_lifecycle(client, img, ha):
    hs = moj_key(client, ha, ["machines:read"])
    nomes = [k["name"] for k in client.get("/api/v1/service-keys", headers=ha).json()["service_keys"]]
    assert nomes == ["moj"]
    assert client.delete("/api/v1/service-keys/moj", headers=ha).status_code == 204
    assert client.get("/api/v1/site-images/testes3/machines", headers=hs).status_code == 401


def test_webhook_config_hides_secret(client, img, ha):
    r = client.put(
        "/api/v1/site-images/testes3/webhooks",
        json={
            "webhooks": [
                {
                    "url": "https://moj.example/hooks/nb3",
                    "secret": "segredo-do-moj",
                    "events": ["machine.locked"],
                }
            ]
        },
        headers=ha,
    )
    assert r.status_code == 200
    got = client.get("/api/v1/site-images/testes3/webhooks", headers=ha).json()["webhooks"][0]
    assert got["secret"] == "***"
    assert got["url"] == "https://moj.example/hooks/nb3"


def test_webhook_rejects_bad_url_and_event(client, img, ha):
    r = client.put(
        "/api/v1/site-images/testes3/webhooks",
        json={"webhooks": [{"url": "ftp://x/y"}]},
        headers=ha,
    )
    assert r.status_code == 400
    r = client.put(
        "/api/v1/site-images/testes3/webhooks",
        json={"webhooks": [{"url": "https://x/y", "events": ["nao.existe"]}]},
        headers=ha,
    )
    assert r.status_code == 400


def test_webhook_filter_by_event(client, img, ha):
    client.put(
        "/api/v1/site-images/testes3/webhooks",
        json={
            "webhooks": [
                {"url": "https://a/", "events": ["machine.locked"]},
                {"url": "https://b/", "events": []},  # vazio = todos
            ]
        },
        headers=ha,
    )
    urls = lambda ev: [w["url"] for w in webhook_push.webhooks_for("testes3", ev)]  # noqa: E731
    assert urls("machine.locked") == ["https://a/", "https://b/"]
    assert urls("command.acked") == ["https://b/"]


def test_signature_matches_hmac():
    """Contrato com o MOJ: assinatura é HMAC-SHA256 do corpo, com o segredo."""
    corpo = json.dumps({"event": "machine.locked"}).encode()
    assinatura = webhook_push.sign("segredo", corpo)
    esperado = "sha256=" + hmac.new(b"segredo", corpo, hashlib.sha256).hexdigest()
    assert assinatura == esperado


@pytest.mark.anyio
async def test_webhook_is_delivered_and_signed(data_root, image_testes3):
    """Sobe um receptor local e confirma entrega + assinatura verificável."""
    import asyncio

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    recebidos = []
    receptor = FastAPI()

    @receptor.post("/hook")
    async def hook(request: Request):
        recebidos.append(
            {"body": await request.body(), "sig": request.headers.get("X-NB-Signature", "")}
        )
        return JSONResponse({"ok": True})

    import uvicorn

    config = uvicorn.Config(receptor, host="127.0.0.1", port=8899, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)

    fsdb.write_json(
        data_root / "site-images" / "testes3" / "webhooks.json",
        [{"url": "http://127.0.0.1:8899/hook", "secret": "s3gr3d0", "events": ["machine.locked"]}],
    )
    webhook_push.emit("testes3", "machine.locked", {"machines": [MAC]})
    for _ in range(60):
        if recebidos:
            break
        await asyncio.sleep(0.1)

    server.should_exit = True
    await task

    assert recebidos, "webhook não chegou"
    corpo, sig = recebidos[0]["body"], recebidos[0]["sig"]
    assert sig == webhook_push.sign("s3gr3d0", corpo)
    payload = json.loads(corpo)
    assert payload["event"] == "machine.locked"
    assert payload["image"] == "testes3"
    assert payload["data"]["machines"] == [MAC]


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- eventos que estavam no catálogo mas nunca eram emitidos ---


def _emitidos(monkeypatch, acao):
    """Roda `acao` capturando o que foi para o canal de webhook."""
    from server.app.services import webhook_push

    vistos = []
    monkeypatch.setattr(webhook_push, "emit", lambda img, ev, data: vistos.append(ev))
    acao()
    return vistos


@pytest.fixture
def sede(client, data_root, image_testes3):
    """Uma imagem com roster, para exercitar vínculo e configuração."""
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    h = {"Authorization": f"Bearer {image_testes3['token']}"}
    client.put(
        "/api/v1/site-images/testes3/roster",
        json={"roster": [{"user_id": "team-001", "name": "Time 1"}]},
        headers=h,
    )
    return h


def test_vinculo_de_time_chega_ao_webhook(client, sede, monkeypatch):
    """machine.bound e machine.unbound publicavam só no SSE: o painel via em
    tempo real, mas um webhook do MOJ inscrito nesses eventos nunca disparava,
    apesar de a documentação prometer."""
    mac = "52-54-00-01-02-03"
    rota = f"/api/v1/site-images/testes3/machines/{mac}/binding"

    vistos = _emitidos(
        monkeypatch,
        lambda: client.put(rota, json={"user_id": "team-001", "seat": "1"}, headers=sede),
    )
    assert "machine.bound" in vistos, vistos

    vistos = _emitidos(monkeypatch, lambda: client.delete(rota, headers=sede))
    assert "machine.unbound" in vistos, vistos


def test_config_updated_e_emitido(client, sede, monkeypatch):
    """Estava no catálogo desde o começo e nenhum código o publicava."""
    vistos = _emitidos(
        monkeypatch,
        lambda: client.put(
            "/api/v1/site-images/testes3/config",
            json={"values": {"TIMEZONE": "UTC"}},
            headers=sede,
        ),
    )
    assert "config.updated" in vistos, vistos


def test_seeder_joined_e_emitido(client, sede, image_testes3, monkeypatch, data_root):
    """Idem. E só no join, não a cada heartbeat: senão viraria um evento por
    máquina a cada poucos minutos."""
    from server.app import fsdb as _fsdb

    chave = "nb3b_teste"
    _fsdb.write_text(data_root / "site-images" / "testes3" / "boot.key", chave + "\n")

    def entra():
        client.post(f"/boot/v3/testes3/seeders/join?ip=10.0.0.5&key={chave}")

    assert "seeder.joined" in _emitidos(monkeypatch, entra)
    # segundo contato do mesmo IP é heartbeat, não entrada
    assert "seeder.joined" not in _emitidos(monkeypatch, entra)


def test_todo_evento_do_catalogo_tem_quem_o_emita():
    """O catálogo é o que o MOJ lê para saber em que se inscrever. Evento
    listado e nunca emitido é promessa que não se cumpre — aconteceu com
    config.updated e seeder.joined, que ficaram anos na lista sem emissor."""
    from pathlib import Path

    from server.app.routers.webhooks import EVENTOS

    app_dir = Path(__file__).resolve().parents[1] / "server" / "app"
    fonte = "\n".join(
        p.read_text(encoding="utf-8")
        for p in app_dir.rglob("*.py")
        if p.name != "webhooks.py"  # o catálogo cita todos por definição
    )
    faltando = [e for e in EVENTOS if f'"{e}"' not in fonte]
    assert faltando == [], f"eventos no catalogo que ninguem emite: {faltando}"
