"""Todo erro leva `code`, e é por ele que o cliente decide.

O MOJ mapeava TODO 404 do vínculo para "time fora do roster", inclusive o de
imagem inexistente, porque o corpo só tinha uma frase em português. A frase
pode mudar; o código é contrato (publicado em `GET /events/types`).
"""

import re
from pathlib import Path

import pytest

from server.app import errors, fsdb
from server.app.services import ratelimit

REPO = Path(__file__).resolve().parents[1]
MAC = "52-54-00-12-34-56"


@pytest.fixture
def img(data_root, image_testes3):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    return image_testes3


@pytest.fixture
def hi(img):
    return {"Authorization": f"Bearer {img['token']}"}


def _servico(client, admin_key, scopes, images=()):
    r = client.post(
        "/api/v1/service-keys",
        json={"name": "moj", "scopes": list(scopes), "images": list(images)},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    return {"Authorization": f"Bearer {r.json()['key']}"}


def test_os_codigos_que_o_moj_le(client, img, hi, admin_key):
    base = "/api/v1/site-images/testes3"
    casos = [
        (client.get(f"{base}/machines"), 401, "unauthorized"),
        (client.put(f"{base}/machines/{MAC}/binding", json={"user_id": "x"}, headers=hi), 404, "user_not_in_roster"),
        (client.put(f"{base}/machines/zz/binding", json={"name": "x"}, headers=hi), 400, "invalid_mac"),
        (client.post(f"{base}/commands", json={"command": "rm -rf"}, headers=hi), 400, "command_not_allowed"),
        (client.post(f"{base}/commands", json={"command": "mlreboot", "target": []}, headers=hi), 400, "no_target"),
        (client.post(f"{base}/commands", json={"command": "mlreboot", "macs": [MAC]}, headers=hi), 400, "no_target"),
    ]
    hs = _servico(client, admin_key, ["roster:read"], ["outra*"])
    casos += [
        (client.get(f"{base}/machines", headers=hs), 403, "insufficient_scope"),
        (client.get(f"{base}/roster", headers=hs), 403, "image_out_of_scope"),
        (client.get("/api/v1/site-images/naoexiste/roster", headers=hs), 404, "image_not_found"),
    ]
    for r, status, codigo in casos:
        assert r.status_code == status, r.text
        corpo = r.json()
        assert corpo["code"] == codigo, corpo
        assert corpo["detail"], "a frase continua lá, para gente ler"


def test_erro_sem_codigo_proprio_ganha_o_do_status(client, admin_key):
    r = client.get("/api/v1/models/naoexiste", headers={"Authorization": f"Bearer {admin_key}"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_validacao_tambem_tem_codigo(client, admin_key):
    r = client.post("/api/v1/site-images", json={"id": 3}, headers={"Authorization": f"Bearer {admin_key}"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error" and isinstance(r.json()["detail"], list)


def test_429_diz_quando_tentar_de_novo(client):
    ratelimit.reset()
    h = {"Authorization": "Bearer nb3a_" + "0" * 32, "X-Forwarded-For": "198.51.100.7"}
    ultimo = None
    for _ in range(12):
        ultimo = client.get("/api/v1/whoami", headers=h)
    assert ultimo.status_code == 429
    assert ultimo.json()["code"] == "rate_limited"
    assert int(ultimo.headers["Retry-After"]) >= 1
    ratelimit.reset()


def test_o_catalogo_e_publico_e_completo(client):
    publicados = client.get("/api/v1/events/types").json()["error_codes"]
    assert publicados == errors.CODIGOS
    assert set(errors.PADRAO_POR_STATUS.values()) <= set(publicados)


def test_todo_codigo_levantado_esta_no_catalogo_e_vice_versa():
    usados = set()
    for arq in (REPO / "server" / "app").rglob("*.py"):
        usados |= set(re.findall(r'\berro\(\s*\d{3},\s*"([a-z_]+)"', arq.read_text(encoding="utf-8")))
    assert usados, "nenhum erro( encontrado: a regex quebrou?"
    assert usados <= set(errors.CODIGOS), usados - set(errors.CODIGOS)
    sem_emissor = set(errors.CODIGOS) - usados - set(errors.PADRAO_POR_STATUS.values())
    assert sem_emissor == set(), f"código no catálogo que ninguém levanta: {sem_emissor}"
