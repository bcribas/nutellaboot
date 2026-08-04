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


# --- o carimbo da sede no papel de parede ---


def test_o_papel_de_parede_guarda_o_original_e_carimba_a_copia(imagem, raiz):
    """Carimbar sobre o carimbado empilharia tarja sobre tarja a cada boot — e
    a home é persistente, então isso se acumularia até a tela toda ser tarja."""
    (raiz / "home").mkdir(parents=True, exist_ok=True)
    (raiz / "usr/share/maratona-background").mkdir(parents=True, exist_ok=True)
    (raiz / "etc/rc.local.d").mkdir(parents=True, exist_ok=True)

    texto = (REPO / "client" / "stuff" / "60-postmount.d" / "70-wallpaper.sh").read_text()
    assert ".wallpaper-orig.png" in texto, "o original precisa sobreviver ao carimbo"
    # o que o dconf aponta é o carimbado
    assert "ln -s /home/.wallpaper.png" in texto


def test_o_carimbo_e_desenhado_com_o_sistema_rodando():
    """No initrd não há python nem fonte nenhuma; quem tem Pillow é a máquina."""
    texto = (REPO / "client" / "stuff" / "60-postmount.d" / "70-wallpaper.sh").read_text()
    assert "rc.local.d/60-wallpaper-stamp" in texto
    assert "imageroot-icpc" in texto, "a sede vem do arquivo que o 15-machineid grava"
    assert "PIL" in texto


# --- o nome de exibição da sede ---


def test_o_stuff_leva_o_nome_de_exibicao(imagem):
    """O nome vem por aqui, e não do pendrive: numa imagem genérica com o
    IMAGEROOT digitado à mão — que é o fluxo previsto — o pendrive não teria
    nome nenhum para dar."""
    linhas = [l for l in stuffgen.render(imagem).splitlines() if l.startswith("NB_SITE_NAME=")]
    assert linhas, "o stuff não diz o nome da sede"
    assert "Sala 1" in linhas[0], linhas[0]


def test_o_nome_da_sede_chega_ao_disco(imagem, raiz):
    """Arquivo separado do imageroot-icpc: aquele é lido inteiro com `$(< ...)`
    pelo user-agent do Firefox e do Epiphany, e uma segunda linha o
    envenenaria."""
    r = roda_consumidor(
        imagem, "nb3_post_machineid", raiz, extra=f'mkdir -p "{raiz}/var/lib/dbus" "{raiz}/home"'
    )
    assert r.returncode == 0, r.stderr
    assert (raiz / "etc/sitename-icpc").read_text().strip() == "Sala 1"
    assert (raiz / "etc/imageroot-icpc").read_text().strip() == imagem


def test_o_carimbo_fica_fora_da_dock_do_gnome():
    """A dock fica na esquerda e, com ícone de 48 px, ocupa uns 76: o texto
    começava em `faixa // 2` (~45 px em 1080p) e ficava por baixo dela."""
    texto = (REPO / "client" / "stuff" / "60-postmount.d" / "70-wallpaper.sh").read_text()
    assert "sitename-icpc" in texto, "o carimbo não mostra o nome de exibição"
    assert "margem = max(96," in texto, "a margem da dock sumiu"
    assert "(faixa // 2," not in texto, "o texto voltou a começar por baixo da dock"


def test_o_tema_escuro_tambem_recebe_o_papel_de_parede(imagem, raiz):
    """A base trava `picture-uri` mas deixa `picture-uri-dark` no padrão do
    Ubuntu: em tema escuro apareceria o fundo da Canonical, e com ele sumiria
    o carimbo da sede."""
    r = roda_consumidor(imagem, "nb3_post_dconf", raiz)
    assert r.returncode == 0, r.stderr
    arq = raiz / "etc/dconf/db/local.d/91-wallpaper-dark"
    assert arq.is_file()
    texto = arq.read_text()
    assert "picture-uri-dark" in texto
    assert "maratona-common-wallpaper.png" in texto
    assert (raiz / "etc/dconf/db/local.d/locks/91-wallpaper-dark").is_file()


# --- a senha de root chega ao /etc/shadow ------------------------------------


def test_a_senha_de_root_vira_a_linha_do_shadow(imagem, raiz):
    """O consumidor existe desde sempre (`60-polkit.sh` reescreve a linha do
    root a partir de NB_ROOT_PW_HASH) e o produtor nunca existiu. Este teste
    junta os dois: define a senha no modelo e olha o shadow que sobra."""
    from server.app.services import store

    store.set_schema_field("t", "ROOT_PASSWORD", {"default": "senha-da-prova", "locked": True})
    (raiz / "etc").mkdir(parents=True, exist_ok=True)
    (raiz / "etc/shadow").write_text("root:!:20000:0:99999:7:::\nicpc:*:20000:0:99999:7:::\n")
    (raiz / "etc/polkit-1/localauthority/90-mandatory.d").mkdir(parents=True, exist_ok=True)
    (raiz / "etc/sudoers").write_text("")

    r = roda_consumidor(imagem, "nb3_post_polkit", raiz)
    assert r.returncode == 0, r.stderr

    linhas = (raiz / "etc/shadow").read_text().splitlines()
    root = [l for l in linhas if l.startswith("root:")]
    assert len(root) == 1, linhas
    assert root[0].split(":")[1].startswith("$6$"), root[0]
    # e o resto do arquivo sobrevive: reescrever o shadow inteiro apagaria o
    # usuário que a prova usa
    assert any(l.startswith("icpc:") for l in linhas)


