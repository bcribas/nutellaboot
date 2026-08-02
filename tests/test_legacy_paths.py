"""Compatibilidade dos caminhos que já estão em campo.

O agente de telemetria vai DENTRO da camada squashfs publicada: máquinas já
instaladas continuam chamando o caminho antigo da API, e não há como
atualizá-las remotamente sem telemetria — que é justamente o que quebraria.
Este teste lê o próprio agent.sh e exige que o servidor ainda atenda o que
ele chama, para ninguém "limpar" o alias em 2027.
"""

import re
from pathlib import Path

import pytest

from server.app import fsdb
from server.app.services import store

REPO = Path(__file__).resolve().parents[1]
AGENT = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "agent.sh"
MAC = "52-54-00-11-22-33"


def test_agente_usa_o_prefixo_legado():
    """Se um dia o agent.sh mudar de prefixo, este teste avisa que o alias
    pode (aí sim) ser reavaliado."""
    prefixos = re.findall(r'API="\$NB_SERVER(/api/v1/[a-z-]+)/', AGENT.read_text())
    assert prefixos, "não achei o prefixo da API no agent.sh"
    assert prefixos[0] in ("/api/v1/images", "/api/v1/site-images"), prefixos


@pytest.fixture
def img(data_root, admin_key):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    return store.create_site_image("lab1", "Lab", "t")


def test_caminho_antigo_continua_atendendo(client, img):
    """As três chamadas que o agente faz têm de funcionar pelo caminho velho."""
    hm = {"X-NB-Machine-Key": img["machine_key"]}
    hi = {"Authorization": f"Bearer {img['token']}"}

    # telemetria
    r = client.post(f"/api/v1/images/lab1/machines/{MAC}/status", json={}, headers=hm)
    assert r.status_code == 200, "telemetria quebraria em toda máquina em campo"

    # fila de comandos (long-poll)
    r = client.get(f"/api/v1/images/lab1/machines/{MAC}/commands", headers=hm)
    assert r.status_code == 200

    # ack de comando
    client.post("/api/v1/images/lab1/lock", headers=hi)
    cid = client.get(f"/api/v1/images/lab1/machines/{MAC}/commands", headers=hm).json()["commands"][0]["id"]
    r = client.post(
        f"/api/v1/images/lab1/machines/{MAC}/commands/{cid}/ack", json={"status": "done"}, headers=hm
    )
    assert r.status_code == 200


def test_caminho_antigo_e_novo_dao_a_mesma_resposta(client, img):
    hi = {"Authorization": f"Bearer {img['token']}"}
    antigo = client.get("/api/v1/images/lab1/config", headers=hi)
    novo = client.get("/api/v1/site-images/lab1/config", headers=hi)
    assert antigo.status_code == novo.status_code == 200
    assert antigo.json() == novo.json()


def test_so_o_caminho_novo_aparece_na_documentacao(client):
    """O alias existe para compatibilidade, mas a API publicada é uma só."""
    spec = client.get("/api/v1/openapi.json").json()
    assert not [p for p in spec["paths"] if p.startswith("/api/v1/images")]
    assert [p for p in spec["paths"] if p.startswith("/api/v1/site-images")]


def test_contrato_de_boot_intacto(client, img):
    """O que está gravado em pendrive e initrd não muda."""
    bk = {"X-NB-Boot-Key": img["boot_key"]}
    assert client.get("/boot/v3/sanity").text.strip() == "penguin"
    assert client.get("/boot/v3/lab1/manifest", headers=bk).status_code == 200
    assert "IMAGEROOT='lab1'" in client.get("/boot/v3/lab1/stuff", headers=bk).text
