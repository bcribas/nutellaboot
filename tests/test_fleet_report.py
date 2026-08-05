"""O relatório da frota: o disparo, o estado e os arquivos.

Duas coisas aqui não são detalhe:

  * **o nome do arquivo vem da URL e vai para o disco.** `data/reports/` tem o
    diretório `data/site-images/` de vizinho, com o token e a chave de máquina
    de cada sede. Por isso o nome sai de uma lista fechada, e há teste com
    `../` de todo jeito que o navegador consegue mandar;
  * **os links são `<a download>`, que não mandam cabeçalho.** Foi assim que o
    CSV da frota deu 401 na cara de quem clicava. Vale o cookie sem
    `X-NB-Console` — e só para GET.

O gerador de verdade também é exercitado, contra uma frota pequena plantada em
disco: o que este arquivo protege é o contrato entre as duas peças.
"""

import asyncio
import csv
import gzip
import json
import os
import subprocess
import sys
import time

import pytest

from server.app import fsdb
from server.app.services import fleet_report
from server.app.services import machines as m
from server.app.services import store
from server.app.services.default_schema import build_default_schema
from server.app.settings import REPO_ROOT

# Um gerador de mentira: escreve os arquivos com o nome certo e anota os
# argumentos. O que interessa na maior parte dos testes é o CONTRATO — quais
# argumentos a ferramenta recebe e o que o serviço faz com o resultado.
FALSO = """#!/bin/bash
set -e
saida=""
args=""
while [ $# -gt 0 ]; do
    case "$1" in
        --saida) saida=$2; args="$args --saida"; shift 2 ;;
        *) args="$args $1"; shift ;;
    esac
done
echo "$args" > "${NB3_RELATORIO_LOG:-/dev/null}"
mkdir -p "$saida"
for f in relatorio.html inventario.csv editores.csv recursos-hora.csv alertas.csv resumo.json; do
    echo "conteudo de $f" > "$saida/$f"
done
printf '' | gzip > "$saida/recursos-brutos.csv.gz"
echo "pronto: 0 sedes"
"""


@pytest.fixture
def gerador(tmp_path, monkeypatch):
    p = tmp_path / "relatorio-falso"
    p.write_text(FALSO)
    p.chmod(0o755)
    log = tmp_path / "args.log"
    monkeypatch.setenv("NB3_RELATORIO_CMD", str(p))
    monkeypatch.setenv("NB3_RELATORIO_LOG", str(log))
    return log


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}", "X-NB-Console": "1"}


@pytest.fixture
def cliente(data_root):
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    return TestClient(create_app(), base_url="https://testserver")


def gera(desde=None, ate=None):
    """A geração, esperada até o fim.

    Pela ROTA não dá: o `TestClient` abre um laço por requisição, e a tarefa de
    segundo plano morre junto com ele — é o mesmo motivo que faz os eventos do
    long-poll nascerem dentro da requisição que espera. No servidor de verdade
    o laço é um só e vive enquanto o processo viver. Então o disparo se testa
    pela rota, e a geração aqui.
    """
    ate = ate if ate is not None else time.time()
    return asyncio.run(fleet_report.gerar(desde if desde is not None else 0, ate))


# --- estado ------------------------------------------------------------------


def test_sem_nunca_ter_gerado_o_estado_e_vazio(cliente, ha):
    e = cliente.get("/api/v1/labs/report", headers=ha).json()
    assert e["status"] == "missing"
    assert e["files"] == []


def test_o_pedido_marca_gerando_e_manda_a_janela(cliente, ha, gerador):
    r = cliente.post("/api/v1/labs/report?dias=3", headers=ha)
    assert r.status_code == 202, r.text
    assert r.json()["started"] is True
    assert r.json()["status"] == "building"
    # a janela pedida fica gravada no estado, e é a de 3 dias
    e = fsdb.read_json(fleet_report._estado_path(), {})
    assert abs((e["until"] - e["since"]) - 3 * 86400) < 1
    assert abs(e["until"] - time.time()) < 60


