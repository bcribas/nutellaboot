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
