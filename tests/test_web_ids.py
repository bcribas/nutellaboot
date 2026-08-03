"""Os ids que o JavaScript procura precisam existir no HTML da mesma tela.

Este teste existe porque `$("#naoexiste").onclick = ...` estoura em tempo de
execução e derruba o resto do `main()` — a tela abre em branco, sem erro
visível para quem está operando. Renomear ou remover um id no HTML é
exatamente o tipo de coisa que passa despercebida numa reorganização.

Não substitui abrir a tela no navegador; pega a classe de erro que aparece
depois, quando ninguém está olhando.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"

# ids criados em tempo de execução (não estão no HTML de propósito)
DINAMICOS: dict[str, set[str]] = {}


def paginas() -> list[tuple[Path, Path]]:
    """(html, js) de cada tela. A home é web/index.html + web/index.js; as
    demais são web/<tela>/index.html + web/<tela>/app.js."""
    out = [(WEB / "index.html", WEB / "index.js")]
    for d in sorted(WEB.iterdir()):
        if (d / "index.html").is_file() and (d / "app.js").is_file():
            out.append((d / "index.html", d / "app.js"))
    return out


def ids_no_html(html: Path) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html.read_text(encoding="utf-8")))


def ids_procurados(js: Path) -> set[str]:
    texto = js.read_text(encoding="utf-8")
    # $("#foo") e document.getElementById("foo")
    achados = set(re.findall(r'\$\(\s*"#([A-Za-z0-9_-]+)"', texto))
    achados |= set(re.findall(r'getElementById\(\s*"([A-Za-z0-9_-]+)"', texto))
    return achados


@pytest.mark.parametrize("html,js", paginas(), ids=lambda p: p.parent.name or p.name)
def test_ids_do_js_existem_no_html(html, js):
    faltando = ids_procurados(js) - ids_no_html(html) - DINAMICOS.get(html.parent.name, set())
    assert faltando == set(), f"{js.relative_to(REPO)} procura ids que {html.name} não tem: {sorted(faltando)}"


def test_console_tem_os_elementos_da_secao_de_modelos():
    """A seção de Modelos é a novidade do console; se algum campo sumir, a
    criação de modelo para de funcionar sem erro na tela."""
    ids = ids_no_html(WEB / "admin" / "index.html")
    assert {"mod_name", "mod_desc", "mod_from", "mod_create", "modlist", "modpanel"} <= ids


def test_painel_do_laboratorio_tem_a_faixa_de_alerta():
    """A faixa é o ponto inteiro do alerta de pendrive: sem ela, o evento
    chega ao servidor e ninguém vê."""
    ids = ids_no_html(WEB / "hotconfig" / "index.html")
    assert "alertbar" in ids
    assert "soundbtn" in ids

    css = (WEB / "hotconfig" / "lab.css").read_text(encoding="utf-8")
    assert ".alertbar" in css
    assert "position: sticky" in css, "a faixa tem que ficar visível ao rolar a lista"
    assert "prefers-reduced-motion" in css, (
        "quem configurou o sistema para não animar não pode levar uma faixa piscando"
    )
    assert ".mcard.usb" in css, "o card da máquina também precisa se destacar"


def test_som_do_alerta_nao_depende_de_arquivo_externo():
    """As páginas publicadas rodam sob uma política de conteúdo que bloqueia
    recurso de outro host; um .mp3 externo simplesmente não tocaria."""
    app = (WEB / "hotconfig" / "app.js").read_text(encoding="utf-8")
    assert "AudioContext" in app
    for proibido in (".mp3", ".wav", ".ogg", "new Audio("):
        assert proibido not in app, proibido


def test_alerta_chega_sem_esperar_o_agrupamento():
    """Os demais eventos passam por um debounce de 400 ms; o alerta não, porque
    esse é o intervalo entre espetar um pendrive e o fiscal ver."""
    app = (WEB / "hotconfig" / "app.js").read_text(encoding="utf-8")
    assert 'addEventListener("alert.raised"' in app


@pytest.mark.parametrize("secao", ["invites", "requests_admin", "publish_section", "bulk"])
def test_console_marca_o_que_e_so_da_administracao(secao):
    """Sub-admin não pode ver convites, pedidos, publicação nem criação em
    massa — o JS esconde pelo atributo, então ele precisa estar no cartão."""
    html = (WEB / "admin" / "index.html").read_text(encoding="utf-8")
    # do último <div class="card... antes do título até o título: é a abertura
    # do cartão que contém esta seção
    antes = html.split(f'<h2 data-i18n="{secao}">', 1)[0]
    abertura = antes.rsplit("<div class=", 1)[-1]
    assert "data-admin-only" in abertura, f"o cartão de {secao} precisa de data-admin-only"