def test_da_geracao_ate_os_arquivos(cliente, ha, gerador):
    agora = time.time()
    e = gera(agora - 3 * 86400, agora)
    assert e["status"] == "done", e

    e = cliente.get("/api/v1/labs/report", headers=ha).json()
    nomes = {f["name"] for f in e["files"]}
    assert nomes == set(fleet_report.ARQUIVOS)
    assert all(f["size"] > 0 for f in e["files"] if not f["name"].endswith(".gz"))

    # a janela chega na ferramenta pelos argumentos que ela conhece
    args = gerador.read_text().split()
    desde = float(args[args.index("--desde") + 1])
    ate = float(args[args.index("--ate") + 1])
    assert abs((ate - desde) - 3 * 86400) < 1


def test_falha_vira_estado_e_nao_excecao(cliente, ha, monkeypatch, tmp_path):
    ruim = tmp_path / "ruim"
    ruim.write_text("#!/bin/bash\necho 'sem espaço em disco' >&2\nexit 1\n")
    ruim.chmod(0o755)
    monkeypatch.setenv("NB3_RELATORIO_CMD", str(ruim))

    assert gera()["status"] == "failed"
    e = cliente.get("/api/v1/labs/report", headers=ha).json()
    assert e["status"] == "failed"
    assert "sem espaço" in e["error"]
    assert e["files"] == []


def test_comando_que_nao_existe_tambem(cliente, ha, monkeypatch):
    monkeypatch.setenv("NB3_RELATORIO_CMD", "/nao/existe/mesmo")
    assert gera()["status"] == "failed"
    assert cliente.get("/api/v1/labs/report", headers=ha).json()["status"] == "failed"


def test_gerando_ha_tempo_demais_e_geracao_MORTA(cliente, ha, gerador):
    """O worker reiniciou no meio (deploy, OOM) e a tarefa foi junto. Sem isto o
    estado fica `building` para sempre e o botão nunca mais funciona — e ninguém
    ia ligar as duas coisas olhando a tela."""
    assert cliente.post("/api/v1/labs/report", headers=ha).status_code == 202
    assert cliente.get("/api/v1/labs/report", headers=ha).json()["status"] == "building"

    e = fsdb.read_json(fleet_report._estado_path(), {})
    e["started_at"] = time.time() - fleet_report.TIMEOUT - 1
    fsdb.write_json(fleet_report._estado_path(), e)

    assert cliente.get("/api/v1/labs/report", headers=ha).json()["status"] == "failed"
    assert cliente.post("/api/v1/labs/report", headers=ha).json()["started"] is True


def test_um_de_cada_vez(data_root, gerador):
    """Duas passadas juntas leriam os mesmos 1,5 GB em paralelo, e é o disco que
    atende o boot. O segundo pedido não é erro — a tela sonda, e duas abas
    abertas fariam a segunda receber um 409 que ninguém pediu."""

    async def cenario():
        primeiro = fleet_report.agendar(0, time.time())
        segundo = fleet_report.agendar(0, time.time())
        # deixa a tarefa terminar antes de o laço fechar
        await asyncio.gather(*list(fleet_report._tarefas))
        return primeiro, segundo

    primeiro, segundo = asyncio.run(cenario())
    assert primeiro is True
    assert segundo is False
    assert fleet_report.estado()["status"] == "done"


# --- exclusão de sedes --------------------------------------------------------


