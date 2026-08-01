import json
import os
import threading

from server.app import fsdb


def test_write_read_json_roundtrip(tmp_path):
    p = tmp_path / "a" / "b.json"
    fsdb.write_json(p, {"x": 1, "é": "açúcar"})
    assert fsdb.read_json(p) == {"x": 1, "é": "açúcar"}


def test_read_json_default(tmp_path):
    assert fsdb.read_json(tmp_path / "nada.json", {"d": True}) == {"d": True}


def test_atomic_write_no_tmp_leftover(tmp_path):
    p = tmp_path / "f.json"
    fsdb.write_json(p, {"v": 1})
    fsdb.write_json(p, {"v": 2})
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []
    assert fsdb.read_json(p)["v"] == 2


def test_write_text_mode(tmp_path):
    p = tmp_path / "token"
    fsdb.write_text(p, "segredo\n", mode=0o600)
    assert (p.stat().st_mode & 0o777) == 0o600
    assert fsdb.read_text(p) == "segredo\n"


def test_locked_serializes_writers(tmp_path):
    """Dois escritores concorrentes sob locked() nunca perdem incrementos."""
    p = tmp_path / "contador.json"
    fsdb.write_json(p, {"n": 0})

    def bump():
        for _ in range(50):
            with fsdb.locked(tmp_path):
                cur = fsdb.read_json(p)["n"]
                fsdb.write_json(p, {"n": cur + 1})

    threads = [threading.Thread(target=bump) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert fsdb.read_json(p)["n"] == 200


def test_json_file_ends_with_newline(tmp_path):
    p = tmp_path / "x.json"
    fsdb.write_json(p, [1, 2])
    raw = p.read_bytes()
    assert raw.endswith(b"\n")
    assert json.loads(raw) == [1, 2]
