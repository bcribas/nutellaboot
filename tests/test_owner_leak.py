"""O id do dono de um sub-admin é `invite:<CÓDIGO>`, e o código É a credencial
de console dele (invariante 18).

O teste antigo conferia só que a chave `invite` não existia no `image.json`.
O valor estava lá o tempo todo, em `owner`, e `GET /site-images/{img}` devolvia
o arquivo cru a quem tivesse o token da sede: o link do hotconfig entregava o
console do sub-admin. Aqui a conferência é pelo VALOR, em toda rota de leitura
que o token alcança.
"""

import pytest

from server.app import fsdb
from server.app.services import owners, ratelimit, store

MD5 = "0" * 32


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def lab(data_root, client, ha):
    # o pedido público tem limite por IP, e todo teste daqui cria uma sede
    ratelimit.reset()
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    client.post("/api/v1/models", json={"name": "oficial", "public": True}, headers=ha)
    client.post("/api/v1/models/oficial/layers", json={"file": "b.squashfs", "md5": MD5}, headers=ha)
    code = client.post(
        "/api/v1/invites", json={"max_images": 3, "count": 1, "label": "Lab da Camila"}, headers=ha
    ).json()["invites"][0]["code"]
    criada = client.post(
        "/api/v1/public/site-images",
        json={"code": code, "id": "meulab", "fullname": "Meu Lab", "model": "oficial"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    ).json()
    return {"code": code, "token": criada["token"]}


def _rotas_get_da_imagem(client):
    rotas = []
    for caminho, metodos in client.app.openapi()["paths"].items():
        if "get" not in metodos or not caminho.startswith("/api/v1/site-images/{image}"):
            continue
        if "{" in caminho.replace("{image}", ""):
            continue  # pedem mac, arquivo, id: não há o que ler numa sede vazia
        rotas.append(caminho.replace("{image}", "meulab"))
    return rotas


def test_o_token_da_sede_nunca_le_o_codigo_do_convite(client, lab):
    assert store.site_image_owner("meulab") == owners.owner_id(lab["code"])
    ht = {"Authorization": f"Bearer {lab['token']}"}
    rotas = _rotas_get_da_imagem(client)
    assert "/api/v1/site-images/meulab" in rotas
    for rota in rotas:
        r = client.get(rota, headers=ht)
        assert lab["code"] not in r.text, f"{rota} entregou o código do convite ao token da sede"


def test_o_token_recebe_o_rotulo_do_dono_e_nao_o_dono(client, lab):
    corpo = client.get(
        "/api/v1/site-images/meulab", headers={"Authorization": f"Bearer {lab['token']}"}
    ).json()
    assert "owner" not in corpo
    assert corpo["owner_kind"] == "subadmin"
    assert corpo["owner_label"] == "Lab da Camila"
    assert lab["code"] not in corpo["owner_ref"]


def test_admin_e_o_proprio_dono_continuam_vendo_o_dono(client, lab, ha):
    dono = owners.owner_id(lab["code"])
    assert client.get("/api/v1/site-images/meulab", headers=ha).json()["owner"] == dono
    hs = {"Authorization": f"Bearer {lab['code']}"}
    assert client.get("/api/v1/site-images/meulab", headers=hs).json()["owner"] == dono


def test_modelo_publico_de_outro_sub_admin_nao_entrega_o_codigo_dele(client, lab, ha):
    hs = {"Authorization": f"Bearer {lab['code']}"}
    assert client.post("/api/v1/models", json={"name": "dacamila"}, headers=hs).status_code in (200, 201)
    client.patch("/api/v1/models/dacamila", json={"public": True}, headers=ha)

    outro = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    ho = {"Authorization": f"Bearer {outro}"}
    lista = client.get("/api/v1/models", headers=ho)
    um = client.get("/api/v1/models/dacamila", headers=ho)
    assert um.status_code == 200
    for r in (lista, um):
        assert lab["code"] not in r.text
    assert um.json()["owner_label"] == "Lab da Camila"
    # e a dona continua se reconhecendo
    meu = next(m for m in client.get("/api/v1/models", headers=hs).json()["models"] if m["name"] == "dacamila")
    assert meu["mine"] and meu["owner"] == owners.owner_id(lab["code"])


def test_convite_revogado_nao_cria_imagem(client, lab, ha):
    """`revoked` fechava só o console; a criação seguia aberta."""
    from server.app.services import invites

    invites.set_fields(lab["code"], {"revoked": True})
    r = client.post(
        "/api/v1/public/site-images",
        json={"code": lab["code"], "id": "outrolab", "fullname": "Outro", "model": "oficial"},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert r.status_code in (400, 403), r.text
    assert not store.site_image_exists("outrolab")


def test_o_hash_da_senha_de_root_do_modelo_nao_sai_pela_api(client, lab, ha):
    """O padrão do ROOT_PASSWORD é guardado como `default_hash` (`$6$…`) no
    esquema do modelo, e o configureitor recebia o esquema cru: o token da sede
    levava o hash da senha de root da organização, quebrável offline. Mesmo
    funil de antes, mesma conferência pelo valor."""
    r = client.patch(
        "/api/v1/models/oficial/schema/fields/ROOT_PASSWORD",
        json={"default": "da-organizacao", "locked": True},
        headers=ha,
    )
    assert r.status_code == 200, r.text
    campo = next(f for f in store.get_schema("oficial")["fields"] if f["key"] == "ROOT_PASSWORD")
    segredo = campo["default_hash"]
    assert segredo.startswith("$6$")

    ht = {"Authorization": f"Bearer {lab['token']}"}
    hs = {"Authorization": f"Bearer {lab['code']}"}
    respostas = [client.get(rota, headers=ht) for rota in _rotas_get_da_imagem(client)]
    respostas += [
        client.get("/api/v1/models/oficial", headers=hs),
        client.get("/api/v1/models/oficial/schema", headers=hs),
        client.get("/api/v1/models/oficial", headers=ha),
        # o derivado copia o formulário, e com ele o hash
        client.post("/api/v1/models/oficial/duplicate", json={"name": "copia"}, headers=hs),
        client.get("/api/v1/models/copia", headers=hs),
    ]
    for r in respostas[-5:]:
        assert r.status_code < 400, (r.request.url, r.text)
    for r in respostas:
        assert segredo not in r.text and "default_hash" not in r.text, f"{r.request.url} entregou o hash de root"

    # quem olha ainda sabe que há um padrão definido
    config = client.get("/api/v1/site-images/meulab/config", headers=ht).json()
    root = next(f for f in config["schema"]["fields"] if f["key"] == "ROOT_PASSWORD")
    assert root["has_default"] is True
    # e o stuff, que é quem precisa dele, continua recebendo
    from server.app.services import stuffgen

    assert f"NB_ROOT_PW_HASH='{segredo}'" in stuffgen.render("meulab")
