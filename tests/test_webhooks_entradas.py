"""Webhooks entrada por entrada (achados 10 e 11 do relatório do MOJ).

Só existia o PUT da lista inteira, e o GET mascarava o segredo: dois
consumidores na mesma sede não conviviam (quem instalava o seu apagava o do
outro), e um ler-e-regravar gravava `***` como segredo de todo mundo. E tudo
era rota de admin: a chave de serviço, que é a recomendada, não instalava o
próprio webhook.
"""

import pytest

from server.app import fsdb
from server.app.services import webhook_guard, webhook_push
from server.app.services import webhooks_store as ws

BASE = "/api/v1/site-images/testes3/webhooks"
SEGREDO = "um-segredo-bem-comprido"


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


@pytest.fixture
def publico(monkeypatch):
    """Todo host resolve para um IP público: os testes não tocam a rede."""
    monkeypatch.setattr(webhook_guard, "_resolver", lambda host: ["93.184.216.34"])


def _servico(client, ha, nome, scopes=("webhooks:write",), images=()):
    r = client.post("/api/v1/service-keys", json={"name": nome, "scopes": list(scopes), "images": list(images)}, headers=ha)
    return {"Authorization": f"Bearer {r.json()['key']}"}


def test_a_chave_de_servico_instala_o_proprio_webhook(client, img, ha, publico):
    moj = _servico(client, ha, "moj")
    r = client.post(BASE, json={"url": "https://moj.example/h", "secret": SEGREDO, "events": ["alert.raised"]}, headers=moj)
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["created"] and w["id"].startswith("wh_") and w["owner"] == "service:moj"
    assert w["secret"] == "***" and isinstance(w["created_at"], int)
    assert [x["id"] for x in client.get(BASE, headers=moj).json()["webhooks"]] == [w["id"]]


def test_reinstalar_a_mesma_url_nao_duplica(client, img, ha, publico):
    moj = _servico(client, ha, "moj")
    corpo = {"url": "https://moj.example/h", "secret": SEGREDO, "events": ["alert.raised"]}
    um = client.post(BASE, json=corpo, headers=moj).json()
    dois = client.post(BASE, json={**corpo, "events": ["alert.raised", "alert.dismissed"]}, headers=moj)
    assert dois.status_code == 200 and not dois.json()["created"]
    assert dois.json()["id"] == um["id"]
    assert len(ws.carregar("testes3")) == 1
    assert ws.carregar("testes3")[0]["events"] == ["alert.raised", "alert.dismissed"]


def test_cada_chave_so_ve_e_mexe_no_que_e_seu(client, img, ha, publico):
    moj, outro = _servico(client, ha, "moj"), _servico(client, ha, "outro")
    meu = client.post(BASE, json={"url": "https://moj.example/h", "secret": SEGREDO}, headers=moj).json()
    dele = client.post(BASE, json={"url": "https://outro.example/h", "secret": SEGREDO}, headers=outro).json()
    client.post(BASE, json={"url": "http://10.0.0.5/interno"}, headers=ha)  # a administração aponta para onde quiser

    assert [w["id"] for w in client.get(BASE, headers=moj).json()["webhooks"]] == [meu["id"]]
    assert len(client.get(BASE, headers=ha).json()["webhooks"]) == 3
    for r in (
        client.put(f"{BASE}/{dele['id']}", json={"events": []}, headers=moj),
        client.delete(f"{BASE}/{dele['id']}", headers=moj),
    ):
        assert r.status_code == 404 and r.json()["code"] == "webhook_not_found"
    assert client.delete(f"{BASE}/{meu['id']}", headers=moj).status_code == 204
    assert client.delete(f"{BASE}/{dele['id']}", headers=ha).status_code == 204  # o admin apaga qualquer um
    assert len(ws.carregar("testes3")) == 1


def test_put_parcial_roda_so_o_segredo(client, img, ha, publico):
    moj = _servico(client, ha, "moj")
    w = client.post(BASE, json={"url": "https://moj.example/h", "secret": SEGREDO, "events": ["alert.raised"]}, headers=moj).json()
    r = client.put(f"{BASE}/{w['id']}", json={"secret": "outro-segredo-comprido"}, headers=moj)
    assert r.status_code == 200, r.text
    gravado = ws.carregar("testes3")[0]
    assert gravado["secret"] == "outro-segredo-comprido"
    assert gravado["url"] == "https://moj.example/h" and gravado["events"] == ["alert.raised"]