def test_sem_senha_o_shadow_nao_e_tocado(imagem, raiz):
    original = "root:!:20000:0:99999:7:::\n"
    (raiz / "etc").mkdir(parents=True, exist_ok=True)
    (raiz / "etc/shadow").write_text(original)
    (raiz / "etc/polkit-1/localauthority/90-mandatory.d").mkdir(parents=True, exist_ok=True)
    (raiz / "etc/sudoers").write_text("")

    r = roda_consumidor(imagem, "nb3_post_polkit", raiz)
    assert r.returncode == 0, r.stderr
    assert (raiz / "etc/shadow").read_text() == original


# --- o wifi do pendrive vira perfil do NetworkManager ------------------------
#
# O mesmo `wifi.conf` alimenta o wpa_supplicant do initrd (para o boot) e os
# perfis do NetworkManager (para o sistema rodando). É o que substitui a camada
# `wifis.squash`, que tinha 4 kB e três redes fixas sem relação com a sede.
#
# O módulo existia, era chamado, e NENHUM teste jamais o executou.

WIFI = "\t".join(["ICPC-BR", "senha-da-sede"]) + "\n" \
    + "ICPC-ABERTA\t\n" \
    + "\t".join(["oculta", "s3nh4", "hidden"]) + "\n" \
    + "# comentário\n"


def com_wifi(tmp_path, conteudo=WIFI):
    """O wifi.conf onde o initrd o deixa: copiado do pendrive para a RAM."""
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    (run / "wifi.conf").write_text(conteudo, encoding="utf-8")
    return f'NB_RUN="{run}"'


def perfis(raiz):
    d = raiz / "etc/NetworkManager/system-connections"
    return {p.stem: p.read_text(encoding="utf-8") for p in d.iterdir()} if d.is_dir() else {}


def test_a_rede_com_senha_vira_perfil_do_networkmanager(imagem, raiz, tmp_path):
    r = roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=com_wifi(tmp_path))
    assert r.returncode == 0, r.stderr
    p = perfis(raiz)
    assert set(p) == {"ICPC-BR", "ICPC-ABERTA", "oculta"}, sorted(p)

    texto = p["ICPC-BR"]
    assert "id=ICPC-BR" in texto and "type=wifi" in texto
    assert "key-mgmt=wpa-psk" in texto
    assert "psk=senha-da-sede" in texto
    assert "method=auto" in texto


def test_a_rede_aberta_nao_ganha_seguranca(imagem, raiz, tmp_path):
    """Com `[wifi-security]` sem senha o NetworkManager recusa o perfil, e a
    rede aberta simplesmente não conecta."""
    roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=com_wifi(tmp_path))
    texto = perfis(raiz)["ICPC-ABERTA"]
    assert "[wifi-security]" not in texto
    assert "psk=" not in texto


def test_a_rede_oculta_e_marcada(imagem, raiz, tmp_path):
    """Sem `hidden=true` a rede não é encontrada — o mesmo motivo do
    `scan_ssid=1` no wpa_supplicant."""
    roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=com_wifi(tmp_path))
    assert "hidden=true" in perfis(raiz)["oculta"]


def test_o_perfil_nao_e_legivel_por_qualquer_um(imagem, raiz, tmp_path):
    """A senha da rede da sede está lá dentro, em claro — é assim que o
    NetworkManager guarda, e por isso o modo importa."""
    roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=com_wifi(tmp_path))
    arq = raiz / "etc/NetworkManager/system-connections/ICPC-BR.nmconnection"
    assert oct(arq.stat().st_mode)[-3:] == "600"


def test_o_uuid_e_o_mesmo_em_dois_boots(imagem, raiz, tmp_path):
    """UUID novo a cada boot faz o NetworkManager acumular um perfil duplicado
    por boot, e a home é persistente."""
    extra = com_wifi(tmp_path)
    roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=extra)
    primeiro = perfis(raiz)["ICPC-BR"]
    roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=extra)
    assert perfis(raiz)["ICPC-BR"] == primeiro
    assert len(perfis(raiz)) == 3


def test_ssid_com_barra_nao_escreve_fora_do_diretorio(imagem, raiz, tmp_path):
    """O SSID vira nome de arquivo, escrito como root dentro do sistema que a
    sala monta. O arquivo é editado à mão pela sede: errar aqui é mais fácil
    que ser atacado."""
    ruim = "../../../etc/cron.d/pwn\tsenha\nboa\tsenha2\n"
    r = roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=com_wifi(tmp_path, ruim))
    assert r.returncode == 0, r.stderr
    assert not (raiz / "etc/cron.d/pwn").exists()
    assert set(perfis(raiz)) == {"boa"}
    assert "invalid SSID" in r.stdout + r.stderr


def test_sem_wifi_conf_nao_escreve_nada(imagem, raiz, tmp_path):
    """Pendrive sem redes é o padrão de fábrica: o `nb3-genusb` só embarca os
    comentários do exemplo."""
    r = roda_consumidor(imagem, "nb3_post_nm_wifi", raiz, extra=com_wifi(tmp_path, "# só comentário\n"))
    assert r.returncode == 0, r.stderr
    assert perfis(raiz) == {}
