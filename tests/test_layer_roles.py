"""O papel de cada camada, e trocar a base entre temporadas.

O nome do arquivo da base muda todo ano (icpc-latam2025 → maratonalinux2026).
Enquanto a troca casava por nome, registrar a base nova deixava as duas no
modelo: a máquina baixava 13 GB e montava duas raízes sobrepostas, sem erro
nenhum — nem no registro, nem no manifest, nem no boot. Marcar o papel é o que
faz a troca acertar a camada certa.
"""

import subprocess
from pathlib import Path

import pytest

from server.app import fsdb
from server.app.services import store

REPO = Path(__file__).resolve().parents[1]
MIGRACAO = REPO / "tools" / "nb3-migrate-roles"

MD5_BASE = "a" * 32
MD5_NOVA = "b" * 32
MD5_TELE = "c" * 32


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def modelo(client, data_root, ha):
    """Um modelo no formato real: extras na frente, base por último."""
    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    client.post("/api/v1/models", json={"name": "temporada"}, headers=ha)
    for camada in (
        {"file": "telemetria-2026.squash", "md5": MD5_TELE, "role": "telemetry"},
        {"file": "wifis.squash", "md5": "d" * 32, "role": "wifi"},
        {"file": "icpc-latam2025.squash-2025-08-01", "md5": MD5_BASE, "role": "base"},
    ):
        r = client.post(
            "/api/v1/models/temporada/layers",
            json={**camada, "position": 99},  # 99 = no fim
            headers=ha,
        )
        assert r.status_code == 200, r.text
    return "temporada"


def camadas(client, ha, nome="temporada"):
    return client.get(f"/api/v1/models/{nome}", headers=ha).json()["layers"]


# --- validação ---


def test_role_invalido_e_recusado(client, modelo, ha):
    """Errar o papel da base é o que empilha duas raízes; melhor recusar."""
    r = client.post(
        "/api/v1/models/temporada/layers",
        json={"file": "x.squash", "md5": MD5_NOVA, "role": "sistema"},
        headers=ha,
    )
    assert r.status_code == 400
    assert "role" in r.json()["detail"]


def test_sem_role_a_camada_e_extra(client, modelo, ha):
    r = client.post(
        "/api/v1/models/temporada/layers",
        json={"file": "novo.squash", "md5": MD5_NOVA},
        headers=ha,
    )
    assert r.json()["layers"][0]["role"] == "extra"


def test_replace_role_invalido_e_recusado(client, modelo, ha):
    r = client.post(
        "/api/v1/models/temporada/layers",
        json={"file": "x.squash", "md5": MD5_NOVA, "replace_role": "raiz"},
        headers=ha,
    )
    assert r.status_code == 400


# --- a regressão que motivou tudo ---


def test_trocar_a_base_com_nome_diferente_deixa_uma_so(client, modelo, ha):
    """O caso real: de icpc-latam2025 para maratonalinux2026. Sem o papel,
    ficavam as duas."""
    r = client.post(
        "/api/v1/models/temporada/layers",
        json={
            "file": "maratonalinux2026-24.04.4.squash-2026-08-02",
            "md5": MD5_NOVA,
            "role": "base",
            "replace_role": "base",
        },
        headers=ha,
    )
    assert r.status_code == 200, r.text

    atuais = r.json()["layers"]
    bases = [c for c in atuais if c["role"] == "base"]
    assert len(bases) == 1, [c["file"] for c in atuais]
    assert bases[0]["file"] == "maratonalinux2026-24.04.4.squash-2026-08-02"


def test_a_base_nova_fica_no_lugar_da_antiga(client, modelo, ha):
    """A ordem é a prioridade no overlay: a base tem que continuar por último,
    senão ela sobrescreve as personalizações em silêncio."""
    client.post(
        "/api/v1/models/temporada/layers",
        json={
            "file": "maratonalinux2026.squash-2026",
            "md5": MD5_NOVA,
            "role": "base",
            "replace_role": "base",
        },
        headers=ha,
    )
    atuais = camadas(client, ha)
    assert atuais[-1]["role"] == "base"
    assert [c["role"] for c in atuais] == ["telemetry", "wifi", "base"]


def test_trocar_a_base_nao_mexe_nas_outras(client, modelo, ha):
    antes = [c["file"] for c in camadas(client, ha) if c["role"] != "base"]
    client.post(
        "/api/v1/models/temporada/layers",
        json={"file": "nova.squash", "md5": MD5_NOVA, "role": "base", "replace_role": "base"},
        headers=ha,
    )
    depois = [c["file"] for c in camadas(client, ha) if c["role"] != "base"]
    assert antes == depois


