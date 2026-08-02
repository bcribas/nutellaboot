"""Testes contra um uvicorn de verdade.

Necessário porque o ASGITransport do httpx não faz streaming: ele executa a
aplicação até o fim antes de devolver a resposta, então um fluxo SSE (que não
termina) o deixaria pendurado para sempre. Estes testes sobem o servidor do
mesmo jeito que a produção — um único worker — e falam HTTP com ele.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from server.app import auth, fsdb  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    token = auth.new_key("nb3i")
    mkey = auth.new_key("nb3m")
    fsdb.write_json(data / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data / "models" / "t" / "model.json", {"layers": []})
    img = data / "site-images" / "testes3"
    fsdb.write_json(img / "image.json", {"id": "testes3", "model": "t", "namespace": "personal"})
    fsdb.write_text(img / "token", token + "\n")
    fsdb.write_text(img / "machine.key", mkey + "\n")

    port = free_port()
    env = {**os.environ, "NB3_DATA_ROOT": str(data), "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen(
        [
            str(REPO / ".venv" / "bin" / "uvicorn"),
            "server.app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("uvicorn não subiu: " + proc.stderr.read().decode()[-2000:])

    yield {"base": base, "token": token, "machine_key": mkey, "data": data}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


MAC = "52-54-00-99-88-77"


def test_health_and_boot_endpoints(live):
    b = live["base"]
    assert httpx.get(f"{b}/boot/v3/sanity").text.strip() == "penguin"
    assert httpx.get(f"{b}/boot/v3/testes3/manifest").status_code == 200
    assert "IMAGEROOT='testes3'" in httpx.get(f"{b}/boot/v3/testes3/stuff").text


def test_sse_delivers_events_live(live):
    """O painel do laboratório recebe as mudanças sem recarregar a página."""
    b, tk = live["base"], live["token"]
    hm = {"X-NB-Machine-Key": live["machine_key"]}
    recebidos = []

    with httpx.stream(
        "GET", f"{b}/api/v1/site-images/testes3/events?tk={tk}", timeout=15
    ) as stream:
        linhas = stream.iter_lines()
        next(linhas)  # "retry: 3000"

        httpx.post(f"{b}/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm, timeout=5)
        t0 = time.monotonic()
        for line in linhas:
            if line.startswith("event:"):
                recebidos.append(line.split(":", 1)[1].strip())
            if len(recebidos) >= 2 or time.monotonic() - t0 > 10:
                break

    assert "machine.status" in recebidos
    assert "machine.first_seen" in recebidos


def test_lock_latency_over_http(live):
    """Fim a fim, por HTTP real: o agente pendurado no long-poll recebe o
    bloqueio em poucos segundos (o nb2 passava de 30 s)."""
    import threading

    b = live["base"]
    hm = {"X-NB-Machine-Key": live["machine_key"]}
    hi = {"Authorization": f"Bearer {live['token']}"}
    httpx.post(f"{b}/api/v1/site-images/testes3/machines/{MAC}/status", json={}, headers=hm, timeout=5)

    resultado = {}

    def agente():
        t0 = time.monotonic()
        r = httpx.get(
            f"{b}/api/v1/site-images/testes3/machines/{MAC}/commands?wait=25", headers=hm, timeout=40
        )
        resultado["elapsed"] = time.monotonic() - t0
        resultado["body"] = r.json()

    th = threading.Thread(target=agente)
    th.start()
    time.sleep(0.5)
    httpx.post(f"{b}/api/v1/site-images/testes3/machines/{MAC}/lock", headers=hi, timeout=5)
    th.join(timeout=30)

    assert not th.is_alive()
    assert resultado["elapsed"] < 3, f"levou {resultado['elapsed']:.2f}s"
    assert resultado["body"]["commands"][0]["command"] == "donottouch"
    assert resultado["body"]["lock"]["locked"] is True
