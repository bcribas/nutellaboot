"""Onde uma construção de camada vai parar, e de onde a tela sabe disso.

Um sub-admin construiu uma camada sobre o modelo dele; o worker a anexou à
IMAGEM (o destino do pedido). Ele esperava vê-la no modelo, a tela do modelo
dizia "2 camadas" enquanto a imagem bootava com 3, a lista de construções não
mostrava o md5 e o catálogo do modelo só listava camadas já em uso: a tentativa
de pôr a camada no modelo à mão morreu em "md5 inválido".
"""

import pytest

from server.app import fsdb
from server.app.services import ratelimit, store

MD5_BASE = "a" * 32
MD5_EXTRA = "b" * 32


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


def _job(data_root, jid, *, estado="done", model="t", owner="admin", attach_to=(), arquivo="extra.squash", blob=True):
    job = {
        "id": jid,
        "name": "extra",
        "model": model,
        "packages": ["htop"],
        "owner": owner,
        "created_at": 1.0,
        "attach_to": list(attach_to),
    }
    if estado == "done":
        job["output"] = {"file": arquivo, "md5": MD5_EXTRA, "size": 3}
        job["finished_at"] = 2.0
    fsdb.write_json(data_root / "layerbuilds" / estado / f"{jid}.json", job)
    if blob:
        (data_root / "blobs").mkdir(parents=True, exist_ok=True)
        (data_root / "blobs" / arquivo).write_bytes(b"xyz")
    return job


@pytest.fixture
def base(client, data_root, ha):
    """Modelo público `t` da administração com a base, uma imagem da
    administração (`alvo`) e um sub-admin com a imagem `sub1` no mesmo modelo."""
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    fsdb.write_json(
        data_root / "models" / "t" / "model.json",
        {"owner": "admin", "public": True,
         "layers": [{"file": "base.squash", "md5": MD5_BASE, "role": "base", "cdn_url": "https://cdn/base.squash"}]},
    )
    assert client.post(
        "/api/v1/site-images", json={"id": "alvo", "fullname": "Alvo", "model": "t"}, headers=ha
    ).status_code == 201
    code = client.post("/api/v1/invites", json={"max_images": 3}, headers=ha).json()["invites"][0]["code"]
    hs = {"Authorization": f"Bearer {code}"}
    r = client.post("/api/v1/site-images", json={"id": "sub1", "fullname": "Sub", "model": "t"}, headers=hs)
    assert r.status_code == 201, r.text
    return {"code": code, "hs": hs, "owner": f"invite:{code}"}


def _camadas_do_modelo(client, ha, nome="t"):
    return client.get(f"/api/v1/models/{nome}", headers=ha).json()["layers"]