def test_escopo_glob_e_quem_nao_entra(client, img, ha, publico):
    sem = _servico(client, ha, "sem", scopes=("machines:read",))
    fora = _servico(client, ha, "fora", images=("outra*",))
    assert client.get(BASE, headers=sem).json()["code"] == "insufficient_scope"
    assert client.get(BASE, headers=fora).json()["code"] == "image_out_of_scope"
    assert client.get("/api/v1/site-images/naoexiste/webhooks", headers=ha).json()["code"] == "image_not_found"
    # token da sede e sub-admin continuam de fora: é um cliente HTTP na rede de gestão
    assert client.get(BASE, headers={"Authorization": f"Bearer {img['token']}"}).status_code == 401


def test_chave_de_servico_nao_aponta_para_dentro(client, img, ha, monkeypatch):
    moj = _servico(client, ha, "moj")
    mapa = {"metadata.example": ["169.254.169.254"], "casa.example": ["127.0.0.1"],
            "rede.example": ["10.1.2.3"], "v6.example": ["::ffff:10.0.0.1"], "ok.example": ["93.184.216.34"]}
    monkeypatch.setattr(webhook_guard, "_resolver", lambda host: mapa[host])
    for url in ("https://metadata.example/", "https://casa.example/", "https://rede.example/h",
                "https://v6.example/h", "http://ok.example/h", "https://u:p@ok.example/h"):
        r = client.post(BASE, json={"url": url, "secret": SEGREDO}, headers=moj)
        assert r.status_code == 400 and r.json()["code"] == "webhook_url_forbidden", url
    assert client.post(BASE, json={"url": "https://ok.example/h", "secret": SEGREDO}, headers=moj).status_code == 201


def test_a_administracao_libera_um_destino_interno(client, img, ha, data_root, monkeypatch):
    moj = _servico(client, ha, "moj")
    monkeypatch.setattr(webhook_guard, "_resolver", lambda host: ["10.1.2.3"])
    fsdb.write_json(data_root / "server.json", {"webhooks": {"allow_hosts": ["moj.interno", "10.9.0.0/16"]}})
    assert client.post(BASE, json={"url": "http://moj.interno/h", "secret": SEGREDO}, headers=moj).status_code == 201
    assert client.post(BASE, json={"url": "https://rede.example/h", "secret": SEGREDO}, headers=moj).status_code == 400
    fsdb.write_json(data_root / "server.json", {"webhooks": {"allow_hosts": ["10.1.0.0/16"]}})
    assert client.post(BASE, json={"url": "http://rede.example/h", "secret": SEGREDO}, headers=moj).status_code == 201


def test_segredo_obrigatorio_e_teto_para_chave_de_servico(client, img, ha, publico):
    moj = _servico(client, ha, "moj")
    for ruim in ({}, {"secret": "curto"}, {"secret": "***"}):
        r = client.post(BASE, json={"url": "https://moj.example/x", **ruim}, headers=moj)
        assert r.status_code == 400 and r.json()["code"] == "invalid_secret", ruim
    for i in range(ws.TETO_POR_SERVICO):
        assert client.post(BASE, json={"url": f"https://moj.example/{i}", "secret": SEGREDO}, headers=moj).status_code == 201
    r = client.post(BASE, json={"url": "https://moj.example/demais", "secret": SEGREDO}, headers=moj)
    assert r.status_code == 400 and r.json()["code"] == "webhook_limit"


