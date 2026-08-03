"""O elo entre o gerador do stuff e quem consome o valor do outro lado.

O formulário vira variáveis de shell no servidor (Python) e é lido por scripts
no cliente (sh). Os dois combinam um formato — separador de lista, aspas — em
arquivos diferentes, em linguagens diferentes, e até aqui **nada os
confrontava**: nenhum teste tocava `type: list`, e nenhum gerava o stuff para
dar `source` nele.

Foi por essa fresta que passaram dois defeitos ao mesmo tempo:

  * `INPUT_SOURCES` saía com espaço entre as tuplas, e `sources=[(…) (…)]` não
    é GVariant válido: o `dconf update` recusava o arquivo e, com ele, o
    `local.d` inteiro — teclado, página inicial e favoritos caíam juntos;
  * `FIREWALL_ALLOWLIST` saía com espaço, mas o laço do firewall usa `IFS=,` e
    cada item TEM um espaço dentro (`"nome ip"`). Com duas entradas, só a
    primeira era liberada — em silêncio. Na prova, é o servidor do BOCA fora
    do firewall.

Os dois só aparecem com **dois ou mais** itens: com um item os separadores dão
o mesmo texto, e o padrão do firewall tem exatamente um.

Por isso este arquivo faz o caminho todo: renderiza o stuff de verdade, dá
`source` com `sh`, roda o consumidor de verdade contra um `rootmnt` de mentira
e olha o que ficou no disco.
"""

import subprocess
from pathlib import Path

import pytest

from server.app import fsdb
from server.app.services import config, stuffgen
from server.app.services.default_schema import build_default_schema

REPO = Path(__file__).resolve().parents[1]
STUFF = REPO / "client" / "stuff"

DOIS_HOSTS = ["moj.naquadah.com.br 159.65.72.180", "boca-server 200.145.148.81"]
TRES_LAYOUTS = ["('xkb','br')", "('xkb','us')", "('xkb','latam')"]

GVARIANT = """
import json, sys
import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib
print(json.dumps(GLib.Variant.parse(GLib.VariantType(sys.argv[2]), sys.argv[1], None, None).unpack()))
"""


def gvariant(texto: str, tipo: str):
    """Passa o texto pelo parser do GLib — o MESMO que o dconf usa.

    Roda no python do sistema porque o `gi` não está no venv. Se não houver,
    o teste pula: conferir com o parser de verdade é o ponto, e uma reimplementação
    aqui provaria só que duas cópias do meu palpite concordam.
    """
    import json

    r = subprocess.run(
        ["/usr/bin/python3", "-c", GVARIANT, texto, tipo], capture_output=True, text=True
    )
    if "ModuleNotFoundError" in r.stderr:
        pytest.skip("sem gi no python do sistema para conferir o GVariant")
    assert r.returncode == 0, f"o dconf recusaria isto: {r.stderr.strip()}"
    return json.loads(r.stdout)


@pytest.fixture
def imagem(data_root):
    """Uma imagem com o esquema padrão e mais de um item em cada lista."""
    from server.app.services import store

    fsdb.write_json(data_root / "models" / "t" / "model.json", {"layers": []})
    fsdb.write_json(data_root / "models" / "t" / "schema.json", build_default_schema())
    store.create_site_image("sala1", "Sala 1", "t", unlocked=True)
    config.write_values(
        "sala1",
        {"FIREWALL_ALLOWLIST": DOIS_HOSTS, "INPUT_SOURCES": TRES_LAYOUTS},
        is_admin=True,
    )
    return "sala1"


def roda_consumidor(imagem, funcao, raiz: Path, extra: str = "") -> subprocess.CompletedProcess:
    """Gera o stuff, faz `source` nele e chama um dos módulos do postmount.

    É o stuff INTEIRO, como a máquina recebe: os módulos vêm concatenados
    dentro dele, então isto exercita exatamente o texto que vai para a sala.
    """
    texto = stuffgen.render(imagem)
    script = raiz.parent / "stuff.sh"
    script.write_text(texto)
    corpo = f"""
log_begin_msg() {{ :; }}
log_end_msg() {{ :; }}
log_warning_msg() {{ echo "WARN: $*" >&2; }}
log_failure_msg() {{ echo "FAIL: $*" >&2; }}
. "{script}"
rootmnt="{raiz}"
{extra}
{funcao}
"""
    return subprocess.run(["sh", "-c", corpo], capture_output=True, text=True)


@pytest.fixture
def raiz(tmp_path):
    r = tmp_path / "root"
    for d in (
        "usr/share/maratona-firewall/hosts",
        "etc/systemd/system",
        "etc/dconf/db/local.d/locks",
        "etc",
        "root",
    ):
        (r / d).mkdir(parents=True, exist_ok=True)
    (r / "etc/resolv.conf").write_text("nameserver 1.1.1.1\n")
    return r


# --- firewall: o item tem espaço dentro, então o separador não pode ser espaço


def test_todos_os_hosts_da_lista_sao_liberados(imagem, raiz):
    r = roda_consumidor(imagem, "nb3_post_firewall", raiz)
    assert r.returncode == 0, r.stderr
    hosts = {p.name: p.read_text().strip() for p in (raiz / "usr/share/maratona-firewall/hosts").iterdir()}
    assert hosts["moj.naquadah.com.br"] == "159.65.72.180"
    assert hosts["boca-server"] == "200.145.148.81", (
        "só a primeira entrada foi liberada — o separador do stuff não bate "
        "com o IFS do laço"
    )


