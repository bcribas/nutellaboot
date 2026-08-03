"""O relatório da sede por período.

O painel responde "como está a sala agora"; isto responde "o que aconteceu
entre 14h e 18h", que é outra pergunta e precisava de outra fonte: até aqui o
`status.json` era sobrescrito a cada ~45 s e memória, carga e editores só
existiam no presente.

O relatório sai como UM arquivo: CSS embutido e gráficos em SVG desenhados
pelo servidor. Ele costuma ser aberto depois da prova, muitas vezes numa
máquina sem internet — qualquer `<script src>` ou `<img src>` externo o
transformaria numa página quebrada.
"""

import json
import re
import time

import pytest

from server.app import fsdb
from server.app.services import machines, report, samples

CONSOLE = {"X-NB-Console": "1"}
MAC1 = "52-54-00-11-22-33"
MAC2 = "52-54-00-aa-bb-cc"


@pytest.fixture
def ha(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def sede(client, data_root, ha):
    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    r = client.post(
        "/api/v1/site-images",
        json={"id": "sala1", "fullname": "Sede São Paulo", "model": "t"},
        headers=ha,
    )
    assert r.status_code == 201, r.text
    return r.json()


def alimenta(image, mac, *, inicio, n=10, mem0=30, editor="vim", processor="i5-8400", ram=8192):
    """Escreve amostras como se a máquina tivesse reportado a cada 45 s."""
    for i in range(n):
        status = {
            "hwinfo": {"processor": processor, "cores": 4, "memtotal_mb": ram},
            "sysresources": {"mem_pct": mem0 + i * 3, "loadavg": [0.5 + i * 0.2, 1, 1],
                             "swap_used_mb": 0},
            "operations": {"firewall": True, "editors": [editor] if i % 2 == 0 else [],
                           "editors_time": {editor: 12, "total": 20}},
        }
        machines.record_status(image, mac, status)
        # o carimbo é do servidor; reescreve para espalhar no tempo
    p = machines.machine_dir(image, mac) / samples.ARQUIVO
    linhas = []
    for i, linha in enumerate(p.read_text().splitlines()):
        d = json.loads(linha)
        d["t"] = int(inicio) + i * 45
        linhas.append(json.dumps(d))
    fsdb.write_text(p, "\n".join(linhas) + "\n")


# --- o que o relatório junta ---


def test_inventario_traz_o_hardware_de_cada_maquina(client, data_root, sede):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 3600, processor="Intel i5-8400", ram=8192)
    alimenta("sala1", MAC2, inicio=agora - 3600, processor="AMD Ryzen 5", ram=16384)

    d = report.coletar("sala1", agora - 7200, agora)
    assert len(d["machines"]) == 2
    assert {m["processor"] for m in d["machines"]} == {"Intel i5-8400", "AMD Ryzen 5"}
    assert d["ram"] == {"8 GB": 1, "16 GB": 1}
    assert d["cpus"]["Intel i5-8400"] == 1


def test_o_periodo_recorta_as_amostras(client, data_root, sede):
    agora = int(time.time())
    alimenta("sala1", MAC1, inicio=agora - 7200, n=10)  # 10 amostras, começando 2h atrás

    tudo = report.coletar("sala1", agora - 7200, agora)
    metade = report.coletar("sala1", agora - 7200, agora - 7200 + 200)
    assert tudo["samples"] == 10
    assert 0 < metade["samples"] < 10, "o intervalo não recortou nada"


def test_uso_de_editor_sai_das_amostras(client, data_root, sede):
    agora = time.time()
    # o `alimenta` abre o editor em metade das amostras
    alimenta("sala1", MAC1, inicio=agora - 3600, n=10, editor="vim")
    d = report.coletar("sala1", agora - 7200, agora)
    assert d["editors"]["vim"] == 5
    assert d["samples"] == 10
    # e o acumulado contado na própria máquina vem junto
    assert d["editors_time"]["vim"] == 12