def test_excluir_chega_na_ferramenta_e_fica_no_estado(cliente, ha, gerador, data_root):
    """A sede de teste inflaria o perfil nacional. A exclusão vai como
    `--excluir` para a ferramenta e fica gravada no estado — é a memória entre
    gerações: a tela pré-marca as mesmas sedes na próxima."""
    from server.app.services import store as st
    from server.app.services.default_schema import build_default_schema

    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    st.create_site_image("sedeteste", "Teste", "t")

    r = cliente.post(
        "/api/v1/labs/report",
        json={"dias": 3, "excluir": ["sedeteste"]},
        headers=ha,
    )
    assert r.status_code == 202, r.text
    assert r.json()["excluded"] == ["sedeteste"]

    agora = time.time()
    asyncio.run(fleet_report.gerar(agora - 86400, agora, ("sedeteste",)))
    args = gerador.read_text().split()
    assert args[args.index("--excluir") + 1] == "sedeteste"


def test_excluir_sede_inexistente_e_400(cliente, ha, gerador):
    """Os ids viram argumento de subprocesso: só entram os que existem."""
    r = cliente.post(
        "/api/v1/labs/report",
        json={"excluir": ["naoexiste"]},
        headers=ha,
    )
    assert r.status_code == 400
    assert "naoexiste" in r.json()["detail"]


