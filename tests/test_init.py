"""Instalar do zero, sem trancar ninguém para fora.

O comando de dados de teste gravava o hash da chave de administração, seguia
para o próximo passo e estourava ali — antes de imprimir a chave. Em disco fica
só o hash: a chave em claro se perdia, e rodar de novo não adiantava porque o
arquivo já existia. Numa máquina nova, tranca permanente.

Além disso ele exigia, em silêncio, um checkout do NutellaBoot 2 ao lado: sem
ele o modelo nunca era escrito e a criação da imagem de teste morria com um
traceback.

Agora são dois comandos: `nb3-init` prepara o servidor e imprime a chave ANTES
de qualquer passo que possa falhar; `nb3-seed-testdata` é só dado de teste, e
funciona com ou sem o nb2.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "tools" / "nb3-init"
SEED = REPO / "tools" / "nb3-seed-testdata"
CHAVE_RE = re.compile(r"nb3a_[0-9a-f]{32}")


def rodar(ferramenta, raiz, *args):
    import os

    return subprocess.run(
        [".venv/bin/python", str(ferramenta), *args],
        cwd=REPO,
        env={**os.environ, "NB3_DATA_ROOT": str(raiz)},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def raiz(tmp_path):
    return tmp_path / "data"


def test_instalacao_do_zero_imprime_a_chave(raiz):
    r = rodar(INIT, raiz)
    assert r.returncode == 0, r.stderr
    achadas = CHAVE_RE.findall(r.stdout)
    assert len(achadas) == 1, r.stdout
    assert (raiz / "keys" / "admin.json").is_file()
    assert (raiz / "server.json").is_file()


def test_a_chave_impressa_e_a_que_vale(raiz, monkeypatch):
    """Não adianta imprimir uma chave que o servidor não reconhece."""
    chave = CHAVE_RE.search(rodar(INIT, raiz).stdout).group(0)

    from server.app import auth, fsdb

    guardado = fsdb.read_json(raiz / "keys" / "admin.json", {})
    assert guardado["keys"][0]["sha256"] == auth.key_hash(chave)
    # e a chave em claro não ficou em lugar nenhum do disco
    for f in raiz.rglob("*"):
        if f.is_file():
            assert chave not in f.read_text(errors="ignore"), f


def test_rodar_de_novo_nao_emite_outra(raiz):
    primeira = CHAVE_RE.search(rodar(INIT, raiz).stdout).group(0)
    r = rodar(INIT, raiz)
    assert r.returncode == 0
    assert not CHAVE_RE.findall(r.stdout)
    assert "ja existe" in r.stdout

    from server.app import fsdb

    assert len(fsdb.read_json(raiz / "keys" / "admin.json", {})["keys"]) == 1
    assert primeira  # a original continua sendo a única


def test_nova_chave_nao_derruba_a_anterior(raiz):
    """Trocar de máquina não pode significar perder o acesso da que já está
    funcionando."""
    rodar(INIT, raiz)
    r = rodar(INIT, raiz, "--nova-chave", "--id", "bruno")
    assert r.returncode == 0
    assert len(CHAVE_RE.findall(r.stdout)) == 1

    from server.app import fsdb

    chaves = fsdb.read_json(raiz / "keys" / "admin.json", {})["keys"]
    assert [k["id"] for k in chaves] == ["admin", "bruno"]


def test_o_arquivo_de_chaves_e_privado(raiz):
    rodar(INIT, raiz)
    assert (raiz / "keys" / "admin.json").stat().st_mode & 0o777 == 0o600


# --- os dados de teste ---


def test_seed_funciona_sem_o_nutellaboot2(raiz):
    """Era exatamente aqui que estourava, depois de já ter gravado a chave."""
    rodar(INIT, raiz)
    r = rodar(SEED, raiz, "--nb2", "/nao-existe")
    assert r.returncode == 0, r.stderr
    assert (raiz / "models" / "maratonalinux2404" / "model.json").is_file()
    assert (raiz / "models" / "maratonalinux2404" / "schema.json").is_file()
    assert (raiz / "site-images" / "testes3" / "boot.key").is_file()
    assert "nb3i_" in r.stdout  # as credenciais da imagem saíram


def test_seed_sem_chave_manda_rodar_o_init(raiz):
    """Em vez de gravar um hash órfão e estourar depois."""
    r = rodar(SEED, raiz, "--nb2", "/nao-existe")
    assert r.returncode != 0
    assert "nb3-init" in r.stderr
    assert not (raiz / "keys" / "admin.json").exists()


def test_seed_e_idempotente(raiz):
    rodar(INIT, raiz)
    rodar(SEED, raiz, "--nb2", "/nao-existe")
    r = rodar(SEED, raiz, "--nb2", "/nao-existe")
    assert r.returncode == 0
    assert "nada a fazer" in r.stdout


def test_camadas_importadas_nascem_com_papel(raiz, tmp_path):
    """Camada sem papel faz a troca de base da temporada seguinte errar o alvo
    e empilhar duas raízes, em silêncio."""
    nb2 = tmp_path / "nb2" / "maratonalinux2404"
    nb2.mkdir(parents=True)
    (nb2 / "template").write_text(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa log23.squash https://x/log23.squash\n"
        "cccccccccccccccccccccccccccccccc base2404.squash https://x/base2404.squash\n"
    )
    rodar(INIT, raiz)
    r = rodar(SEED, raiz, "--nb2", str(tmp_path / "nb2"))
    assert r.returncode == 0, r.stderr

    from server.app import fsdb

    camadas = fsdb.read_json(raiz / "models" / "maratonalinux2404" / "model.json", {})["layers"]
    assert [c["role"] for c in camadas] == ["telemetry", "base"]
