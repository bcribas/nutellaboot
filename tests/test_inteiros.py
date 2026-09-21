"""Achado 14: instantes saem como inteiro.

`since`/`until` voltavam `1790000630.0` porque a query é float e era ecoada
crua; `at` do webhook e os instantes do vínculo eram `time.time()`. Os `t` dos
pontos sempre foram inteiros. Um cliente com parser estrito de inteiro quebrava
na metade dos campos.
"""

import json

import pytest

from server.app import fsdb

MAC = "52-54-00-12-34-56"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def test_janela_dos_samples_ecoa_inteiros(client, img):
    hm = {"X-NB-Machine-Key": img["machine_key"]}
    hi = {"Authorization": f"Bearer {img['token']}"}
    base = "/api/v1/site-images/testes3"
    client.post(f"{base}/machines/{MAC}/status", json={"sysresources": {"mem_pct": 10}}, headers=hm)

    um = client.get(f"{base}/machines/{MAC}/samples?since=100.7&until=9999999999.5", headers=hi).json()
    assert _int(um["since"]) and _int(um["until"]) and um["since"] == 100

    lote = client.get(f"{base}/samples?since=100.7&until=9999999999.5", headers=hi).text
    linha = json.loads(lote.splitlines()[0])
    assert _int(linha["since"]) and _int(linha["until"])


def test_instantes_do_vinculo_sao_inteiros(client, img):
    hi = {"Authorization": f"Bearer {img['token']}"}
    base = "/api/v1/site-images/testes3"
    b = client.put(f"{base}/machines/{MAC}/binding", json={"name": "Time", "at": 1788026460.9}, headers=hi).json()
    assert _int(b["bound_at"]) and b["client_at"] == 1788026460 and _int(b["client_at"])
    client.delete(f"{base}/machines/{MAC}/binding", headers=hi)
    hist = client.get(f"{base}/machines/{MAC}/binding/history", headers=hi).json()["history"]
    solto = next(h for h in hist if h["event"] == "unbound")
    assert _int(solto["at"])


def test_lote_comprimido_so_quando_pedido(client, img):
    """Uma sede de 300 máquinas são vários MB de JSON repetitivo. O gzip é só
    desta rota e só a pedido: um middleware embrulharia também o SSE."""
    import gzip

    hm = {"X-NB-Machine-Key": img["machine_key"]}
    hi = {"Authorization": f"Bearer {img['token']}"}
    base = "/api/v1/site-images/testes3"
    for i in range(40):
        client.post(f"{base}/machines/52-54-00-00-00-{i:02x}/status", json={"sysresources": {"mem_pct": i}}, headers=hm)

    puro = client.get(f"{base}/samples", headers={**hi, "Accept-Encoding": "identity"})
    assert "content-encoding" not in puro.headers and puro.headers["vary"] == "Accept-Encoding"
    assert len(puro.text.splitlines()) == 40

    with client.stream("GET", f"{base}/samples", headers={**hi, "Accept-Encoding": "gzip"}) as r:
        assert r.headers["content-encoding"] == "gzip"
        cru = b"".join(r.iter_raw())
    assert gzip.decompress(cru).decode() == puro.text
    assert len(cru) < len(puro.content) / 3

    recusa = client.get(f"{base}/samples", headers={**hi, "Accept-Encoding": "gzip;q=0, identity"})
    assert "content-encoding" not in recusa.headers