def test_memoria_e_carga_viram_media_e_pico(client, data_root, sede):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 3600, n=5, mem0=40)
    m = report.coletar("sala1", agora - 7200, agora)["machines"][0]
    assert m["mem_pico"] == 52  # 40, 43, 46, 49, 52
    assert m["mem_media"] == 46
    assert m["carga_pico"] == 1.3


def test_time_vinculado_aparece_com_o_nome_do_roster(client, data_root, sede, ha):
    """O painel mostra o `user_id` cru quando o vínculo vem do MOJ; num
    relatório isso não serve para nada."""
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 600, n=2)
    client.put(
        "/api/v1/site-images/sala1/roster",
        json={"roster": [{"user_id": "t42", "display_name": "Os Batutas",
                          "organization": {"id": "ufpr", "name": "UFPR"}, "seat": "A12"}]},
        headers=ha,
    )
    client.put(
        f"/api/v1/site-images/sala1/machines/{MAC1}/binding",
        json={"user_id": "t42"},
        headers=ha,
    )
    m = report.coletar("sala1", agora - 3600, agora)["machines"][0]
    assert m["team"] == "Os Batutas"
    assert m["organization"] == "UFPR"
    assert m["seat"] == "A12"


def test_alertas_do_periodo_entram_com_hora(client, data_root, sede):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 600, n=2)
    from server.app.services import alerts

    alerts.raise_alert("sala1", MAC1, "usb.storage", "SanDisk")
    d = report.coletar("sala1", agora - 3600, time.time() + 60)
    assert len(d["alerts"]) == 1
    assert d["alerts"][0]["kind"] == "usb.storage"
    assert d["alerts"][0]["mac"] == MAC1


def test_dmesg_estranho_e_classificado(client, data_root, sede):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 600, n=2)
    from server.app.services import logs

    logs.record(
        "sala1",
        MAC1,
        "Aug 03 17:00:01 maratona kernel: ata1.00: failed command: READ DMA\n"
        "Aug 03 17:00:02 maratona kernel: Out of memory: Killed process 4242 (cc1plus)\n"
        "Aug 03 17:00:03 maratona kernel: usb 1-2: reset high-speed USB device\n"
        "Aug 03 17:00:04 maratona kernel: nada de mais por aqui\n",
        origem="journal",
    )
    d = report.coletar("sala1", agora - 3600, time.time() + 60)
    assert d["dmesg"]["disco"] == 1
    assert d["dmesg"]["memória"] == 1
    assert d["dmesg"]["usb"] == 1
    assert "programa" not in d["dmesg"]


def test_avisa_quando_o_historico_foi_descartado(client, data_root, sede):
    """O teto de log descarta a metade mais antiga. Pedir um relatório de
    ontem e receber uma página com metade dos dados, sem aviso, seria pior que
    não ter relatório."""
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 600, n=3)
    # o arquivo bateu no teto: é o sinal de que a metade antiga foi descartada
    from server.app.services import samples as s

    p = machines.machine_dir("sala1", MAC1) / s.ARQUIVO
    fsdb.write_text(p, p.read_text() + "\n".join(["#" * 100] * 20000) + "\n")

    d = report.coletar("sala1", agora - 86400, agora)
    assert d["corte"] > 0
    assert "descartado" in report.html_report(d, "pt")


def test_maquina_que_acabou_de_ligar_nao_vira_aviso_de_descarte(client, data_root, sede):
    """Ela simplesmente não tem histórico — dizer que "foi descartado" faria o
    relatório mentir em toda sala que ligou uma máquina no meio da prova."""
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 600, n=3)
    d = report.coletar("sala1", agora - 86400, agora)
    assert d["corte"] == 0
    assert "descartado" not in report.html_report(d, "pt")


# --- o HTML ---


