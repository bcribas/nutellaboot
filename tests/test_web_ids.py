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
    demais são web/<tela>/index.html + CADA .js de web/<tela>/ (as telas
    grandes são divididas em módulos, e um id procurado num módulo que não
    fosse conferido voltaria a ser a tela em branco sem erro)."""
    out = [(WEB / "index.html", WEB / "index.js")]
    for d in sorted(WEB.iterdir()):
        if (d / "index.html").is_file() and (d / "app.js").is_file():
            out += [(d / "index.html", js) for js in sorted(d.glob("*.js"))]
    return out


def ids_no_html(html: Path) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html.read_text(encoding="utf-8")))


def ids_procurados(js: Path) -> set[str]:
    texto = js.read_text(encoding="utf-8")
    # $("#foo") e document.getElementById("foo")
    achados = set(re.findall(r'\$\(\s*"#([A-Za-z0-9_-]+)"', texto))
    achados |= set(re.findall(r'getElementById\(\s*"([A-Za-z0-9_-]+)"', texto))
    return achados


@pytest.mark.parametrize("html,js", paginas(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_ids_do_js_existem_no_html(html, js):
    faltando = ids_procurados(js) - ids_no_html(html) - DINAMICOS.get(html.parent.name, set())
    assert faltando == set(), f"{js.relative_to(REPO)} procura ids que {html.name} não tem: {sorted(faltando)}"


def test_o_console_cria_modelo_com_nome_descricao_e_origem():
    """Criar e duplicar modelo são o mesmo diálogo; se um campo sumir do
    corpo, a criação para de copiar camadas e formulário sem erro na tela."""
    js = (WEB / "admin" / "modelo.js").read_text(encoding="utf-8")
    trecho = js.split('api.post("/api/v1/models"', 1)[1].split(")", 1)[0]
    for campo in ("name:", "description:", "from:"):
        assert campo in trecho, campo


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


@pytest.mark.parametrize(
    "aba,so_admin",
    [("imagens", False), ("modelos", False), ("camadas", False), ("pessoas", True), ("chaves", True), ("sistema", True)],
)
def test_console_marca_o_que_e_so_da_administracao(aba, so_admin):
    """Sub-admin não vê convites, pedidos, chaves, publicação nem auditoria: a
    aba some (data-admin-only) E o roteador não a abre (`admin: true`), para o
    endereço digitado à mão também voltar à aba padrão."""
    html = (WEB / "admin" / "index.html").read_text(encoding="utf-8")
    link = re.search(rf'<a href="#{aba}"[^>]*>', html)
    assert link, f"a aba {aba} sumiu"
    assert ("data-admin-only" in link.group(0)) is so_admin
    rotas = (WEB / "admin" / "rotas.js").read_text(encoding="utf-8")
    assert re.search(rf"\b{aba}: \{{ admin: {'true' if so_admin else 'false'},", rotas), aba
    assert "ROTAS[aba].admin" in rotas, "o roteador tem de consultar a marca"


def _imports(js: Path) -> list[str]:
    return re.findall(r'''^\s*import\s[^;]*?from\s+["\']([^"\']+)["\']''', js.read_text(encoding="utf-8"), re.M)


def test_modulos_importados_existem():
    """Import de módulo que não existe é tela em branco, sem erro para quem
    opera: o navegador nem começa a rodar o app.js."""
    ruins = []
    for js in WEB.rglob("*.js"):
        for alvo in _imports(js):
            caminho = WEB / alvo.lstrip("/") if alvo.startswith("/") else (js.parent / alvo)
            if not caminho.resolve().is_file():
                ruins.append(f"{js.relative_to(WEB)} importa {alvo}")
    assert ruins == []


def test_nenhum_import_default():
    """O no-undef caseiro (test_web_js) só entende `import { a, b }` e
    `import * as x`: um `import x from` passaria batido e esconderia erro."""
    ruins = []
    for js in WEB.rglob("*.js"):
        for linha in js.read_text(encoding="utf-8").splitlines():
            if re.match(r"\s*import\s+[A-Za-z_$][\w$]*\s*(,|from)", linha):
                ruins.append(f"{js.relative_to(WEB)}: {linha.strip()}")
    assert ruins == []
