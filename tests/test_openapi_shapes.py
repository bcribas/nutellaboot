"""Os formatos publicados no OpenAPI batem com o que as rotas devolvem.

Os modelos de `server/app/schemas.py` são documentação: não filtram nem coagem
a resposta. Por isso mesmo podem mentir sem ninguém notar; este teste valida
respostas REAIS contra eles e prende os campos do contrato que o MOJ lê.
"""

import json

import pytest

from server.app import fsdb, schemas
from server.app.main import create_app

BASE = "/api/v1/site-images/testes3"
MAC = "52-54-00-12-34-56"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


def _declarados(modelo, caminho=""):
    """Os campos de um modelo, em notação pontuada, descendo nos aninhados."""
    out = set()
    for nome, campo in modelo.model_fields.items():
        out.add(caminho + nome)
        for t in (campo.annotation, *getattr(campo.annotation, "__args__", ())):
            for interno in (t, *getattr(t, "__args__", ())):
                if isinstance(interno, type) and issubclass(interno, schemas.BaseModel):
                    out |= _declarados(interno, caminho + nome + ".")
    return out


def test_os_campos_que_o_moj_le_estao_no_esquema():
    maquina = _declarados(schemas.Machine)
    assert {
        "mac", "first_seen", "last_seen", "online", "last_boot", "boots", "binding", "alerts",
        "alerts.kind", "alerts.other_mac", "status.t_agent", "status.hwinfo.processor",
        "status.hwinfo.cores", "status.hwinfo.memtotal_mb", "status.hwinfo.machine_id",
        "status.hwinfo.boot_id", "status.hwinfo.mac", "status.hwinfo.product_vendor",
        "status.hwinfo.product_name", "status.hwinfo.last_boot", "status.sysresources",
        "status.sysdisk.home_pct", "status.operations.firewall", "status.operations.screen_lock",
        "status.operations.editors_time",
    } <= maquina
    assert set("t mem ld sw hd ed fw lk psi_mem psi_cpu psi_io oom idle skew edm eds".split()) == set(
        schemas.SamplePoint.model_fields
    )
    assert {"mac", "points", "native_points", "resampled", "interval_s", "since", "until", "truncated"} == set(
        schemas.SamplesWindow.model_fields
    )
    assert {"event", "image", "at", "delivery", "data"} == set(schemas.WebhookPayload.model_fields)
    assert {"command_id", "machines"} == set(schemas.CommandResult.model_fields)


def test_todo_esquema_e_aberto_e_todo_campo_opcional():
    """Campo novo nosso não pode quebrar o validador de um cliente."""
    doc = create_app().openapi()
    nossos = {m.__name__ for m in (*schemas.DOCS.values(), *schemas.NDJSON.values(), schemas.ErrorBody, schemas.WebhookPayload)}
    for nome, esquema in doc["components"]["schemas"].items():
        modelo = getattr(schemas, nome, None)
        if modelo is None or not (nome in nossos or issubclass(modelo, schemas.Aberto)):
            continue
        assert esquema.get("additionalProperties") is True, nome
        assert not esquema.get("required"), f"{nome} tem campo obrigatório"


def test_as_rotas_documentadas_existem_e_apontam_para_o_esquema():
    doc = create_app().openapi()
    for (metodo, caminho), modelo in schemas.DOCS.items():
        respostas = doc["paths"][caminho][metodo]["responses"]
        ok = respostas.get("200") or respostas["201"]
        assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/" + modelo.__name__)
        assert "4XX" in respostas
    assert "nb3-event" in doc["webhooks"]


def test_respostas_reais_validam_e_saem_intocadas(client, img, admin_key):
    hm = {"X-NB-Machine-Key": img["machine_key"]}
    hi = {"Authorization": f"Bearer {img['token']}"}
    ha = {"Authorization": f"Bearer {admin_key}"}
    # um status com campo que o esquema NÃO conhece e um número que um
    # response_model de verdade coagiria
    status = {"t_agent": 1788000000, "agent_version": "2026.09.2", "capabilities": ["psi"],
              "hwinfo": {"boot_id": "777", "cores": 8, "mac": MAC, "coletor_novo": {"x": 1}},
              "sysresources": {"mem_pct": 41.5, "loadavg": [0.5, 0.4, 0.3]},
              "sysdisk": {"home_pct": 12.5}, "operations": {"firewall": True, "editors_time": {"code": 3}},
              "campo_do_futuro": 2.0}
    client.post(f"{BASE}/machines/{MAC}/status", json=status, headers=hm)
    client.post(f"{BASE}/roster", json={"user_id": "t1", "name": "Um"}, headers=hi)
    client.put(f"{BASE}/machines/{MAC}/binding", json={"user_id": "t1", "at": 1788000000}, headers=hi)
    cid = client.post(f"{BASE}/commands", json={"command": "mlreboot", "target": [MAC]}, headers=hi).json()["command_id"]
    chave = client.post("/api/v1/service-keys", json={"name": "moj", "scopes": ["machines:read"]}, headers=ha).json()["key"]

    casos = [
        (schemas.MachineList, client.get(f"{BASE}/machines", headers=hi)),
        (schemas.Machine, client.get(f"{BASE}/machines/{MAC}", headers=hi)),
        (schemas.SamplesWindow, client.get(f"{BASE}/machines/{MAC}/samples", headers=hi)),
        (schemas.Roster, client.get(f"{BASE}/roster", headers=hi)),
        (schemas.BindingList, client.get(f"{BASE}/bindings", headers=hi)),
        (schemas.BindingHistory, client.get(f"{BASE}/machines/{MAC}/binding/history", headers=hi)),
        (schemas.CommandStatus, client.get(f"{BASE}/commands/{cid}", headers=hi)),
        (schemas.CommandsAllowed, client.get(f"{BASE}/commands", headers=hi)),
        (schemas.Whoami, client.get("/api/v1/whoami", headers=ha)),
        (schemas.Whoami, client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {chave}"})),
        (schemas.SiteImageList, client.get("/api/v1/site-images", headers=ha)),
        (schemas.ErrorBody, client.get(f"{BASE}/machines")),
    ]
    for modelo, r in casos:
        modelo.model_validate(r.json())  # levanta se o tipo documentado não bate

    lote = client.get(f"{BASE}/samples", headers={**hi, "Accept-Encoding": "identity"}).text
    schemas.SamplesWindow.model_validate(json.loads(lote.splitlines()[0]))

    # e o fio não passou por modelo nenhum: o que o esquema desconhece continua lá
    st = client.get(f"{BASE}/machines/{MAC}", headers=hi).json()["status"]
    assert st["campo_do_futuro"] == 2.0 and st["hwinfo"]["coletor_novo"] == {"x": 1}
    assert '"campo_do_futuro":2.0' in client.get(f"{BASE}/machines/{MAC}", headers=hi).text.replace(" ", "")