def test_o_html_e_um_arquivo_so(client, data_root, sede):
    """Ele é aberto depois da prova, muitas vezes numa máquina sem internet."""
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 3600)
    corpo = report.html_report(report.coletar("sala1", agora - 7200, agora), "pt")
    assert "<svg" in corpo, "os gráficos precisam existir"
    for externo in ("<script", "src=", "@import", "<link", "url(http"):
        assert externo not in corpo, f"o relatório busca algo de fora: {externo}"
    # o xmlns do SVG é um identificador, não um endereço a buscar
    assert corpo.count("http") == corpo.count("http://www.w3.org/2000/svg")


def test_o_html_sai_nos_tres_idiomas(client, data_root, sede):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 3600)
    d = report.coletar("sala1", agora - 7200, agora)
    assert "Inventário" in report.html_report(d, "pt")
    assert "Inventory" in report.html_report(d, "en")
    assert "Inventario" in report.html_report(d, "es")


def test_o_html_escapa_o_que_vem_da_maquina(client, data_root, sede):
    """O nome do processador vem da telemetria — texto que a máquina manda."""
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 600, n=2, processor="<script>alert(1)</script>")
    corpo = report.html_report(report.coletar("sala1", agora - 3600, agora), "pt")
    assert "<script>alert" not in corpo
    assert "&lt;script&gt;" in corpo


# --- a rota ---


def test_a_rota_devolve_html_por_padrao(client, data_root, sede, ha):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 3600)
    r = client.get("/api/v1/site-images/sala1/report", headers=ha)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "Sede São Paulo" in r.text


def test_a_rota_aceita_o_token_na_url(client, data_root, sede):
    """O relatório abre em outra aba: `<a href>` não manda cabeçalho."""
    r = client.get(f"/api/v1/site-images/sala1/report?tk={sede['token']}")
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/site-images/sala1/report").status_code == 401


def test_o_json_nao_carrega_a_serie_inteira(client, data_root, sede, ha):
    agora = time.time()
    alimenta("sala1", MAC1, inicio=agora - 3600, n=20)
    r = client.get(
        f"/api/v1/site-images/sala1/report?format=json&since={agora - 7200}&until={agora}",
        headers=ha,
    )
    assert r.status_code == 200, r.text
    assert r.json()["machines"][0]["serie"] == 20  # a contagem, não os pontos


def test_periodo_invertido_e_recusado(client, data_root, sede, ha):
    agora = time.time()
    r = client.get(
        f"/api/v1/site-images/sala1/report?since={agora}&until={agora - 3600}", headers=ha
    )
    assert r.status_code == 400


def test_periodo_longo_demais_e_recusado(client, data_root, sede, ha):
    agora = time.time()
    r = client.get(
        f"/api/v1/site-images/sala1/report?since={agora - 200 * 86400}&until={agora}", headers=ha
    )
    assert r.status_code == 400


def test_sede_de_outro_dono_nao_sai(client, data_root, sede, ha):
    code = client.post("/api/v1/invites", json={"count": 1}, headers=ha).json()["invites"][0]["code"]
    r = client.get(
        "/api/v1/site-images/sala1/report", headers={"Authorization": f"Bearer {code}"}
    )
    assert r.status_code in (401, 404)


# --- a amostragem em si ---


def test_a_amostra_e_curta(client, data_root, sede):
    """~60 bytes por amostra é o que faz caber um mês por máquina no teto."""
    machines.record_status(
        "sala1",
        MAC1,
        {"sysresources": {"mem_pct": 40, "loadavg": [0.5, 1, 1], "swap_used_mb": 0},
         "operations": {"firewall": True, "editors": ["vim"]}},
    )
    linha = (machines.machine_dir("sala1", MAC1) / samples.ARQUIVO).read_text().strip()
    assert len(linha) < 120, linha
    assert re.match(r'^\{"t":\d+', linha)


def test_status_sem_recursos_nao_quebra(client, data_root, sede):
    machines.record_status("sala1", MAC1, {"hwinfo": {"processor": "x"}})
    assert samples.series("sala1", MAC1)[0].keys() >= {"t"}
