"""A configuração do navegador, que é uma trinca fácil de desfazer sem notar.

O `firefox.cfg` só é lido se um `.js` em `defaults/pref/` disser o nome dele; o
`{{ UIDBROWSER }}` dentro dele só vira alguma coisa se o script de `rc.local.d`
apontar para o mesmo caminho. Três arquivos que precisam concordar — e no nb2
isso era mantido à mão, em lugares diferentes, até o `.cfg` sumir junto com a
camada `/opt/firefox` e ninguém perceber.

`general.useragent.override` **não** é alcançável por `policies.json` (a
política `Preferences` só aceita `general.autoScroll` e `general.smoothScroll`
de `general.*`), então o autoconfig não é uma alternativa: é o único caminho.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "client" / "stuff" / "60-postmount.d" / "65-firefox.sh"
HEADER = REPO / "client" / "stuff" / "00-header.sh"


@pytest.fixture
def raiz(tmp_path):
    """Um / de mentira com o que a imagem de verdade tem."""
    r = tmp_path / "root"
    for d in (
        "usr/bin",
        "usr/lib/firefox-esr/defaults/pref",
        "usr/lib/firefox-esr/distribution",
        "etc/rc.local.d",
        "etc/alternatives",
        "etc/dconf/db/local.d/locks",
    ):
        (r / d).mkdir(parents=True)
    (r / "usr/bin/firefox-esr").touch()
    (r / "etc/dconf/db/local.d/50-favorites").write_text(
        "[org/gnome/shell]\nfavorite-apps=['epiphany.desktop', 'org.gnome.Nautilus.desktop']\n"
    )
    (r / "usr/lib/firefox-esr/application.ini").write_text("[App]\nVersion=140.13.0\n")
    return r


def roda(raiz, url="https://moj.naquadah.com.br"):
    script = f"""
log_begin_msg() {{ :; }}
log_end_msg() {{ :; }}
. {HEADER}
. {SCRIPT}
rootmnt="{raiz}"
DEFAULTBROWSERURL='{url}'
nb3_post_firefox
"""
    r = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


# --- a trinca do autoconfig ---


def test_o_autoconfig_aponta_para_o_cfg_que_e_gerado(raiz):
    roda(raiz)
    pref = (raiz / "usr/lib/firefox-esr/defaults/pref/autoconfig.js").read_text()
    nome = re.search(r'general\.config\.filename",\s*"([^"]+)"', pref).group(1)
    assert (raiz / "usr/lib/firefox-esr" / nome).is_file(), (
        f"o autoconfig pede {nome}, que ninguém gera"
    )
    # sem estes dois, o Firefox espera um .cfg ofuscado e ignora o texto puro
    assert "general.config.obscure_value" in pref
    assert "general.config.sandbox_enabled" in pref


def test_a_primeira_linha_do_cfg_e_comentario(raiz):
    """O Firefox descarta a primeira linha do .cfg por desenho. Uma diretiva
    ali some sem aviso nenhum."""
    roda(raiz)
    primeira = (raiz / "usr/lib/firefox-esr/firefox.cfg").read_text().splitlines()[0]
    assert primeira.startswith("//"), primeira


def test_o_carimbo_do_user_agent_e_preenchido_no_boot(raiz):
    """O `.cfg` sai com um placeholder; quem o troca é o rc.local.d, porque a
    identidade da máquina só existe com o sistema rodando."""
    roda(raiz)
    cfg = (raiz / "usr/lib/firefox-esr/firefox.cfg").read_text()
    assert "{{ UIDBROWSER }}" in cfg
    assert "general.useragent.override" in cfg

    rc = (raiz / "etc/rc.local.d/50-firefox-default").read_text()
    assert "{{ UIDBROWSER }}" in rc, "o rc.local.d não troca o placeholder"
    # e mexe no MESMO arquivo que foi gerado
    alvo = re.search(r"sed -i .*\+g\" (\S+)", rc).group(1)
    assert alvo == "/usr/lib/firefox-esr/firefox.cfg", alvo


def test_o_user_agent_leva_sede_maquina_e_boot(raiz):
    roda(raiz)
    rc = (raiz / "etc/rc.local.d/50-firefox-default").read_text()
    for insumo in ("/etc/imageroot-icpc", "/home/.machine-id", "/home/.machine-id-boot"):
        assert insumo in rc, insumo
    assert "MLinux/" in rc


def test_a_versao_do_firefox_sai_da_instalacao(raiz):
    """Estava `Firefox/148.0` fixo, e a imagem traz ESR 140."""
    roda(raiz)
    rc = (raiz / "etc/rc.local.d/50-firefox-default").read_text()
    assert "application.ini" in rc
    assert "148.0" not in rc


# --- as políticas ---


def test_a_politica_vai_nos_caminhos_que_esta_build_le(raiz):
    """`MOZ_APP_NAME=firefox-esr` faz o caminho de sistema ser
    /etc/firefox-esr/policies/. O script escrevia em /etc/firefox/policies/,
    que não existe nesta imagem — a política inteira era ignorada."""
    roda(raiz)
    assert (raiz / "etc/firefox-esr/policies/policies.json").is_file()
    assert (raiz / "usr/lib/firefox-esr/distribution/policies.json").is_file()
    assert not (raiz / "etc/firefox/policies/policies.json").exists()


def test_a_politica_e_json_valido_e_leva_a_pagina_inicial(raiz):
    roda(raiz)
    d = json.loads((raiz / "etc/firefox-esr/policies/policies.json").read_text())
    assert d["policies"]["Homepage"]["URL"] == "https://moj.naquadah.com.br"
    assert d["policies"]["Homepage"]["Locked"] is True
    assert d["policies"]["BlockAboutConfig"] is True


def test_aspas_na_pagina_inicial_nao_quebram_o_json(raiz):
    """JSON inválido o Firefox ignora em silêncio: a máquina ficaria sem
    política nenhuma, e ninguém saberia até alguém abrir about:config."""
    roda(raiz, url='https://x/?a="b"&c=\\d')
    d = json.loads((raiz / "etc/firefox-esr/policies/policies.json").read_text())
    assert d["policies"]["Homepage"]["URL"] == 'https://x/?a="b"&c=\\d'


# --- o navegador padrão ---


def test_troca_o_navegador_padrao(raiz):
    roda(raiz)
    for alt in ("x-www-browser", "gnome-www-browser"):
        assert (raiz / "etc/alternatives" / alt).resolve().name == "firefox-esr"
    favoritos = (raiz / "etc/dconf/db/local.d/50-favorites").read_text()
    assert "firefox-esr.desktop" in favoritos and "epiphany.desktop" not in favoritos


def test_o_epiphany_tambem_recebe_o_carimbo(raiz):
    """Ele continua instalado: quem o abrir submete sem identificação. O nb2
    carimbava os dois; o nb3 tinha perdido este."""
    roda(raiz)
    rc = (raiz / "etc/rc.local.d/55-epiphany-uid").read_text()
    assert "user-agent" in rc and "MLinux/" in rc
    assert "/etc/imageroot-icpc" in rc


def test_sem_firefox_instalado_nao_faz_nada(tmp_path):
    """A guarda estava comentada: numa imagem sem o ESR, o script escrevia
    configuração para um navegador que não existe."""
    vazia = tmp_path / "semff"
    (vazia / "etc").mkdir(parents=True)
    roda(vazia)
    assert not (vazia / "etc/firefox-esr").exists()
    assert not (vazia / "usr").exists()