def test_ler_e_regravar_a_lista_nao_destroi_nada(client, img, ha, publico):
    """O que o MOJ fazia com a chave de admin: GET, acrescenta o seu, PUT."""
    moj = _servico(client, ha, "moj")
    de_servico = client.post(BASE, json={"url": "https://moj.example/h", "secret": SEGREDO}, headers=moj).json()
    antigo = client.post(BASE, json={"url": "https://antigo.example/h", "secret": "segredo-antigo"}, headers=ha).json()

    lista = client.get(BASE, headers=ha).json()["webhooks"]
    assert all(w["secret"] == "***" for w in lista)
    do_admin = [w for w in lista if w["owner"] == "admin"]
    r = client.put(BASE, json={"webhooks": do_admin + [{"url": "https://novo.example/h", "secret": "segredo-novo"}]}, headers=ha)
    assert r.status_code == 200 and r.json() == {"ok": True, "webhooks": 2, "kept": 1}

    gravados = {w["url"]: w for w in ws.carregar("testes3")}
    assert gravados["https://antigo.example/h"]["secret"] == "segredo-antigo", "a máscara virou segredo"
    assert gravados["https://antigo.example/h"]["id"] == antigo["id"]
    assert gravados["https://novo.example/h"]["secret"] == "segredo-novo"
    assert gravados["https://moj.example/h"]["id"] == de_servico["id"], "o PUT apagou o webhook da chave de serviço"
    # "" explícito limpa; máscara em entrada nova é erro
    client.put(BASE, json={"webhooks": [{"url": "https://antigo.example/h", "secret": ""}]}, headers=ha)
    assert {w["url"]: w for w in ws.carregar("testes3")}["https://antigo.example/h"]["secret"] == ""
    r = client.put(BASE, json={"webhooks": [{"url": "https://outro.example/h", "secret": "***"}]}, headers=ha)
    assert r.status_code == 400 and r.json()["code"] == "invalid_secret"


def test_arquivo_antigo_sem_id_e_migrado_na_leitura(client, img, ha, data_root):
    arq = data_root / "site-images" / "testes3" / "webhooks.json"
    fsdb.write_json(arq, [{"url": "http://127.0.0.1:9/h", "secret": "s", "events": ["machine.locked"]}])
    um = client.get(BASE, headers=ha).json()["webhooks"]
    dois = client.get(BASE, headers=ha).json()["webhooks"]
    assert um == dois and um[0]["id"].startswith("wh_") and um[0]["owner"] == "admin"
    assert "id" not in fsdb.read_json(arq)[0], "ler não grava"
    assert webhook_push.webhooks_for("testes3", "machine.locked")[0]["id"] == um[0]["id"]
    # a primeira escrita leva a migração para o disco
    client.put(f"{BASE}/{um[0]['id']}", json={"events": []}, headers=ha)
    assert fsdb.read_json(arq)[0]["id"] == um[0]["id"]


@pytest.mark.anyio
async def test_botao_de_teste_e_lista_de_falhas(data_root, image_testes3, admin_key):
    """O teste bate de verdade na URL e devolve o status; a entrega que morre
    aparece em `deliveries`."""
    import asyncio
    import json

    import httpx
    import uvicorn
    from fastapi import FastAPI, Request

    from server.app.main import create_app

    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    vistos = []
    receptor = FastAPI()

    @receptor.post("/h")
    async def h(request: Request):
        vistos.append(json.loads(await request.body()))
        return {}

    server = uvicorn.Server(uvicorn.Config(receptor, host="127.0.0.1", port=8897, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)

    ha = {"Authorization": f"Bearer {admin_key}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        w = (await c.post(BASE, json={"url": "http://127.0.0.1:8897/h", "secret": SEGREDO}, headers=ha)).json()
        r = (await c.post(f"{BASE}/{w['id']}/test", headers=ha)).json()
        assert r["ok"] and r["status_code"] == 200 and isinstance(r["elapsed_ms"], int)
        assert vistos[0]["event"] == "webhook.test" and vistos[0]["delivery"] == r["delivery"]

        morto = (await c.post(BASE, json={"url": "http://127.0.0.1:9/h"}, headers=ha)).json()
        r = (await c.post(f"{BASE}/{morto['id']}/test", headers=ha)).json()
        assert not r["ok"] and r["status_code"] is None and r["error"]

        webhook_push._registra("testes3", {"at": 1, "delivery": "d", "event": "x", "webhook_id": morto["id"], "attempts": 3})
        falhas = (await c.get(f"{BASE}/deliveries", headers=ha)).json()["deliveries"]
        assert falhas[-1]["webhook_id"] == morto["id"]
    server.should_exit = True
    await task
