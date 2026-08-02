"""Verifica o caminho RÁPIDO do long-poll, no mesmo event loop.

O TestClient síncrono roda cada requisição em um loop próprio, então o sinal
em memória não cruza — lá o teste passa pelo mecanismo de segurança (a
reconferência periódica do disco, ≤5 s). Aqui as duas pontas rodam no MESMO
loop, como no uvicorn de produção, e medimos a latência real.
"""

import asyncio
import time

import httpx
import pytest

from server.app import fsdb
from server.app.main import create_app

MAC = "52-54-00-12-34-56"


@pytest.mark.anyio
async def test_lock_reaches_machine_in_under_a_second(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    hm = {"X-NB-Machine-Key": image_testes3["machine_key"]}
    hi = {"Authorization": f"Bearer {image_testes3['token']}"}

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post(f"/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm)

        t0 = time.monotonic()
        poll = asyncio.create_task(
            c.get(f"/api/v1/site-images/testes3/machines/{MAC}/commands?wait=25", headers=hm)
        )
        await asyncio.sleep(0.2)  # o agente já está pendurado esperando
        await c.post("/api/v1/site-images/testes3/lock", headers=hi)

        resp = await asyncio.wait_for(poll, timeout=15)
        elapsed = time.monotonic() - t0

    body = resp.json()
    assert [cmd["command"] for cmd in body["commands"]] == ["donottouch"]
    assert body["lock"]["locked"] is True
    # requisito operacional: bloquear a sala em muito menos de 10 s
    assert elapsed < 1.5, f"latência de {elapsed:.2f}s — esperado abaixo de 1,5s"


@pytest.mark.anyio
async def test_many_machines_wait_without_burning_cpu(data_root, image_testes3):
    """50 agentes pendurados ao mesmo tempo: todos recebem o comando junto.
    É o cenário da sala inteira sendo travada de uma vez."""
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    hm = {"X-NB-Machine-Key": image_testes3["machine_key"]}
    hi = {"Authorization": f"Bearer {image_testes3['token']}"}
    macs = [f"52-54-00-00-{i // 256:02x}-{i % 256:02x}" for i in range(50)]

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        for mac in macs:
            await c.post(f"/api/v1/site-images/testes3/machines/{mac}/status", json={}, headers=hm)

        t0 = time.monotonic()
        polls = [
            asyncio.create_task(
                c.get(f"/api/v1/site-images/testes3/machines/{mac}/commands?wait=25", headers=hm)
            )
            for mac in macs
        ]
        await asyncio.sleep(0.3)
        r = await c.post("/api/v1/site-images/testes3/lock", headers=hi)
        assert r.json()["machines"] == 50

        respostas = await asyncio.wait_for(asyncio.gather(*polls), timeout=20)
        elapsed = time.monotonic() - t0

    assert all(r.json()["commands"][0]["command"] == "donottouch" for r in respostas)
    assert elapsed < 3, f"50 máquinas levaram {elapsed:.2f}s"


@pytest.fixture
def anyio_backend():
    return "asyncio"
