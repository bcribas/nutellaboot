"""Logs de máquina: ingestão com teto, leitura e autenticação.

O nb2 mandava `journalctl` para o servidor e isso se perdeu na reescrita. Volta
com dois tetos, porque log é o tipo de dado que enche disco em silêncio: um por
requisição e um por máquina.
"""

import re

import pytest

from server.app import fsdb
from server.app.services import logs
from server.app.services.default_schema import build_default_schema


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def imagem(client, data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    r = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "Sala 1", "model": "t"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def hm(imagem):
    return {"X-NB-Machine-Key": imagem["machine_key"], "Content-Type": "text/plain"}


MAC = "52-54-00-11-22-33"
ROTA = f"/api/v1/site-images/sala1/machines/{MAC}/logs"


# --- ingestão ---


def test_maquina_envia_e_admin_le(client, imagem, hm, ha):
    r = client.post(ROTA, content=b"kernel: algo aconteceu\nmais uma linha", headers=hm)
    assert r.status_code == 200, r.text
    assert r.json()["stored"] > 0

    r = client.get(ROTA, headers=ha)
    assert r.status_code == 200
    corpo = r.json()
    assert "kernel: algo aconteceu" in corpo["journal"]
    assert corpo["bytes"] > 0


def test_cada_envio_vira_um_bloco_datado(client, imagem, hm, ha):
    """Sem o cabeçalho não dá para separar o que veio em cada ciclo, e o log
    vira uma parede de texto sem hora."""
    client.post(ROTA, content=b"primeiro pedaco", headers=hm)
    client.post(ROTA, content=b"segundo pedaco", headers=hm)
    journal = client.get(ROTA, headers=ha).json()["journal"]
    assert journal.count("=====") == 4  # dois blocos, dois delimitadores cada
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", journal)
    assert journal.index("primeiro") < journal.index("segundo")


def test_envio_vazio_nao_cria_bloco(client, imagem, hm, ha):
    """O agente não manda nada quando o incremento é vazio; se ainda assim
    chegar, não vale poluir o histórico."""
    r = client.post(ROTA, content=b"   \n\n", headers=hm)
    assert r.status_code == 200
    assert r.json()["stored"] == 0
    assert client.get(ROTA, headers=ha).json()["journal"] == ""


def test_envio_grande_demais_e_recusado(client, imagem, hm, ha):
    """Uma máquina em laço de erro encheria o disco do servidor sozinha."""
    grande = b"x" * (logs.MAX_ENVIO + 1)
    r = client.post(ROTA, content=grande, headers=hm)
    assert r.status_code == 413
    assert client.get(ROTA, headers=ha).json()["bytes"] == 0


def test_teto_por_maquina_mantem_a_cauda(client, imagem, hm, ha, monkeypatch):
    """Ao estourar, o começo é descartado e o fim — o que acabou de acontecer —
    é o que fica."""
    monkeypatch.setattr(logs, "POR_MAQUINA", 64 * 1024)
    for i in range(80):
        client.post(ROTA, content=f"linha numero {i} ".encode() + b"z" * 1000, headers=hm)

    assert logs.tamanho("sala1", MAC) <= 64 * 1024
    journal = client.get(ROTA, headers=ha, params={"tail": 20000}).json()["journal"]
    assert "linha numero 79" in journal
    assert "linha numero 0 " not in journal


def test_tail_limita_o_que_volta(client, imagem, hm, ha):
    client.post(ROTA, content=b"\n".join(f"linha {i}".encode() for i in range(500)), headers=hm)
    curto = client.get(ROTA, headers=ha, params={"tail": 5}).json()["journal"]
    assert len(curto.splitlines()) == 5
    assert "linha 499" in curto


# --- autenticação ---


def test_sem_chave_de_maquina_nao_envia(client, imagem):
    r = client.post(ROTA, content=b"log", headers={"Content-Type": "text/plain"})
    assert r.status_code == 401


def test_chave_de_outra_imagem_nao_envia(client, imagem, admin_key):
    outra = client.post(
        "/api/v1/site-images",
        json={"id": "sala2", "fullname": "S2", "model": "t"},
        headers={"Authorization": f"Bearer {admin_key}"},
    ).json()
    r = client.post(ROTA, content=b"log", headers={"X-NB-Machine-Key": outra["machine_key"]})
    assert r.status_code == 401


def test_leitura_exige_credencial(client, imagem, hm):
    client.post(ROTA, content=b"segredo do laboratorio", headers=hm)
    assert client.get(ROTA).status_code == 401


def test_dono_da_imagem_le_os_logs(client, imagem, hm):
    """O coordenador da sede precisa ver o log da máquina dele sem depender da
    administração."""
    client.post(ROTA, content=b"kernel: oops", headers=hm)
    r = client.get(ROTA, headers={"Authorization": f"Bearer {imagem['token']}"})
    assert r.status_code == 200
    assert "oops" in r.json()["journal"]


# --- confirmações de comando, que ninguém conseguia ler ---


def test_leitura_traz_as_confirmacoes_de_comando(client, imagem, hm, ha):
    """O acks.log era escrito desde o começo do projeto e nenhuma rota o
    devolvia: para saber se um comando chegou era preciso abrir o disco do
    servidor."""
    client.post(ROTA, content=b"nada", headers=hm)
    client.post(
        "/api/v1/site-images/sala1/commands",
        json={"command": "cleanhomenow", "target": [MAC]},
        headers=ha,
    )
    cid = client.get(
        f"/api/v1/site-images/sala1/machines/{MAC}/commands",
        headers={"X-NB-Machine-Key": imagem["machine_key"]},
    ).json()["commands"][0]["id"]
    client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/commands/{cid}/ack",
        json={"status": "done"},
        headers={"X-NB-Machine-Key": imagem["machine_key"]},
    )

    acks = client.get(ROTA, headers=ha).json()["acks"]
    assert [a["id"] for a in acks] == [cid]
    assert acks[0]["status"] == "done"


