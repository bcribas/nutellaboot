import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from server.app import auth, fsdb  # noqa: E402
from server.app.settings import settings  # noqa: E402


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """data/ isolado por teste."""
    monkeypatch.setattr(settings, "data_root", tmp_path)
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
