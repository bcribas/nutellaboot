"""Modelos criáveis pela API: criar, derivar, montar camadas, apagar."""

import pytest

from server.app import fsdb
from server.app.services import store
from server.app.services.default_schema import build_default_schema

MD5 = "0" * 32
MD5B = "1" * 32


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def base(data_root, admin_key):
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    return admin_key


def _camada(client, ha, modelo, file, md5=MD5, **kw):
    return client.post(
        f"/api/v1/models/{modelo}/layers",
        json={"file": file, "md5": md5, **kw},
        headers=ha,
    )


# --- criação ---


def test_cria_modelo_do_zero_com_formulario_padrao(client, base, ha):
    r = client.post(
        "/api/v1/models", json={"name": "meumodelo", "description": "para o meu lab"}, headers=ha
    )
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["name"] == "meumodelo"
    assert corpo["owner"] == "admin"
    assert corpo["layers"] == []
    # sem camada nenhuma a imagem derivada não boota; o aviso existe para a
    # tela não deixar isso passar em branco
    assert "warning" in corpo

    campos = {f["key"] for f in corpo["schema"]["fields"]}
    assert {f["key"] for f in build_default_schema()["fields"]} == campos


def test_modelo_novo_ja_aparece_para_derivar_site_image(client, base, ha):
    client.post("/api/v1/models", json={"name": "meumodelo"}, headers=ha)
    _camada(client, ha, "meumodelo", "base.squashfs")
    r = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "Sala 1", "model": "meumodelo"},
        headers=ha,
    )
    assert r.status_code == 201, r.text
    assert r.json()["model"] == "meumodelo"


@pytest.mark.parametrize(
    "nome",
    ["../../keys", "MAIUSCULA", "a", "com espaco", "x" * 60, "-comeco", ""],
)
def test_nome_invalido_recusado(client, base, ha, nome):
    r = client.post("/api/v1/models", json={"name": nome}, headers=ha)
    assert r.status_code == 400
    assert not (store.model_dir(nome)).exists()


def test_nome_duplicado_recusado(client, base, ha):
    client.post("/api/v1/models", json={"name": "dup"}, headers=ha)
    r = client.post("/api/v1/models", json={"name": "dup"}, headers=ha)
    assert r.status_code == 400
    assert "já existe" in r.json()["detail"]


# --- derivar de outro modelo ---


def test_duplicar_copia_camadas_e_cadeados(client, base, ha):
    client.post("/api/v1/models", json={"name": "origem"}, headers=ha)
    _camada(client, ha, "origem", "telemetria.squashfs", MD5)
    _camada(client, ha, "origem", "wifi.squashfs", MD5B, position=1)
    client.put(
        "/api/v1/models/origem/schema/locks", json={"locks": {"TIMEZONE": True}}, headers=ha
    )

    r = client.post("/api/v1/models/origem/duplicate", json={"name": "copia"}, headers=ha)
    assert r.status_code == 201, r.text
    copia = r.json()
    assert [c["file"] for c in copia["layers"]] == ["telemetria.squashfs", "wifi.squashfs"]
    assert copia["derived_from"] == "origem"
    travados = {f["key"] for f in copia["schema"]["fields"] if f.get("locked")}
    assert "TIMEZONE" in travados
    # com camadas herdadas, não há aviso de modelo vazio
    assert "warning" not in copia


def test_duplicar_nao_liga_os_dois(client, base, ha):
    """Editar a cópia não pode mexer na origem — senão trocar o wifi de um lab
    mudaria o de todos os que derivaram dele."""
    client.post("/api/v1/models", json={"name": "origem"}, headers=ha)
    _camada(client, ha, "origem", "base.squashfs")
    client.post("/api/v1/models/origem/duplicate", json={"name": "copia"}, headers=ha)
    _camada(client, ha, "copia", "extra.squashfs", MD5B)

    origem = client.get("/api/v1/models/origem", headers=ha).json()
    assert [c["file"] for c in origem["layers"]] == ["base.squashfs"]


def test_duplicar_de_modelo_inexistente(client, base, ha):
    r = client.post("/api/v1/models/naoexiste/duplicate", json={"name": "x"}, headers=ha)
    assert r.status_code == 404


# --- camadas ---


def test_camada_entra_na_frente_por_padrao(client, base, ha):
    """Posição 0 é a que ganha no overlay; é o padrão porque a camada nova é
    quase sempre a personalização que deve sobrepor a base."""
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    _camada(client, ha, "mod", "base.squashfs", MD5)
    r = _camada(client, ha, "mod", "extra.squashfs", MD5B)
    assert [c["file"] for c in r.json()["layers"]] == ["extra.squashfs", "base.squashfs"]


