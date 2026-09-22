import os
import sys
from pathlib import Path

# a suíte cria dezenas de apps; nenhum deles deve ligar o gravador de série
os.environ.setdefault("NB3_SEM_SERIE", "1")

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from server.app import auth, fsdb  # noqa: E402
from server.app.settings import settings  # noqa: E402


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """data/ isolado por teste."""
    monkeypatch.setattr(settings, "data_root", tmp_path)
    # o disco é por teste; os mapas em memória do processo também têm de ser
    from server.app.services import keyusage, presence

    keyusage.reset()
    presence.reset()
    return tmp_path


@pytest.fixture
def admin_key(data_root):
    key = auth.new_key("nb3a")
    fsdb.write_json(
        data_root / "keys" / "admin.json",
        {"keys": [{"id": "test", "sha256": auth.key_hash(key)}]},
    )
    return key


@pytest.fixture
def image_testes3(data_root):
    img = data_root / "site-images" / "testes3"
    token = auth.new_key("nb3i")
    mkey = auth.new_key("nb3m")
    fsdb.write_json(img / "image.json", {"id": "testes3", "model": "t", "namespace": "personal"})
    fsdb.write_text(img / "token", token + "\n")
    fsdb.write_text(img / "machine.key", mkey + "\n")
    return {"id": "testes3", "token": token, "machine_key": mkey}


@pytest.fixture
def client(data_root):
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def servidor(data_root, admin_key):
    """Sobe um uvicorn de verdade: as ferramentas falam HTTP, não importam o app
    (`nb3-nova-temporada`, `nb3-camada-telemetria`)."""
    import socket
    import subprocess
    import time

    porta = socket.socket()
    porta.bind(("127.0.0.1", 0))
    _, p = porta.getsockname()
    porta.close()

    env = {**os.environ, "NB3_DATA_ROOT": str(data_root), "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen(
        [".venv/bin/python", "-m", "uvicorn", "server.app.main:app",
         "--host", "127.0.0.1", "--port", str(p), "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{p}"
    import urllib.request

    for _ in range(80):
        try:
            urllib.request.urlopen(f"{base}/api/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("uvicorn nao subiu")
    yield base, admin_key
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
