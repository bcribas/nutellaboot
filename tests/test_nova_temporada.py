"""O comando de temporada: modelo novo herdando o anterior, base trocada.

É também o único caminho que registra um `.squash` que já foi gerado — o
`nb3-gerar-squash` só sabe registrar dentro da mesma execução, e repetir a
geração custa meia hora de mksquashfs sobre dezenas de GB.
"""

import subprocess
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FERRAMENTA = REPO / "tools" / "nb3-nova-temporada"
MD5_VAZIO_1MB = "b6d81b360a5672d80c27430f39153e2c"  # md5 de 1 MiB de zeros


@pytest.fixture
def servidor(data_root, admin_key):
    """Sobe um uvicorn de verdade: a ferramenta fala HTTP, não importa o app."""
    import os
    import socket
    import time

    porta = socket.socket()
    porta.bind(("127.0.0.1", 0))
    _, p = porta.getsockname()
    porta.close()

    env = {**os.environ, "NB3_DATA_ROOT": str(data_root), "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen(
        [".venv/bin/python", "-m", "uvicorn", "server.app.main:app",
         "--host", "127.0.0.1", "--port", str(p), "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{p}"
    import urllib.request

    for _ in range(80):
        try:
            urllib.request.urlopen(f"{base}/api/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("uvicorn nao subiu")
    yield base, admin_key
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def base_squash(tmp_path):
    """Um 'squash' de mentira, mas com tamanho e md5 de verdade."""
    p = tmp_path / "maratonalinux2026.squash-2026-08-02"
    p.write_bytes(b"\0" * (1024 * 1024))
    return p


def rodar(servidor, *args, esperar_ok=True):
    base, chave = servidor
    r = subprocess.run(
        [".venv/bin/python", str(FERRAMENTA), "--server", base, "--admin-key", chave, *args],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    if esperar_ok:
        assert r.returncode == 0, r.stderr or r.stdout
    return r


def api(servidor, caminho):
    import json
    import urllib.request

    base, chave = servidor
    req = urllib.request.Request(f"{base}{caminho}")
    req.add_header("Authorization", f"Bearer {chave}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


@pytest.fixture
def anterior(servidor, data_root):
    """O modelo do ano passado, no formato real: extras na frente, base no fim."""
    from server.app import fsdb
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data_root / "server.json", {"reserved_prefix_regex": "^[0-9]"})
    esquema = build_default_schema()
    for campo in esquema["fields"]:
        campo["locked"] = campo["key"] in ("MINRAM", "ALLOWUSBMOUNT")
    fsdb.write_json(data_root / "models" / "ano2025" / "schema.json", esquema)
    fsdb.write_json(
        data_root / "models" / "ano2025" / "model.json",
        {
            "name": "ano2025",
            "owner": "admin",
            "layers": [
                {"file": "telemetria-2025.squash", "md5": "a" * 32, "role": "telemetry"},
                {"file": "wifis.squash", "md5": "b" * 32, "role": "wifi"},
                {"file": "icpc-latam2025.squash-2025", "md5": "c" * 32, "role": "base"},
            ],
        },
    )
    return "ano2025"


# --- o caminho normal ---


def test_cria_a_temporada_herdando_e_trocando_a_base(servidor, anterior, base_squash):
    r = rodar(servidor, "--de", "ano2025", "--para", "ano2026", "--base", str(base_squash))
    camadas = api(servidor, "/api/v1/models/ano2026")["layers"]

    assert [c["role"] for c in camadas] == ["telemetry", "wifi", "base"]
    assert camadas[-1]["file"] == base_squash.name
    assert camadas[-1]["md5"] == MD5_VAZIO_1MB
    # a base do ano passado saiu
    assert not any(c["file"].startswith("icpc-latam2025") for c in camadas)
    assert "ano2026" in r.stdout


def test_os_cadeados_do_formulario_sao_herdados(servidor, anterior, base_squash):
    """É o que separa uma imagem Oficial de uma Livre; refazer à mão é onde se
    erra."""
    rodar(servidor, "--de", "ano2025", "--para", "ano2026", "--base", str(base_squash))
    campos = api(servidor, "/api/v1/models/ano2026/schema")["fields"]
    travados = {c["key"] for c in campos if c["locked"]}
    assert "MINRAM" in travados and "ALLOWUSBMOUNT" in travados


def test_o_modelo_anterior_nao_e_tocado(servidor, anterior, base_squash):
    """As sedes que usam a temporada passada seguem bootando o que bootam."""
    antes = api(servidor, "/api/v1/models/ano2025")["layers"]
    rodar(servidor, "--de", "ano2025", "--para", "ano2026", "--base", str(base_squash))
    assert api(servidor, "/api/v1/models/ano2025")["layers"] == antes


def test_dry_run_nao_cria_nada(servidor, anterior, base_squash):
    r = rodar(servidor, "--de", "ano2025", "--para", "ano2026",
              "--base", str(base_squash), "--dry-run")
    assert "dry-run" in r.stdout
    nomes = {m["name"] for m in api(servidor, "/api/v1/models")["models"]}
    assert "ano2026" not in nomes


# --- os casos que apareceram no uso real ---


def test_modelo_vazio_e_preenchido_em_vez_de_so_ganhar_a_base(servidor, anterior, base_squash):
    """Um modelo criado e nunca preenchido é o resultado mais comum de um
    registro que falhou calado. Trocar 'a base' dele deixaria a temporada sem
    telemetria nem wifi."""
    rodar(servidor, "--de", "ano2025", "--para", "vazio2026", "--base", str(base_squash),
          "--dry-run")  # garante que nao existe ainda
    import json
    import urllib.request

    base, chave = servidor
    req = urllib.request.Request(
        f"{base}/api/v1/models",
        data=json.dumps({"name": "vazio2026"}).encode(),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {chave}")
    req.add_header("Content-Type", "application/json")
    urllib.request.urlopen(req, timeout=15)
    assert api(servidor, "/api/v1/models/vazio2026")["layers"] == []

    r = rodar(servidor, "--de", "ano2025", "--para", "vazio2026", "--base", str(base_squash))
    assert "VAZIO" in r.stdout
    camadas = api(servidor, "/api/v1/models/vazio2026")["layers"]
    assert [c["role"] for c in camadas] == ["telemetry", "wifi", "base"]


def test_rodar_duas_vezes_nao_empilha_bases(servidor, anterior, base_squash, tmp_path):
    """Regerar a base e registrar de novo tem que continuar com UMA base — foi
    o bug que motivou o papel da camada."""
    rodar(servidor, "--de", "ano2025", "--para", "ano2026", "--base", str(base_squash))
    outra = tmp_path / "maratonalinux2026.squash-2026-08-03"
    outra.write_bytes(b"\1" * (1024 * 1024))
    rodar(servidor, "--de", "ano2025", "--para", "ano2026", "--base", str(outra))

    camadas = api(servidor, "/api/v1/models/ano2026")["layers"]
    bases = [c for c in camadas if c["role"] == "base"]
    assert len(bases) == 1, [c["file"] for c in camadas]
    assert bases[0]["file"] == outra.name
    assert camadas[-1]["role"] == "base", "a base tem que continuar por ultimo"


def test_primeira_temporada_sem_modelo_anterior(servidor, data_root, base_squash):
    from server.app import fsdb

    fsdb.write_json(data_root / "server.json", {})
    r = rodar(servidor, "--para", "primeira", "--base", str(base_squash))
    camadas = api(servidor, "/api/v1/models/primeira")["layers"]
    assert [c["role"] for c in camadas] == ["base"]
    assert "nb3-camada-telemetria" in FERRAMENTA.read_text(), (
        "o texto tem que apontar como acrescentar a telemetria depois"
    )
    del r


# --- erros que precisam aparecer alto ---


def test_arquivo_inexistente_falha(servidor, anterior):
    r = rodar(servidor, "--de", "ano2025", "--para", "ano2026",
              "--base", "/nao/existe.squash", esperar_ok=False)
    assert r.returncode != 0
    assert "nao existe" in (r.stderr + r.stdout)


def test_modelo_de_origem_inexistente_falha_dizendo_quais_existem(servidor, anterior, base_squash):
    """Errar o nome do modelo foi exatamente como dois modelos ficaram
    vazios — o erro tem que ser alto e dizer o que existe."""
    r = rodar(servidor, "--de", "naoexiste", "--para", "ano2026",
              "--base", str(base_squash), esperar_ok=False)
    assert r.returncode != 0
    saida = r.stderr + r.stdout
    assert "naoexiste" in saida
    assert "ano2025" in saida, "tem que listar os modelos que existem"


def test_chave_errada_falha_alto(servidor, anterior, base_squash):
    base, _ = servidor
    r = subprocess.run(
        [".venv/bin/python", str(FERRAMENTA), "--server", base, "--admin-key", "nb3a_errada",
         "--de", "ano2025", "--para", "ano2026", "--base", str(base_squash)],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode != 0, "credencial errada nao pode terminar com sucesso"
    assert "401" in (r.stderr + r.stdout)


def test_gerar_squash_nao_engole_erro_de_http():
    """O `curl -sS` sem --fail devolvia código 0 num 404: o script dizia que
    registrou sem ter registrado nada, e dois modelos ficaram vazios."""
    texto = (REPO / "tools" / "nb3-gerar-squash").read_text()
    assert "--fail-with-body" in texto
    assert "curl -sS \"$SERVIDOR" not in texto, "sobrou curl sem verificacao de status"


def test_modelo_com_camada_sem_papel_e_recusado(servidor, data_root, base_squash):
    """O caso que o importador do nb2 produzia: camadas gravadas direto em
    disco, sem papel. `replace_role` não as reconhece, a base velha fica, e a
    trava que conta bases acha 1 porque a antiga nem entra na conta — modelo
    com duas raízes e nenhum erro em lugar nenhum."""
    from server.app import fsdb

    fsdb.write_json(
        data_root / "models" / "importado" / "model.json",
        {
            "name": "importado",
            "owner": "admin",
            # sem `role`, como o nb2 gravava
            "layers": [
                {"file": "log23.squash", "md5": "a" * 32},
                {"file": "maratonalinux2404.squash", "md5": "c" * 32},
            ],
        },
    )
    r = rodar(
        servidor, "--para", "importado", "--base", str(base_squash), esperar_ok=False
    )
    assert r.returncode != 0
    assert "nao tem papel" in r.stderr
    assert "nb3-migrate-roles" in r.stderr
    # e nada foi tocado: a base velha continua lá, sozinha
    camadas = api(servidor, "/api/v1/models/importado")["layers"]
    assert [c["file"] for c in camadas] == ["log23.squash", "maratonalinux2404.squash"]


def test_depois_do_migrate_roles_a_temporada_passa(servidor, data_root, base_squash):
    """A saída do erro acima tem que ser um caminho, não um beco."""
    from server.app import fsdb

    fsdb.write_json(
        data_root / "models" / "importado" / "model.json",
        {
            "name": "importado",
            "owner": "admin",
            "layers": [
                {"file": "log23.squash", "md5": "a" * 32},
                {"file": "maratonalinux2404.squash", "md5": "c" * 32},
            ],
        },
    )
    m = subprocess.run(
        [".venv/bin/python", str(REPO / "tools" / "nb3-migrate-roles"), "--data", str(data_root)],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    assert m.returncode == 0, m.stderr
    rodar(servidor, "--para", "importado", "--base", str(base_squash))
    camadas = api(servidor, "/api/v1/models/importado")["layers"]
    assert [c["role"] for c in camadas] == ["telemetry", "base"]
    assert camadas[-1]["file"] == base_squash.name


def test_pack_upper_nao_engole_erro_de_http():
    """Mesmo bug do gerar-squash, no `--attach`: nome de imagem errado ou
    chave vencida saíam com código 0, dizendo que anexou. Passou despercebido
    porque a guarda acima só olhava um arquivo."""
    texto = (REPO / "tools" / "nb3-pack-upper").read_text()
    assert "--fail-with-body" in texto
    assert "curl -sS -X POST" not in texto, "sobrou curl sem verificacao de status"


def test_genusb_confere_a_publicacao():
    """`publish_file()` nunca levanta exceção (falha vira status: failed): sem
    conferir o status, SSH fora do ar terminava com "pronto:"."""
    texto = (REPO / "tools" / "nb3-genusb").read_text()
    assert "sys.exit" in texto and "!= 'done'" in texto


def test_genusb_nao_tem_servidor_padrao_de_producao():
    """As irmãs apontam para o ambiente de teste; esta apontava para produção,
    e pendrive gravado com a chave do servidor errado some pela sala."""
    texto = (REPO / "tools" / "nb3-genusb").read_text()
    assert "https://nutellaboot.naquadah.com.br" not in texto


def test_gerar_squash_registra_como_base_e_substitui():
    texto = (REPO / "tools" / "nb3-gerar-squash").read_text()
    assert '"role": "base"' in texto
    assert '"replace_role": "base"' in texto
    assert "PUT" not in texto, "o PUT substituia a lista inteira a partir de uma leitura antiga"
