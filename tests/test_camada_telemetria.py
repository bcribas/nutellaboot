"""A camada de telemetria: empacotar client/telemetry/ sem root.

O agente, a tela de bloqueio e os temas estavam prontos no repositório, mas
nada os transformava numa camada — e por isso o que rodava em campo continuava
sendo a `log23.squash`, de 2023. Este arquivo garante que a camada nasce com o
conteúdo certo, com dono root e com o bit de execução onde faz falta.
"""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FERRAMENTA = REPO / "tools" / "nb3-camada-telemetria"
ORIGEM = REPO / "client" / "telemetry"

sem_squashfs = pytest.mark.skipif(
    subprocess.run(["which", "mksquashfs"], capture_output=True).returncode != 0,
    reason="mksquashfs nao instalado",
)


def rodar(*args: str, esperar_ok: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["python3", str(FERRAMENTA), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if esperar_ok:
        assert r.returncode == 0, r.stderr or r.stdout
    return r


@pytest.fixture
def camada(tmp_path):
    """Constrói a camada num diretório temporário e devolve o caminho."""
    rodar("--out", str(tmp_path))
    arquivos = list(tmp_path.glob("telemetria-*.squash"))
    assert len(arquivos) == 1, arquivos
    return arquivos[0]


def listar(camada: Path) -> dict[str, str]:
    """{caminho: permissao} do conteúdo da camada."""
    r = subprocess.run(
        ["unsquashfs", "-ll", str(camada)], capture_output=True, text=True, check=True
    )
    saida = {}
    for linha in r.stdout.splitlines():
        campos = linha.split()
        if len(campos) < 6 or not campos[0][0] in "-dl":
            continue
        caminho = campos[-1].replace("squashfs-root", "").lstrip("/")
        if caminho:
            saida[caminho] = f"{campos[0]} {campos[1]}"
    return saida


# --- o essencial ---


def test_dry_run_nao_grava_nada(tmp_path):
    r = rodar("--dry-run", "--out", str(tmp_path))
    assert "dry-run" in r.stdout
    assert list(tmp_path.iterdir()) == []


@sem_squashfs
def test_camada_tem_o_agente_e_a_tela_de_bloqueio(camada):
    dentro = listar(camada)
    for esperado in (
        "usr/share/mlog/agent.sh",
        "usr/bin/maratona-wait",
        "usr/bin/nb3-json",
        "usr/share/maratona-lock/themes/common/lock.js",
    ):
        assert esperado in dentro, f"faltou {esperado}: {sorted(dentro)}"


@sem_squashfs
def test_todos_os_coletores_entram(camada):
    """Um parts.d que fica de fora some da telemetria sem erro nenhum: o
    agente varre o diretório e simplesmente não encontra o arquivo."""
    dentro = listar(camada)
    do_repo = {
        p.relative_to(ORIGEM).as_posix()
        for p in (ORIGEM / "usr/share/mlog/parts.d").glob("*.sh")
    }
    for rel in do_repo:
        assert rel in dentro, f"{rel} nao entrou na camada"


@sem_squashfs
def test_tudo_pertence_ao_root(camada):
    """Sem -all-root os arquivos sairiam com o uid de quem rodou o comando, e
    o sistema montado não os enxergaria como do root."""
    r = subprocess.run(
        ["unsquashfs", "-ll", str(camada)], capture_output=True, text=True, check=True
    )
    donos = {c.split()[1] for c in r.stdout.splitlines() if c[:1] in "-dl"}
    assert donos == {"root/root"}, donos


@sem_squashfs
def test_o_que_o_sistema_executa_tem_bit_de_execucao(camada):
    """No repositório os arquivos estão 0644 (é assim que saem de um editor).
    Publicar assim deixa a tela de bloqueio morta com 'permission denied' —
    e isso só aparece na hora de travar a sala."""
    dentro = listar(camada)
    assert dentro["usr/bin/maratona-wait"].startswith("-rwxr-xr-x")
    assert dentro["usr/bin/nb3-json"].startswith("-rwxr-xr-x")


@sem_squashfs
def test_camada_nao_leva_segredo(camada):
    """A camada é publicada num servidor de arquivos aberto."""
    dentro = listar(camada)
    for proibido in ("etc/.nb3", "etc/.secrets", "etc/shadow"):
        assert not any(c.startswith(proibido) for c in dentro), proibido


@sem_squashfs
def test_nome_muda_quando_o_conteudo_muda(tmp_path, monkeypatch):
    """O nome carrega o md5 abreviado para não colidir no cache das máquinas:
    reconstruir no mesmo dia com conteúdo diferente tem que gerar outro nome,
    senão a máquina reaproveita a camada velha achando que já a tem."""
    rodar("--out", str(tmp_path))
    primeiro = next(tmp_path.glob("telemetria-*.squash")).name

    extra = ORIGEM / "usr/share/mlog/parts.d/99-teste-temporario.sh"
    extra.write_text("# arquivo temporario de teste\n")
    try:
        rodar("--out", str(tmp_path))
        nomes = {p.name for p in tmp_path.glob("telemetria-*.squash")}
    finally:
        extra.unlink()
    assert len(nomes) == 2, f"o nome nao mudou: {nomes}"
    assert primeiro in nomes


def test_recusa_arvore_incompleta(tmp_path, monkeypatch):
    """Sem o agente a camada não serve para nada, e o erro tem que aparecer
    aqui e não no boot de 40 máquinas."""
    falso = tmp_path / "telemetry"
    (falso / "usr" / "bin").mkdir(parents=True)
    r = rodar("--dry-run", "--from", str(falso), esperar_ok=False)
    assert r.returncode != 0
    assert "agent.sh" in (r.stderr + r.stdout)


# --- integração com o modelo ---


def test_ferramenta_sabe_remover_a_camada_antiga():
    """Duas versões do agente no mesmo caminho fazem a primeira da lista
    vencer em silêncio. Trocar a telemetria significa tirar a anterior."""
    texto = FERRAMENTA.read_text()
    assert "log23.squash" in texto
    assert "telemetria-" in texto
    assert "position" in texto and '"position": 0' in texto, (
        "a camada de personalizacao tem que entrar na frente do sistema base"
    )


def test_a_troca_da_telemetria_casa_por_papel():
    """Casar só por nome funciona enquanto a própria ferramenta nomeia a saída
    — e falha no dia em que uma camada de telemetria chegar por outro caminho,
    com o resultado que o arquivo descreve: duas versões do agente disputando
    o mesmo caminho, a primeira ganhando em silêncio. É o mesmo motivo pelo
    qual a base usa `replace_role`."""
    texto = FERRAMENTA.read_text()
    assert '"replace_role"' in texto
    assert '"telemetry"' in texto


def test_a_parte_de_disco_emite_json_valido(tmp_path):
    """O 25-disco roda DE VERDADE contra um diretório qualquer: o fragmento
    tem que ser JSON válido (dentro de chaves) com os campos do /home. É a
    telemetria que responde "quem está perto de encher o disco"."""
    import json
    import os
    import subprocess

    parte = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "parts.d" / "25-disco.sh"
    r = subprocess.run(
        ["bash", str(parte)],
        capture_output=True,
        text=True,
        env={**os.environ, "NB_DISCO_HOME": str(tmp_path), "NB_DISCO_ROOT": str(tmp_path)},
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    d = json.loads("{" + r.stdout + "}")
    disco = d["sysdisk"]
    for campo in ("home_used_mb", "home_free_mb", "home_pct", "root_free_mb"):
        assert campo in disco, f"faltou {campo}"
    assert 0 <= disco["home_pct"] <= 100


# --- os coletores novos: pressão, OOM, ociosidade, hardware, relógio ---------
#
# Rodam DE VERDADE contra arquivos falsos (variáveis NB_*), como o 25-disco.
# Tudo que não dá para medir fica AUSENTE: o servidor trata como opcional.

PARTS = REPO / "client" / "telemetry" / "usr" / "share" / "mlog" / "parts.d"


def _parte(nome, tmp_path, **env):
    import json
    import os
    import subprocess

    r = subprocess.run(
        ["bash", str(PARTS / nome)],
        capture_output=True,
        text=True,
        env={**os.environ, **{k: str(v) for k, v in env.items()}},
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return json.loads("{" + r.stdout + "}")


def test_a_parte_de_recursos_le_psi_oom_e_ociosidade(tmp_path):
    pressure = tmp_path / "pressure"
    pressure.mkdir()
    for nome, avg in (("memory", "1.25"), ("cpu", "0.10"), ("io", "3.50")):
        (pressure / nome).write_text(
            f"some avg10=0.00 avg60={avg} avg300=0.50 total=123\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        )
    (tmp_path / "vmstat").write_text("nr_free_pages 1\noom_kill 3\n")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "runuser").write_text("#!/bin/sh\necho '(uint64 42000,)'\n")
    (fakebin / "runuser").chmod(0o755)
    import os

    res = _parte(
        "20-recursos.sh",
        tmp_path,
        NB_PROC_PRESSURE=pressure,
        NB_PROC_VMSTAT=tmp_path / "vmstat",
        PATH=f"{fakebin}:{os.environ['PATH']}",
    )["sysresources"]
    assert res["psi_mem"] == 1.25 and res["psi_cpu"] == 0.1 and res["psi_io"] == 3.5
    assert res["oom_kills"] == 3
    assert res["idle_s"] == 42
    for campo in ("mem_pct", "swap_used_mb", "loadavg", "alerts"):
        assert campo in res


def test_sem_psi_os_campos_ficam_ausentes(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for nome in ("runuser", "loginctl"):
        (fakebin / nome).write_text("#!/bin/sh\nexit 1\n")
        (fakebin / nome).chmod(0o755)
    res = _parte(
        "20-recursos.sh",
        tmp_path,
        NB_PROC_PRESSURE=tmp_path / "nao-existe",
        NB_PROC_VMSTAT=tmp_path / "nao-existe",
        PATH=f"{fakebin}:/usr/bin:/bin",
    )["sysresources"]
    for campo in ("psi_mem", "psi_cpu", "psi_io", "oom_kills", "idle_s"):
        assert campo not in res, campo


def test_a_parte_de_hardware_leva_mac_dmi_e_uptime(tmp_path):
    import time

    dmi = tmp_path / "dmi"
    dmi.mkdir()
    (dmi / "product_uuid").write_text("4C4C4544-0042-3010-8034-B4C04F4B4E31\n")
    (dmi / "product_name").write_text("OptiPlex 3090\n")
    (dmi / "sys_vendor").write_text("Dell Inc.\n")
    (tmp_path / "uptime").write_text("1234.56 4000.00\n")
    (tmp_path / "mac").write_text("58-11-22-99-fc-6a\n")
    hw = _parte(
        "10-hardware.sh",
        tmp_path,
        NB_DMI_DIR=dmi,
        NB_PROC_UPTIME=tmp_path / "uptime",
        NB_MAC_ARQ=tmp_path / "mac",
    )["hwinfo"]
    assert hw["mac"] == "58-11-22-99-fc-6a"
    assert hw["dmi_uuid"] == "4c4c4544-0042-3010-8034-b4c04f4b4e31"
    assert hw["product_name"] == "OptiPlex 3090" and hw["product_vendor"] == "Dell Inc."
    assert hw["uptime_s"] == 1234
    assert abs(hw["last_boot"] - (time.time() - 1234)) < 3
    assert hw["hostname"]
    for campo in ("processor", "cores", "memtotal_mb"):
        assert campo in hw


def test_hardware_sem_os_arquivos_novos_nao_inventa_campo(tmp_path):
    hw = _parte(
        "10-hardware.sh",
        tmp_path,
        NB_DMI_DIR=tmp_path / "nao",
        NB_PROC_UPTIME=tmp_path / "nao",
        NB_MAC_ARQ=tmp_path / "nao",
    )["hwinfo"]
    for campo in ("mac", "dmi_uuid", "product_name", "uptime_s", "last_boot"):
        assert campo not in hw, campo


def test_o_relogio_do_agente_e_chave_de_topo(tmp_path):
    import time

    d = _parte("05-relogio.sh", tmp_path)
    assert abs(d["t_agent"] - time.time()) < 3


def test_o_status_inteiro_e_json_valido_com_o_relogio_no_topo(tmp_path):
    """O collect() concatena as partes com vírgula e envolve em chaves: uma
    parte que imprima uma chave escalar entra no topo sem mudar o agente."""
    import json
    import os
    import subprocess

    saidas = []
    for parte in sorted(PARTS.glob("*.sh")):
        r = subprocess.run(
            ["bash", str(parte)],
            capture_output=True,
            text=True,
            env={**os.environ, "NB_PROC_PRESSURE": str(tmp_path / "nao"), "NB_DMI_DIR": str(tmp_path / "nao"),
                 "NB_DISCO_HOME": str(tmp_path), "NB_DISCO_ROOT": str(tmp_path),
                 "NB_EDITORES_ARQ": str(tmp_path / "nao")},
            timeout=60,
        )
        assert r.returncode == 0, (parte.name, r.stderr)
        saidas.append(r.stdout.strip())
    status = json.loads("{" + ",".join(saidas) + "}")
    assert isinstance(status["t_agent"], int)
    for bloco in ("hwinfo", "sysresources", "sysdisk", "operations"):
        assert bloco in status
    assert "editors_time_since" in status["operations"]


def test_o_agente_diz_a_versao_e_o_que_sabe_medir(tmp_path):
    """A frota é mista (a camada chega por sede). O MOJ adivinhava o agente
    novo pela presença de `t_agent`; agora o agente se declara."""
    mac = tmp_path / "mac-icpc"
    mac.write_text("52-54-00-12-34-56\n")
    d = _parte("00-agente.sh", tmp_path, NB_AGENTE_DIR=PARTS.parent, NB_MAC_ARQ=mac)
    assert d["agent_version"] == (PARTS.parent / "VERSION").read_text().strip() != ""
    assert d["capabilities"] == ["psi", "oom", "idle", "skew", "editors_since", "ua_mac"]

    sem = _parte("00-agente.sh", tmp_path, NB_AGENTE_DIR=PARTS.parent, NB_MAC_ARQ=tmp_path / "nao")
    assert "ua_mac" not in sem["capabilities"]
    # sem o arquivo de versão a parte ainda imprime: uma parte vazia no começo
    # quebraria o JSON do status inteiro
    assert _parte("00-agente.sh", tmp_path, NB_AGENTE_DIR=tmp_path)["agent_version"] == ""


def test_cada_capacidade_anunciada_tem_quem_a_produza():
    """Anunciar o que nenhuma parte emite é mentir para quem integra."""
    produtor = {
        "psi": ("20-recursos.sh", "psi_mem"),
        "oom": ("20-recursos.sh", "oom_kills"),
        "idle": ("20-recursos.sh", "idle_s"),
        "skew": ("05-relogio.sh", "t_agent"),
        "editors_since": ("30-operacoes.sh", "editors_time_since"),
    }
    anunciadas = (PARTS / "00-agente.sh").read_text(encoding="utf-8")
    for cap, (arquivo, literal) in produtor.items():
        assert f'"{cap}"' in anunciadas
        assert literal in (PARTS / arquivo).read_text(encoding="utf-8"), (cap, arquivo)


def test_o_servidor_devolve_a_versao_do_agente(client, image_testes3):
    hm = {"X-NB-Machine-Key": image_testes3["machine_key"]}
    hi = {"Authorization": f"Bearer {image_testes3['token']}"}
    base = "/api/v1/site-images/testes3/machines"
    client.post(f"{base}/52-54-00-12-34-56/status",
                json={"agent_version": "2026.09.2", "capabilities": ["psi", "oom"], "t_agent": 1}, headers=hm)
    st = client.get(base, headers=hi).json()["machines"][0]["status"]
    assert st["agent_version"] == "2026.09.2" and st["capabilities"] == ["psi", "oom"]