# --- o tamanho aparece na listagem ---


def test_listagem_de_maquinas_diz_se_ha_log(client, imagem, hm, ha):
    antes = client.get("/api/v1/site-images/sala1/machines", headers=ha).json()["machines"]
    client.post(ROTA, content=b"kernel: algo", headers=hm)
    depois = client.get("/api/v1/site-images/sala1/machines", headers=ha).json()["machines"]

    assert antes == [] or antes[0]["logs"]["bytes"] == 0
    assert depois[0]["logs"]["bytes"] > 0
    assert depois[0]["logs"]["at"] is not None


# --- telemetria também ganhou teto ---


def test_telemetria_grande_demais_e_recusada(client, imagem):
    from server.app.routers.machines import MAX_STATUS

    r = client.post(
        f"/api/v1/site-images/sala1/machines/{MAC}/status",
        content=b'{"x":"' + b"y" * MAX_STATUS + b'"}',
        headers={"X-NB-Machine-Key": imagem["machine_key"], "Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_telemetria_invalida_e_recusada(client, imagem):
    h = {"X-NB-Machine-Key": imagem["machine_key"], "Content-Type": "application/json"}
    rota = f"/api/v1/site-images/sala1/machines/{MAC}/status"
    assert client.post(rota, content=b"nao e json", headers=h).status_code == 400
    assert client.post(rota, content=b"[1,2,3]", headers=h).status_code == 400


# --- a série da máquina (os gráficos do duplo clique no hotconfig) ---


ROTA_SAMPLES = f"/api/v1/site-images/sala1/machines/{MAC}/samples"


def _planta_amostras(n, passo=45, base=None):
    import json as _json
    import time as _time

    from server.app.services import samples

    base = base or (_time.time() - n * passo)
    for i in range(n):
        linha = {"t": int(base + i * passo), "mem": 30 + (i % 40), "ld": round(0.5 + (i % 8) / 2, 2),
                 "sw": 0 if i % 5 else 120, "hd": 20 + (i % 60)}
        samples.append_capped(
            samples.machine_dir("sala1", MAC) / samples.ARQUIVO,
            _json.dumps(linha, separators=(",", ":")) + "\n",
            cap=samples.POR_MAQUINA,
        )


def test_a_rota_devolve_a_janela(client, imagem, ha):
    _planta_amostras(20)
    r = client.get(ROTA_SAMPLES, headers=ha)
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo["points"]) == 20
    assert corpo["truncated"] is False
    assert {"t", "mem", "ld", "sw", "hd"} <= set(corpo["points"][0])

    meio = corpo["points"][10]["t"]
    r = client.get(f"{ROTA_SAMPLES}?since={meio}", headers=ha)
    assert all(p["t"] >= meio for p in r.json()["points"])
    r = client.get(f"{ROTA_SAMPLES}?until={meio}", headers=ha)
    assert all(p["t"] <= meio for p in r.json()["points"])


def test_o_downsample_tem_teto(client, imagem, ha):
    from server.app.routers.machines import MAX_AMOSTRAS

    _planta_amostras(MAX_AMOSTRAS * 3)
    corpo = client.get(ROTA_SAMPLES, headers=ha).json()
    assert len(corpo["points"]) == MAX_AMOSTRAS
    ts = [p["t"] for p in corpo["points"]]
    assert ts == sorted(ts), "o downsample preserva a ordem"


def test_o_dono_da_imagem_le_a_serie(client, imagem):
    _planta_amostras(3)
    tk = imagem["token"]
    r = client.get(ROTA_SAMPLES, headers={"Authorization": f"Bearer {tk}"})
    assert r.status_code == 200, "o token nb3i_ do hotconfig serve"


def test_a_serie_exige_credencial(client, imagem):
    assert client.get(ROTA_SAMPLES).status_code == 401