def test_a_ferramenta_de_verdade_exclui_a_sede(data_root, tmp_path):
    agora = planta_frota(data_root)
    saida = tmp_path / "saida"
    r = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "tools" / "nb3-relatorio-frota"),
            "--desde", f"{agora - 7200:.3f}", "--ate", f"{agora + 60:.3f}",
            "--saida", str(saida), "--excluir", "sede1",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={**os.environ, "NB3_DATA_ROOT": str(data_root)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    inv = linhas_de(saida / "inventario.csv")
    assert {l["sede"] for l in inv} == {"sede0", "sede2"}
    assert "pronto: 2 sedes" in r.stdout


# --- quem pode ---------------------------------------------------------------


def test_so_a_administracao(cliente, ha):
    """Sub-admin não entra: o artefato tem a frota inteira dentro, e o
    relatório da sede dele já existe e é barato.

    O convite é criado de verdade — com um código inventado o 401 viria de a
    credencial não existir, e o teste não estaria olhando para nada.
    """
    r = cliente.post("/api/v1/invites", json={"count": 1}, headers=ha)
    code = r.json()["invites"][0]["code"]
    hs = {"Authorization": f"Bearer {code}", "X-NB-Console": "1"}
    # o convite é credencial válida de console: o painel da frota responde a ele
    assert cliente.get("/api/v1/labs", headers=hs).status_code == 200

    assert cliente.get("/api/v1/labs/report", headers=hs).status_code == 401
    assert cliente.post("/api/v1/labs/report", headers=hs).status_code == 401
    assert cliente.get("/api/v1/labs/report").status_code == 401


def test_o_download_recusa_nome_de_fora_da_lista(cliente, ha, gerador):
    gera()
    for nome in (
        "..%2F..%2Fsite-images%2Fsala1%2Ftoken",
        "%2Fetc%2Fpasswd",
        "frota.json",
        "relatorio.html.bak",
    ):
        r = cliente.get(f"/api/v1/labs/report/{nome}", headers=ha)
        assert r.status_code == 404, f"{nome} devolveu {r.status_code}"


def test_o_download_de_arquivo_ainda_nao_gerado_e_404(cliente, ha):
    assert cliente.get("/api/v1/labs/report/inventario.csv", headers=ha).status_code == 404


# --- a credencial de um LINK -------------------------------------------------


@pytest.fixture
def navegador(data_root, admin_key):
    """Cliente em HTTPS com sessão aberta — o cookie é `Secure`, e sobre http o
    próprio httpx não o guarda (como o navegador não guardaria)."""
    from fastapi.testclient import TestClient

    from server.app.main import create_app

    c = TestClient(create_app(), base_url="https://testserver")
    r = c.post("/api/v1/session", json={"key": admin_key}, headers={"X-NB-Console": "1"})
    assert r.status_code == 200, r.text
    return c


def test_os_arquivos_abrem_com_o_cookie_sem_o_cabecalho(navegador, gerador):
    """Exatamente o que o navegador faz ao clicar no `<a download>`."""
    gera()
    r = navegador.get("/api/v1/labs/report/inventario.csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert navegador.get("/api/v1/labs/report/recursos-brutos.csv.gz").status_code == 200


def test_mas_pedir_a_geracao_continua_exigindo_o_cabecalho(navegador, gerador):
    """A assimetria de sempre: baixar por link é leitura; disparar 118 s de CPU
    no servidor que atende o boot não é."""
    assert navegador.post("/api/v1/labs/report").status_code == 401


# --- o gerador de verdade ----------------------------------------------------


def planta_frota(data_root, *, sedes=3, maquinas=4, amostras=24):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    agora = time.time()
    for s in range(sedes):
        image = f"sede{s}"
        store.create_site_image(image, f"Sede {s}", "t")
        for k in range(maquinas):
            mac = f"52-54-00-0{s}-00-0{k}"
            d = m.machine_dir(image, mac)
            d.mkdir(parents=True, exist_ok=True)
            fsdb.write_json(
                d / "machine.json",
                {"mac": mac, "first_seen": agora - 3600, "last_seen": agora},
            )
            fsdb.write_json(
                d / "status.json",
                {
                    "hwinfo": {
                        "processor": "Intel i5-9500" if k % 2 else "AMD Ryzen 5",
                        "cores": 4,
                        "memtotal_mb": 8000 if k % 2 else 16000,
                    },
                    "operations": {"editors_time": {"code": 11, "vim": 5}},
                },
            )
            linhas = []
            for i in range(amostras):
                linhas.append(
                    json.dumps(
                        {
                            "t": agora - 1800 + i,
                            "mem": 40 + i % 10,
                            "ld": 0.5,
                            "sw": 0,
                            "ed": ["code"] if i % 2 else ["vim"],
                        }
                    )
                )
            (d / "samples.jsonl").write_text("\n".join(linhas) + "\n")
    return agora


def roda_a_ferramenta(data_root, saida, desde, ate):
    r = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "nb3-relatorio-frota"),
            "--desde", f"{desde:.3f}",
            "--ate", f"{ate:.3f}",
            "--saida", str(saida),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "NB3_DATA_ROOT": str(data_root)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def linhas_de(caminho):
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_o_gerador_de_verdade(data_root, tmp_path):
    agora = planta_frota(data_root)
    saida = tmp_path / "saida"
    roda_a_ferramenta(data_root, saida, agora - 7200, agora + 60)

    inv = linhas_de(saida / "inventario.csv")
    assert len(inv) == 12, "uma linha por máquina"
    assert {l["sede"] for l in inv} == {"sede0", "sede1", "sede2"}
    assert {l["ram_mb"] for l in inv} == {"8000", "16000"}
    assert {l["processador"] for l in inv} == {"Intel i5-9500", "AMD Ryzen 5"}

    ed = linhas_de(saida / "editores.csv")
    # 24 amostras por máquina, metade com cada editor
    assert {(l["editor"], l["amostras"]) for l in ed} == {("code", "12"), ("vim", "12")}
    assert {l["minutos_acumulados"] for l in ed} == {"11", "5"}

    alertas = linhas_de(saida / "alertas.csv")
    assert alertas == [], "a frota plantada não tem alerta nenhum"

    resumo = json.loads((saida / "resumo.json").read_text())
    assert sum(s["amostras"] for s in resumo["sedes"]) == 12 * 24


def test_a_soma_por_hora_bate_com_o_cru(data_root, tmp_path):
    """As duas visões saem da MESMA passada; se divergirem, uma delas está
    contando amostra que a outra não viu."""
    agora = planta_frota(data_root)
    saida = tmp_path / "saida"
    roda_a_ferramenta(data_root, saida, agora - 7200, agora + 60)

    hora = linhas_de(saida / "recursos-hora.csv")
    somadas = sum(int(l["amostras"]) for l in hora)

    with gzip.open(saida / "recursos-brutos.csv.gz", "rt", encoding="utf-8") as f:
        cruas = list(csv.DictReader(f))
    assert somadas == len(cruas) == 12 * 24

    # o pico de cada hora é o maior valor cru daquela hora
    for l in hora:
        da_hora = [
            float(c["mem_pct"])
            for c in cruas
            if c["sede"] == l["sede"] and c["mac"] == l["mac"]
            and time.strftime("%Y-%m-%d %H:00", time.localtime(float(c["t"]))) == l["hora"]
        ]
        assert float(l["mem_pico"]) == max(da_hora)


def test_a_janela_corta_as_amostras(data_root, tmp_path):
    agora = planta_frota(data_root)
    saida = tmp_path / "saida"
    # só a última metade das amostras (elas vão de agora-1800 a agora-1777, de
    # segundo em segundo). O corte cai NO MEIO de dois pontos de propósito: em
    # cima de um, o milésimo perdido ao formatar `--desde` decide se ele entra,
    # e o teste passaria a depender do arredondamento.
    roda_a_ferramenta(data_root, saida, agora - 1788.5, agora + 60)
    with gzip.open(saida / "recursos-brutos.csv.gz", "rt", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 12 * 12


def test_o_html_nao_busca_nada_de_fora(data_root, tmp_path):
    """Autocontido como o da sede: o servidor de arquivos externo não existe
    para quem abre o relatório salvo no disco, e a rede da sala pode não sair.
    """
    agora = planta_frota(data_root)
    saida = tmp_path / "saida"
    roda_a_ferramenta(data_root, saida, agora - 7200, agora + 60)
    corpo = (saida / "relatorio.html").read_text()
    for externo in ("<script", "src=", "@import", "<link", "url(http"):
        assert externo not in corpo, f"o relatório busca algo de fora: {externo}"
    # o xmlns do SVG é um identificador, não um endereço a buscar
    assert corpo.count("http") == corpo.count("http://www.w3.org/2000/svg")
    assert "<svg" in corpo, "os gráficos precisam existir"
    assert "sede0" in corpo and "Intel i5-9500" in corpo


def test_frota_vazia_nao_quebra(data_root, tmp_path):
    saida = tmp_path / "saida"
    roda_a_ferramenta(data_root, saida, 0, time.time())
    assert linhas_de(saida / "inventario.csv") == []
    assert (saida / "relatorio.html").read_text().strip().startswith("<!doctype")


def test_o_servico_chama_a_ferramenta_de_verdade(data_root, tmp_path, monkeypatch):
    """Sem `NB3_RELATORIO_CMD` o serviço tem que achar a ferramenta sozinho — o
    gancho de teste não pode ser a única forma de rodar."""
    monkeypatch.delenv("NB3_RELATORIO_CMD", raising=False)
    agora = planta_frota(data_root, sedes=1, maquinas=1, amostras=4)
    e = asyncio.run(fleet_report.gerar(agora - 7200, agora + 60))
    assert e["status"] == "done", e
    assert "pronto: 1 sedes" in e["log"]
    assert (data_root / "reports" / "frota" / "inventario.csv").is_file()


def test_gzip_do_bruto_e_bem_menor(data_root, tmp_path):
    """O arquivo cru é o maior de todos (33 milhões de linhas na frota real).
    Ele nasce comprimido, não comprimido depois."""
    agora = planta_frota(data_root, amostras=200)
    saida = tmp_path / "saida"
    roda_a_ferramenta(data_root, saida, agora - 7200, agora + 60)
    comprimido = (saida / "recursos-brutos.csv.gz").stat().st_size
    with gzip.open(saida / "recursos-brutos.csv.gz", "rb") as f:
        cru = len(f.read())
    assert comprimido < cru / 5