def test_sem_replace_role_a_base_antiga_fica(client, modelo, ha):
    """Comportamento antigo, ainda disponível: quem não pedir a troca leva as
    duas — e é por isso que a ferramenta sempre pede."""
    client.post(
        "/api/v1/models/temporada/layers",
        json={"file": "nova.squash", "md5": MD5_NOVA, "role": "base", "position": 99},
        headers=ha,
    )
    assert len([c for c in camadas(client, ha) if c["role"] == "base"]) == 2


def test_a_ordem_do_modelo_chega_no_manifest(client, modelo, ha, data_root):
    """O contrato de boot: base por último no manifest."""
    fsdb.write_json(data_root / "models" / "temporada" / "schema.json", {"fields": []})
    client.post(
        "/api/v1/models/temporada/layers",
        json={"file": "base2026.squash", "md5": MD5_NOVA, "role": "base", "replace_role": "base"},
        headers=ha,
    )
    criada = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "S", "model": "temporada"},
        headers=ha,
    ).json()
    r = client.get("/boot/v3/sala1/manifest", headers={"X-NB-Boot-Key": criada["boot_key"]})
    arquivos = [ln.split()[1] for ln in r.text.strip().splitlines()]
    assert arquivos[-1] == "base2026.squash"
    assert "icpc-latam2025.squash-2025-08-01" not in arquivos


# --- o PUT, que descartava a normalização ---


def test_put_normaliza_as_camadas(client, modelo, ha):
    """O retorno de _camada_valida era descartado: as camadas iam para o disco
    como vieram, sem cdn_url padrão, sem size e sem role — enquanto o
    comentário da função prometia o contrário."""
    r = client.put(
        "/api/v1/models/temporada/layers",
        json={"layers": [{"file": "so-isso.squash", "md5": MD5_NOVA}]},
        headers=ha,
    )
    assert r.status_code == 200, r.text
    c = camadas(client, ha)[0]
    assert c["role"] == "extra"
    assert c["cdn_url"], "sem cdn_url a camada sai do manifest sem fonte"


def test_put_recusa_camada_invalida(client, modelo, ha):
    r = client.put(
        "/api/v1/models/temporada/layers",
        json={"layers": [{"file": "x.squash", "md5": "nao-e-md5"}]},
        headers=ha,
    )
    assert r.status_code == 400
    assert len(camadas(client, ha)) == 3, "o modelo nao pode ter sido tocado"


# --- a migração ---


def _migrar(data_root, *args):
    return subprocess.run(
        ["python3", str(MIGRACAO), "--data", str(data_root), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
    )


def test_migracao_deduz_os_papeis(data_root):
    fsdb.write_json(
        data_root / "models" / "antigo" / "model.json",
        {
            "layers": [
                {"file": "log23.squash", "md5": MD5_TELE},
                {"file": "firefox.squash", "md5": "e" * 32},
                {"file": "wifis.squash", "md5": "d" * 32},
                {"file": "icpc-latam2025.squash-2025", "md5": MD5_BASE},
            ]
        },
    )
    r = _migrar(data_root)
    assert r.returncode == 0, r.stderr
    papeis = [
        c["role"]
        for c in fsdb.read_json(data_root / "models" / "antigo" / "model.json")["layers"]
    ]
    assert papeis == ["telemetry", "extra", "wifi", "base"]


def test_migracao_dry_run_nao_grava(data_root):
    fsdb.write_json(
        data_root / "models" / "antigo" / "model.json",
        {"layers": [{"file": "base.squash", "md5": MD5_BASE}]},
    )
    r = _migrar(data_root, "--dry-run")
    assert "dry-run" in r.stdout
    camada = fsdb.read_json(data_root / "models" / "antigo" / "model.json")["layers"][0]
    assert "role" not in camada


def test_migracao_e_idempotente(data_root):
    fsdb.write_json(
        data_root / "models" / "antigo" / "model.json",
        {"layers": [{"file": "base.squash", "md5": MD5_BASE}]},
    )
    _migrar(data_root)
    r = _migrar(data_root)
    assert "nada a mudar" in r.stdout


def test_migracao_respeita_papel_ja_marcado(data_root):
    """Quem já marcou à mão (ou pela tela) não é sobrescrito pela dedução."""
    fsdb.write_json(
        data_root / "models" / "antigo" / "model.json",
        {"layers": [{"file": "qualquer.squash", "md5": MD5_BASE, "role": "wifi"}]},
    )
    _migrar(data_root)
    camada = fsdb.read_json(data_root / "models" / "antigo" / "model.json")["layers"][0]
    assert camada["role"] == "wifi", "a ultima da lista viraria base pela deducao"
