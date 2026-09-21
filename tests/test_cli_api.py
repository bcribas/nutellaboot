"""O cliente de referência, contra um servidor de verdade.

`tools/nb3-api` existe para ser copiado por quem integra. Testá-lo com um
cliente falso provaria só que duas cópias do meu palpite concordam — então aqui
sobe um uvicorn (o mesmo padrão de `tests/test_live_server.py`) e roda o
executável de verdade, com `subprocess`, como o MOJ rodaria.

O que estes testes prendem:

  * `bulk` devolve **as duas URLs** da sede. Era o pedido, e o CSV do servidor
    só trazia a do configureitor — quem criava 50 sedes ficava sem metade dos
    links, com a outra metade escondida no JSON;
  * erro do servidor sai com código != 0 E com o motivo. É a invariante 15:
    `curl -sS` sem `--fail` devolvia JSON de erro com código ZERO, e dois
    modelos ficaram vazios com o script dizendo que registrou;
  * o CLI não depende deste repositório — roda com o python do sistema, sem o
    venv, porque é isso que "copiável" quer dizer.
"""

import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from server.app import auth, fsdb  # noqa: E402

CLI = REPO / "tools" / "nb3-api"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    admin = auth.new_key("nb3a")
    fsdb.write_json(
        data / "keys" / "admin.json",
        {"keys": [{"id": "admin", "sha256": auth.key_hash(admin)}]},
    )
    fsdb.write_json(data / "models" / "t" / "model.json", {"layers": []})
    # sem esquema não há campo nenhum, e todo `config set` volta 400
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data / "models" / "t" / "schema.json", build_default_schema())

    port = free_port()
    env = {**os.environ, "NB3_DATA_ROOT": str(data), "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen(
        [
            str(REPO / ".venv" / "bin" / "uvicorn"),
            "server.app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("uvicorn não subiu: " + proc.stderr.read().decode()[-2000:])

    yield {"base": base, "admin": admin}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def roda(live, *args, key=None, entrada=None):
    """Roda o CLI com o python DO SISTEMA — ele não pode depender deste venv."""
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        input=entrada,
        env={
            **os.environ,
            "NB3_BASE_URL": live["base"],
            "NB3_API_KEY": live["admin"] if key is None else key,
        },
    )


def test_whoami(live):
    r = roda(live, "--json", "whoami")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["kind"] == "admin"


def test_bulk_devolve_as_duas_urls_da_sede(live, tmp_path):
    """São duas telas — configureitor e hotconfig — e o coordenador precisa das
    duas. Quem cria 50 sedes de uma vez não vai buscar a segunda de uma em
    uma."""
    tsv = tmp_path / "sedes.tsv"
    tsv.write_text("clisala1\tSala CLI 1\tt\nclisala2\tSala CLI 2\tt\n", encoding="utf-8")
    r = roda(live, "bulk", str(tsv))
    assert r.returncode == 0, r.stderr

    linhas = list(csv.DictReader(io.StringIO(r.stdout)))
    assert [l["id"] for l in linhas] == ["clisala1", "clisala2"]
    for l in linhas:
        assert l["ok"] in ("True", "true")
        assert l["token"].startswith("nb3i_")
        assert f"/configureitor/?id={l['id']}&tk={l['token']}" in l["configureitor_url"]
        assert f"/hotconfig/?id={l['id']}&tk={l['token']}" in l["hotconfig_url"]


def test_as_duas_urls_do_bulk_abrem_mesmo(live, tmp_path):
    """Link que não abre é pior que link ausente: o coordenador só descobre na
    véspera."""
    tsv = tmp_path / "s.tsv"
    tsv.write_text("cliabre\tAbre\tt\n", encoding="utf-8")
    linha = list(csv.DictReader(io.StringIO(roda(live, "bulk", str(tsv)).stdout)))[0]
    for url in (linha["configureitor_url"], linha["hotconfig_url"]):
        caminho = url.split("/", 3)[3]
        assert httpx.get(f"{live['base']}/{caminho}", timeout=5).status_code == 200, url


def test_ciclo_de_vida_de_uma_sede(live):
    assert roda(live, "images", "create", "clivida", "--fullname", "Vida", "--model", "t").returncode == 0

    r = roda(live, "--json", "images", "credentials", "clivida")
    cred = json.loads(r.stdout)
    assert cred["token"].startswith("nb3i_")
    assert cred["configureitor_url"] and cred["hotconfig_url"]

    assert roda(live, "config", "set", "clivida", '{"TIMEZONE":"America/Bahia"}').returncode == 0
    valores = json.loads(roda(live, "--json", "config", "get", "clivida").stdout)
    assert valores["values"]["TIMEZONE"] == "America/Bahia"

    # a chave da própria sede também serve: é o que a coordenação recebe
    r = roda(live, "--json", "machines", "clivida", key=cred["token"])
    assert r.returncode == 0, r.stderr

    assert roda(live, "images", "delete", "clivida").returncode == 0


def test_roster_e_vinculo(live):
    """O caminho do MOJ: manda os times, vincula a máquina ao time.

    `GET /bindings` percorre as máquinas CONHECIDAS (as que já reportaram), e
    não os vínculos gravados — então o vínculo de uma máquina que ainda não
    bootou existe mas não aparece na lista. Por isso a máquina reporta antes
    aqui, como reportaria na sala."""
    roda(live, "images", "create", "cliroster", "--model", "t")
    cred = json.loads(roda(live, "--json", "images", "credentials", "cliroster").stdout)

    times = json.dumps([{"user_id": "team-1", "name": "Os Batatinhas", "seat": "012"}])
    r = roda(live, "roster", "set", "cliroster", "-", entrada=times)
    assert r.returncode == 0, r.stderr
    assert "Batatinhas" in roda(live, "--json", "roster", "get", "cliroster").stdout

    mac = "52-54-00-12-34-56"
    httpx.post(
        f"{live['base']}/api/v1/site-images/cliroster/machines/{mac}/status",
        headers={"X-NB-Machine-Key": cred["machine_key"]},
        json={"sysresources": {"mem_pct": 10}},
        timeout=5,
    )

    r = roda(live, "bind", "cliroster", mac, "team-1", "--seat", "012")
    assert r.returncode == 0, r.stderr
    assert "team-1" in roda(live, "--json", "bindings", "cliroster").stdout

    assert roda(live, "unbind", "cliroster", mac).returncode == 0
    assert "team-1" not in roda(live, "--json", "bindings", "cliroster").stdout
    roda(live, "images", "delete", "cliroster")


def _maquina(live, image, chave, mac):
    r = httpx.post(
        f"{live['base']}/api/v1/site-images/{image}/machines/{mac}/status",
        headers={"X-NB-Machine-Key": chave},
        json={"sysresources": {"mem_pct": 10}},
        timeout=5,
    )
    assert r.status_code == 200, r.text


def _pendentes(live, image):
    r = httpx.get(
        f"{live['base']}/api/v1/site-images/{image}/machines",
        headers={"Authorization": f"Bearer {live['admin']}"},
        timeout=5,
    )
    return {m["mac"]: m["pending"] for m in r.json()["machines"]}


def test_command_atinge_so_as_maquinas_pedidas(live):
    """O CLI mandava as máquinas em `macs`, campo que o servidor nunca leu:
    sem `target` o padrão é a sala inteira, e `command <sede> mlpoweroff <mac>`
    desligava TODAS. O teste confere o efeito, não o corpo: é na fila de cada
    máquina que o erro aparece."""
    roda(live, "images", "create", "clicmd", "--model", "t")
    cred = json.loads(roda(live, "--json", "images", "credentials", "clicmd").stdout)
    alvo, vizinha = "52-54-00-00-00-01", "52-54-00-00-00-02"
    for mac in (alvo, vizinha):
        _maquina(live, "clicmd", cred["machine_key"], mac)

    r = roda(live, "command", "clicmd", "mlreboot", alvo)
    assert r.returncode == 0, r.stderr
    assert _pendentes(live, "clicmd") == {alvo: 1, vizinha: 0}

    # a sala inteira só por extenso
    r = roda(live, "command", "clicmd", "mlreboot")
    assert r.returncode != 0
    assert "--all" in r.stderr
    assert _pendentes(live, "clicmd") == {alvo: 1, vizinha: 0}

    assert roda(live, "command", "clicmd", "mlreboot", "--all").returncode == 0
    assert _pendentes(live, "clicmd") == {alvo: 2, vizinha: 1}
    roda(live, "images", "delete", "clicmd")


def test_logo_sobe_de_verdade(live, tmp_path):
    """Mandava corpo cru a uma rota de `UploadFile`: 422, sempre."""
    roda(live, "images", "create", "clilogo", "--model", "t")
    png = tmp_path / "ufu.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    r = roda(live, "--json", "logo", "clilogo", "ufu", str(png))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["format"] == "png"

    jpg = tmp_path / "ufu.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    assert roda(live, "logo", "clilogo", "ufu", str(jpg)).returncode != 0
    roda(live, "images", "delete", "clilogo")


def test_o_caminho_do_moj_pelas_rotas_novas(live):
    """Chave de serviço se enxerga, acrescenta um time, vincula criando o que
    falta, vincula em lote, segue um comando e instala o próprio webhook."""
    roda(live, "images", "create", "clinovo", "--model", "t")
    cred = json.loads(roda(live, "--json", "images", "credentials", "clinovo").stdout)
    r = roda(live, "--json", "service-key", "create", "moj-cli",
             "--scope", "machines:read", "--scope", "roster:write", "--scope", "bindings:write",
             "--scope", "commands:write", "--scope", "webhooks:write", "--image", "clinovo")
    assert r.returncode == 0, r.stderr
    moj = json.loads(r.stdout)["key"]

    eu = json.loads(roda(live, "--json", "whoami", key=moj).stdout)
    assert eu["kind"] == "service" and eu["images"] == ["clinovo"]

    m1, m2 = "52-54-00-00-aa-01", "52-54-00-00-aa-02"
    for mac in (m1, m2):
        _maquina(live, "clinovo", cred["machine_key"], mac)

    assert roda(live, "roster", "add", "clinovo", '{"user_id":"t1","name":"Um"}', key=moj).returncode == 0
    r = roda(live, "--json", "bind", "clinovo", m1, "t2", "--criar", "--name", "Dois", key=moj)
    assert r.returncode == 0 and json.loads(r.stdout)["roster_entry_created"] is True, r.stderr
    lote = json.dumps([{"mac": m2, "user_id": "t1"}, {"mac": "zz", "user_id": "t1"}])
    d = json.loads(roda(live, "--json", "bind-lote", "clinovo", "-", key=moj, entrada=lote).stdout)
    assert (d["bound"], d["failed"]) == (1, 1)
    assert roda(live, "roster", "remove", "clinovo", "t2", key=moj).returncode == 0

    cid = json.loads(roda(live, "--json", "command", "clinovo", "mlreboot", m1, key=moj).stdout)["command_id"]
    estado = json.loads(roda(live, "--json", "command-status", "clinovo", cid, key=moj).stdout)
    assert estado["summary"] == {"acked": 0, "pending": 1, "expired": 0}

    # com a chave de admin o destino é livre; a de serviço só aponta para https público
    r = roda(live, "--json", "webhooks", "add", "clinovo", "--url", "http://127.0.0.1:9/h", "--event", "alert.raised")
    assert r.returncode == 0, r.stderr
    wid = json.loads(r.stdout)["id"]
    r = roda(live, "webhooks", "add", "clinovo", "--url", "http://127.0.0.1:9/h",
             "--secret", "s" * 16, key=moj)
    assert r.returncode != 0 and "webhook_url_forbidden" in r.stderr
    assert roda(live, "webhooks", "update", "clinovo", "--id", wid, "--secret", "novo-segredo").returncode == 0
    assert json.loads(roda(live, "--json", "webhooks", "test", "clinovo", "--id", wid).stdout)["ok"] is False
    assert roda(live, "webhooks", "delete", "clinovo", "--id", wid).returncode == 0
    assert json.loads(roda(live, "--json", "webhooks", "list", "clinovo").stdout)["webhooks"] == []
    roda(live, "service-key", "delete", "moj-cli")
    roda(live, "images", "delete", "clinovo")


def test_erro_do_servidor_sai_diferente_de_zero_e_diz_o_motivo(live):
    """A invariante 15, do lado do cliente."""
    r = roda(live, "images", "get", "naoexiste")
    assert r.returncode != 0
    assert "404" in r.stderr, r.stderr

    r = roda(live, "whoami", key="nb3a_chaveerrada")
    assert r.returncode != 0
    assert "401" in r.stderr, r.stderr


def test_servidor_fora_do_ar_nao_vira_sucesso(live):
    r = subprocess.run(
        [sys.executable, str(CLI), "whoami"],
        capture_output=True,
        text=True,
        env={**os.environ, "NB3_BASE_URL": f"http://127.0.0.1:{free_port()}", "NB3_API_KEY": "x"},
    )
    assert r.returncode != 0
    assert "servidor" in r.stderr.lower(), r.stderr


def test_o_cli_e_um_arquivo_copiavel():
    """Só biblioteca padrão: o integrador leva o arquivo e usa. Um `import`
    novo de terceiros transforma 'copie este arquivo' em 'monte um ambiente'."""
    import ast

    arvore = ast.parse(CLI.read_text(encoding="utf-8"))
    modulos = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            modulos.add(no.module.split(".")[0])
    externos = modulos - set(sys.stdlib_module_names)
    assert not externos, f"o cliente de referência ganhou dependência: {externos}"
    assert "_create_unverified" not in CLI.read_text(), "TLS não se desliga"