def test_reordenar_camadas(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    _camada(client, ha, "mod", "a.squashfs", MD5)
    _camada(client, ha, "mod", "b.squashfs", MD5B)
    r = client.put(
        "/api/v1/models/mod/layers/order",
        json={"files": ["a.squashfs", "b.squashfs"]},
        headers=ha,
    )
    assert [c["file"] for c in r.json()["layers"]] == ["a.squashfs", "b.squashfs"]


def test_reordenar_nao_perde_camada_esquecida(client, base, ha):
    """Quem manda uma lista incompleta não pode apagar o resto sem querer."""
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    _camada(client, ha, "mod", "a.squashfs", MD5)
    _camada(client, ha, "mod", "b.squashfs", MD5B)
    r = client.put("/api/v1/models/mod/layers/order", json={"files": ["b.squashfs"]}, headers=ha)
    assert {c["file"] for c in r.json()["layers"]} == {"a.squashfs", "b.squashfs"}


def test_remover_camada(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    _camada(client, ha, "mod", "a.squashfs", MD5)
    _camada(client, ha, "mod", "b.squashfs", MD5B)
    r = client.delete("/api/v1/models/mod/layers/a.squashfs", headers=ha)
    assert [c["file"] for c in r.json()["layers"]] == ["b.squashfs"]


def test_camada_com_md5_invalido_recusada(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    r = _camada(client, ha, "mod", "a.squashfs", md5="nao-e-md5")
    assert r.status_code == 400


def test_camada_com_nome_de_arquivo_perigoso_recusada(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    r = _camada(client, ha, "mod", "../../etc/passwd")
    assert r.status_code == 400


def test_ordem_das_camadas_chega_no_manifest(client, base, ha):
    """O manifest é o contrato de boot: a ordem que o admin montou no modelo é
    a ordem do lowerdir do overlayfs."""
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    _camada(client, ha, "mod", "base.squashfs", MD5)
    _camada(client, ha, "mod", "pacotes.squashfs", MD5B)
    criada = client.post(
        "/api/v1/site-images", json={"id": "sala1", "fullname": "S", "model": "mod"}, headers=ha
    ).json()

    r = client.get(
        "/boot/v3/sala1/manifest", headers={"X-NB-Boot-Key": criada["boot_key"]}
    )
    assert r.status_code == 200, r.text
    arquivos = [ln.split()[1] for ln in r.text.strip().splitlines() if ln.strip()]
    assert arquivos == ["pacotes.squashfs", "base.squashfs"]


def test_catalogo_de_camadas_lista_o_que_ja_existe(client, base, ha):
    """É de onde a tela oferece 'telemetria' e 'wifi' ao montar um modelo."""
    client.post("/api/v1/models", json={"name": "m1"}, headers=ha)
    client.post("/api/v1/models", json={"name": "m2"}, headers=ha)
    _camada(client, ha, "m1", "telemetria.squashfs", MD5)
    _camada(client, ha, "m2", "telemetria.squashfs", MD5)
    _camada(client, ha, "m2", "wifi.squashfs", MD5B)

    r = client.get("/api/v1/layers/catalog", headers=ha)
    assert r.status_code == 200
    por_arquivo = {c["file"]: c for c in r.json()["layers"]}
    assert set(por_arquivo) == {"telemetria.squashfs", "wifi.squashfs"}
    assert sorted(por_arquivo["telemetria.squashfs"]["used_by"]) == ["m1", "m2"]


# --- formulário ---


def test_ajusta_padrao_de_campo(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    r = client.patch(
        "/api/v1/models/mod/schema/fields/TIMEZONE",
        json={"default": "America/Santiago", "locked": True},
        headers=ha,
    )
    assert r.status_code == 200
    campo = next(f for f in r.json()["fields"] if f["key"] == "TIMEZONE")
    assert campo["default"] == "America/Santiago"
    assert campo["locked"] is True


def test_campo_inexistente_recusado(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    r = client.patch("/api/v1/models/mod/schema/fields/NAO_EXISTE", json={"default": 1}, headers=ha)
    assert r.status_code == 400


def test_rotulo_exige_os_tres_idiomas(client, base, ha):
    """Interface trilíngue é invariante: aceitar só pt deixaria a tela em
    branco para quem está em en ou es."""
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    r = client.patch(
        "/api/v1/models/mod/schema/fields/TIMEZONE",
        json={"label": {"pt": "Fuso"}},
        headers=ha,
    )
    assert r.status_code == 400
    assert "idiomas" in r.json()["detail"]


# --- remoção ---


def test_apagar_modelo_em_uso_recusado(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    _camada(client, ha, "mod", "base.squashfs")
    client.post(
        "/api/v1/site-images", json={"id": "sala1", "fullname": "S", "model": "mod"}, headers=ha
    )
    r = client.delete("/api/v1/models/mod", headers=ha)
    assert r.status_code == 409
    assert "sala1" in r.json()["detail"]
    assert store.model_exists("mod")


def test_apagar_modelo_livre(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod"}, headers=ha)
    assert client.delete("/api/v1/models/mod", headers=ha).status_code == 204
    assert not store.model_exists("mod")


def test_apagar_modelo_inexistente(client, base, ha):
    assert client.delete("/api/v1/models/naoexiste", headers=ha).status_code == 404


# --- listagem ---


def test_listagem_traz_o_que_a_tela_precisa(client, base, ha):
    client.post("/api/v1/models", json={"name": "mod", "description": "d"}, headers=ha)
    _camada(client, ha, "mod", "base.squashfs")
    client.post(
        "/api/v1/site-images", json={"id": "sala1", "fullname": "S", "model": "mod"}, headers=ha
    )
    r = client.get("/api/v1/models", headers=ha)
    assert r.status_code == 200
    m = next(x for x in r.json()["models"] if x["name"] == "mod")
    assert m["layers"] == 1
    assert m["used_by"] == 1
    assert m["can_manage"] is True
    assert m["description"] == "d"


def test_sem_credencial_nao_lista(client, base):
    assert client.get("/api/v1/models").status_code == 401
    assert client.post("/api/v1/models", json={"name": "x"}).status_code == 401