def test_anexar_ao_modelo_poe_na_frente_e_nao_toca_as_imagens(client, base, ha, data_root):
    _job(data_root, "j1", attach_to=["alvo"])
    r = client.post("/api/v1/layerbuilds/j1/attach", json={"model": True}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "t" and r.json()["images"] == []

    camadas = _camadas_do_modelo(client, ha)
    assert [c["file"] for c in camadas] == ["extra.squash", "base.squash"]
    assert camadas[0]["role"] == "extra" and camadas[0]["from_build"] == "j1"
    # o pedido de modelo não reanexa ao destino que a construção pedia
    assert client.get("/api/v1/site-images/alvo/layers", headers=ha).json()["extra"] == []

    # de novo não duplica
    client.post("/api/v1/layerbuilds/j1/attach", json={"model": True}, headers=ha)
    assert [c["file"] for c in _camadas_do_modelo(client, ha)] == ["extra.squash", "base.squash"]


def test_o_modelo_e_sempre_o_da_construcao(client, base, ha, data_root):
    """Um `model` com nome no corpo não escolhe outro modelo: a camada leva o
    estado do apt da base em que foi construída."""
    fsdb.write_json(data_root / "models" / "outro" / "model.json", {"owner": "admin", "layers": []})
    _job(data_root, "j1")
    client.post("/api/v1/layerbuilds/j1/attach", json={"model": "outro"}, headers=ha)
    assert _camadas_do_modelo(client, ha, "outro") == []
    assert _camadas_do_modelo(client, ha)[0]["file"] == "extra.squash"


def test_corpo_vazio_usa_o_destino_do_pedido(client, base, ha, data_root):
    _job(data_root, "j1", attach_to=["alvo"])
    assert client.post("/api/v1/layerbuilds/j1/attach", json={}, headers=ha).status_code == 200
    extras = client.get("/api/v1/site-images/alvo/layers", headers=ha).json()["extra"]
    assert [c["file"] for c in extras] == ["extra.squash"]


def test_sem_imagem_nem_modelo_e_400(client, base, ha, data_root):
    _job(data_root, "j1")
    r = client.post("/api/v1/layerbuilds/j1/attach", json={}, headers=ha)
    assert r.status_code == 400


def test_sub_admin_nao_anexa_em_modelo_que_nao_gere(client, base, ha, data_root):
    """A construção é dele (e visível a ele), mas o modelo público é da
    administração: 404, e o modelo não muda."""
    _job(data_root, "js", owner=base["owner"], attach_to=["sub1"])
    r = client.post("/api/v1/layerbuilds/js/attach", json={"model": True}, headers=base["hs"])
    assert r.status_code == 404
    assert [c["file"] for c in _camadas_do_modelo(client, ha)] == ["base.squash"]
    # e numa imagem alheia no meio da lista, nada é gravado
    r = client.post("/api/v1/layerbuilds/js/attach", json={"image_ids": ["sub1", "alvo"]}, headers=base["hs"])
    assert r.status_code == 404
    assert client.get("/api/v1/site-images/sub1/layers", headers=base["hs"]).json()["extra"] == []


def test_camada_sem_arquivo_nem_publicacao_nao_anexa(client, base, ha, data_root):
    _job(data_root, "j1", blob=False)
    r = client.post("/api/v1/layerbuilds/j1/attach", json={"model": True}, headers=ha)
    assert r.status_code == 409
    assert [c["file"] for c in _camadas_do_modelo(client, ha)] == ["base.squash"]
    item = next(b for b in client.get("/api/v1/layerbuilds", headers=ha).json()["builds"] if b["id"] == "j1")
    assert item["available"] is False


def test_a_lista_diz_onde_a_camada_esta(client, base, ha, data_root):
    _job(data_root, "j1")
    _job(data_root, "jf", estado="failed")

    def anexada():
        builds = client.get("/api/v1/layerbuilds", headers=ha).json()["builds"]
        assert "attached" not in next(b for b in builds if b["id"] == "jf")
        return next(b for b in builds if b["id"] == "j1")["attached"]

    assert anexada() == {"images": [], "model": False}
    client.post("/api/v1/layerbuilds/j1/attach", json={"image_ids": ["alvo"]}, headers=ha)
    assert anexada() == {"images": ["alvo"], "model": False}
    client.post("/api/v1/layerbuilds/j1/attach", json={"model": True}, headers=ha)
    assert anexada() == {"images": ["alvo"], "model": True}


def test_a_lista_do_sub_admin_so_mostra_as_imagens_dele(client, base, ha, data_root):
    _job(data_root, "js", owner=base["owner"], attach_to=["sub1"])
    client.post("/api/v1/layerbuilds/js/attach", json={"image_ids": ["sub1", "alvo"]}, headers=ha)
    item = next(b for b in client.get("/api/v1/layerbuilds", headers=base["hs"]).json()["builds"] if b["id"] == "js")
    assert item["attached"]["images"] == ["sub1"]


def test_camada_na_imagem_e_no_modelo_vai_uma_vez_ao_manifest(client, base, ha, data_root):
    """A máquina montaria o mesmo squash duas vezes no lowerdir. Fica a
    primeira ocorrência, a da imagem, que é a de maior prioridade."""
    _job(data_root, "j1")
    client.post("/api/v1/layerbuilds/j1/attach", json={"image_ids": ["alvo"], "model": True}, headers=ha)
    camadas = store.site_image_layers("alvo")
    assert [c["file"] for c in camadas] == ["extra.squash", "base.squash"]
    assert "from_build" in camadas[0]


def test_o_catalogo_traz_as_construcoes_prontas_com_md5(client, base, ha, data_root):
    _job(data_root, "j1")
    _job(data_root, "jf", estado="failed", arquivo="falhou.squash", blob=False)
    cat = client.get("/api/v1/layers/catalog", headers=ha).json()["layers"]
    extra = next(c for c in cat if c["file"] == "extra.squash")
    assert extra["md5"] == MD5_EXTRA and extra["role"] == "extra"
    assert extra["build"]["id"] == "j1" and extra["build"]["model"] == "t"
    assert extra["available"] is True
    assert not any(c["file"] == "falhou.squash" for c in cat)
    # a camada em uso continua lá, com quem a usa
    assert next(c for c in cat if c["file"] == "base.squash")["used_by"] == ["t"]


def test_o_catalogo_do_sub_admin_nao_traz_construcao_alheia(client, base, ha, data_root):
    _job(data_root, "j1", attach_to=["alvo"])
    cat = client.get("/api/v1/layers/catalog", headers=base["hs"]).json()["layers"]
    assert not any(c.get("build") for c in cat)


def test_o_modelo_mostra_as_camadas_so_das_imagens(client, base, ha, data_root):
    _job(data_root, "j1")
    client.post("/api/v1/layerbuilds/j1/attach", json={"image_ids": ["alvo", "sub1"]}, headers=ha)

    admin = client.get("/api/v1/models/t", headers=ha).json()
    por_imagem = {i["id"]: i for i in admin["image_extras"]}
    assert set(por_imagem) == {"alvo", "sub1"}
    assert [c["file"] for c in por_imagem["alvo"]["layers"]] == ["extra.squash"]
    assert admin["can_manage"] is True

    sub = client.get("/api/v1/models/t", headers=base["hs"])
    assert sub.status_code == 200
    corpo = sub.json()
    assert [i["id"] for i in corpo["image_extras"]] == ["sub1"]
    assert corpo["can_manage"] is False and corpo["mine"] is False
    # o código do sub-admin é credencial: nada aqui o repete
    assert base["code"] not in sub.text