def test_o_stuff_separa_a_lista_do_firewall_por_virgula(imagem):
    linha = [l for l in stuffgen.render(imagem).splitlines() if l.startswith("FIREWALL_ALLOWLIST=")][0]
    assert linha == (
        "FIREWALL_ALLOWLIST='moj.naquadah.com.br 159.65.72.180,boca-server 200.145.148.81'"
    ), linha


def test_host_com_barra_nao_escreve_fora_de_hosts(imagem, raiz, data_root):
    """O nome vira caminho de arquivo, como root, dentro do sistema montado.
    O servidor recusa o valor; isto é a segunda tranca, para um stuff gerado
    por uma versão anterior."""
    r = roda_consumidor(
        imagem,
        "nb3_post_firewall",
        raiz,
        extra='FIREWALL_ALLOWLIST="../../../etc/cron.d/pwn 1.2.3.4,ok.com 5.6.7.8"',
    )
    assert r.returncode == 0, r.stderr
    assert not (raiz / "etc/cron.d/pwn").exists()
    assert (raiz / "usr/share/maratona-firewall/hosts/ok.com").is_file()
    assert "invalid host" in r.stdout + r.stderr


# --- dconf: lista GVariant


def test_a_lista_de_teclados_e_gvariant_valido(imagem, raiz):
    r = roda_consumidor(imagem, "nb3_post_dconf", raiz)
    assert r.returncode == 0, r.stderr
    linha = [
        l
        for l in (raiz / "etc/dconf/db/local.d/80-keyboards").read_text().splitlines()
        if l.startswith("sources=")
    ][0]
    assert linha == "sources=[('xkb','br'),('xkb','us'),('xkb','latam')]", linha

    # é o mesmo parser que o dconf usa; com espaço entre as tuplas ele recusa
    assert gvariant(linha.split("=", 1)[1], "a(ss)") == [["xkb", "br"], ["xkb", "us"], ["xkb", "latam"]]


def test_aspa_na_pagina_inicial_nao_quebra_o_dconf(imagem, raiz):
    r = roda_consumidor(
        imagem, "nb3_post_dconf", raiz, extra="""DEFAULTBROWSERURL="https://x/?a='b'" """
    )
    assert r.returncode == 0, r.stderr
    texto = (raiz / "etc/dconf/db/local.d/90-browserurl").read_text()
    linha = [l for l in texto.splitlines() if l.startswith("homepage-url=")][0]

    assert gvariant(linha.split("=", 1)[1], "s") == "https://x/?a='b'"


# --- /etc/.nb3, que o agente carrega como root


def test_o_arquivo_do_agente_sobrevive_a_uma_aspa(imagem, raiz, tmp_path):
    """O /etc/.nb3 é `.`-sourced pelo agente COMO ROOT. Se um valor com aspa
    quebrar a linha, o que vem depois dela é comando."""
    marca = tmp_path / "executou-como-root"
    r = roda_consumidor(
        imagem,
        "nb3_post_secrets",
        raiz,
        extra=f"""LOCK_THEME="x'; touch {marca}; '" """,
    )
    assert r.returncode == 0, r.stderr

    lido = subprocess.run(
        ["sh", "-c", f'. "{raiz}/etc/.nb3"; printf %s "$NB_LOCK_THEME"'],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert lido.returncode == 0, lido.stderr
    assert lido.stdout == f"x'; touch {marca}; '"
    assert not marca.exists(), "o valor escapou das aspas e virou comando"


# --- o gerador em si


def test_lista_vazia_e_none_nao_viram_texto_estranho(data_root):
    assert stuffgen._render_value([]) == "''"
    assert stuffgen._render_value(None) == "''", "None virava a string 'None'"
    assert stuffgen._render_value(["a", "b"]) == "'a,b'"
    # um campo pode pedir espaço: o 60-polkit percorre NB_HIDE_DOCS_APPS com o
    # IFS padrão, e um separador global seria a mesma armadilha ao contrário
    assert stuffgen._render_value(["a", "b"], " ") == "'a b'"


def test_a_validacao_vale_para_modelo_que_ja_existia(data_root, imagem):
    """O schema.json é gravado quando o modelo nasce e nunca mais revisto. Sem
    herdar os metadados de formato do esquema padrão, uma regra nova só valeria
    para modelos criados depois dela — e os que estão em produção seguiriam
    aceitando o valor que quebra a máquina."""
    from server.app.services.config import ConfigError

    esquema = build_default_schema()
    for f in esquema["fields"]:
        f.pop("item_pattern", None)  # como um schema.json gravado antes da regra
        f.pop("sep", None)
    fsdb.write_json(data_root / "models" / "t" / "schema.json", esquema)

    with pytest.raises(ConfigError, match="formato inválido"):
        config.write_values(
            "sala1", {"FIREWALL_ALLOWLIST": ["../../etc/cron.d/x 1.2.3.4"]}, is_admin=True
        )


def test_o_esquema_manda_no_separador(data_root, imagem):
    esquema = build_default_schema()
    for f in esquema["fields"]:
        if f["key"] == "INPUT_SOURCES":
            f["sep"] = " "
    fsdb.write_json(data_root / "models" / "t" / "schema.json", esquema)
    linha = [l for l in stuffgen.render(imagem).splitlines() if l.startswith("INPUT_SOURCES=")][0]
    assert "') ('" in linha, linha
