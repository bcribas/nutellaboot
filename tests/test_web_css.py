"""Toda classe que uma tela usa existe no CSS que ELA carrega.

O painel de camadas do /admin/ era um `div.detail`, classe definida só no CSS
do laboratório (que o /admin/ não carrega): caía sem estilo no fim da página, e
cada clique empilhava mais um. `label.fld` (28 usos no /admin/) morava no CSS
da home, as abas não marcavam a ativa, e aviso `.warn` saía como texto comum.
Nenhum teste via isso: o erro é visual e não quebra nada no console.

O teste lê o HTML da tela, os módulos que ela carrega (seguindo os imports) e
os CSS ligados a ela, e compara. Classe que só serve de gancho para o JS entra
em GANCHOS, com o motivo.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
TELAS = sorted(p for p in WEB.rglob("index.html") if "locales" not in p.parts)

GANCHOS = {
    "usb": "o bloco do pendrive (common/usb.js) se reconhece por ela; o visual vem das peças de dentro",
    "fview-mode": "o seletor da visão da frota (common/fleetview.js) acha o próprio <select> por ela",
}

TOKEN = re.compile(r"^[a-z][a-z0-9-]*$")


def _caminho(base: Path, ref: str) -> Path:
    return (WEB / ref.lstrip("/")) if ref.startswith("/") else (base / ref)


def definidas(html_path: Path, html: str) -> set[str]:
    textos = [_caminho(html_path.parent, href).read_text(encoding="utf-8")
              for href in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)]
    textos += re.findall(r"<style>(.*?)</style>", html, re.S)
    nomes: set[str] = set()
    for texto in textos:
        texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
        for seletor in re.findall(r"([^{}]+)\{", texto):
            nomes |= set(re.findall(r"\.([a-zA-Z][\w-]*)", seletor))
    return nomes


def modulos(html_path: Path, html: str) -> list[Path]:
    fila = [_caminho(html_path.parent, src) for src in re.findall(r'<script[^>]+src="([^"]+)"', html)]
    vistos: list[Path] = []
    while fila:
        p = fila.pop().resolve()
        if p in vistos or not p.is_file():
            continue
        vistos.append(p)
        for imp in re.findall(r"""^\s*import\s[^;]*?from\s+["']([^"']+)["']""", p.read_text(encoding="utf-8"), re.M):
            fila.append(_caminho(p.parent, imp))
    return vistos


def _literais(expressao: str) -> list[str]:
    """Os textos de classe de uma expressão: os literais, menos os que só
    aparecem numa comparação (`estado === "acked" ? "ok" : ""`)."""
    expressao = re.sub(r"""(===|!==|==|!=)\s*(["'`])[^"'`]*\2""", " ", expressao)
    expressao = re.sub(r"""(["'`])[^"'`]*\1\s*(===|!==|==|!=)""", " ", expressao)
    partes = re.findall(r'"([^"]*)"', expressao) + re.findall(r"'([^']*)'", expressao)
    partes += [re.sub(r"\$\{[^}]*\}", " ", x) for x in re.findall(r"`([^`]*)`", expressao)]
    return partes


def _atributo(valor: str) -> str:
    # `${...}` inteiro some; um `${` cortado pela aspa de dentro corta o resto
    valor = re.sub(r"\$\{[^}]*\}", " ", valor)
    return valor.split("${", 1)[0]


def usadas(html_path: Path, html: str) -> dict[str, str]:
    achados: dict[str, str] = {}

    def junta(texto: str, origem: str) -> None:
        for token in texto.split():
            if TOKEN.match(token):
                achados.setdefault(token, origem)

    for valor in re.findall(r'class="([^"]*)"', html):
        junta(_atributo(valor), html_path.name)
    for js in modulos(html_path, html):
        texto = js.read_text(encoding="utf-8")
        for valor in re.findall(r'class="([^"]*)"', texto):
            junta(_atributo(valor), js.name)
        for expr in re.findall(r"\bclass:\s*([^,}\n]*)", texto) + re.findall(r"className\s*=\s*([^;\n]*)", texto):
            for literal in _literais(expr):
                junta(literal, js.name)
        for valor in re.findall(r'classList\.(?:add|remove|toggle)\(\s*"([^"]+)"', texto):
            junta(valor, js.name)
    return achados


def faltando(html_path: Path, extra_js: str = "") -> dict[str, str]:
    html = html_path.read_text(encoding="utf-8")
    usos = usadas(html_path, html)
    if extra_js:
        for expr in re.findall(r"\bclass:\s*([^,}\n]*)", extra_js):
            for literal in _literais(expr):
                for token in literal.split():
                    usos.setdefault(token, "sintético")
    nomes = definidas(html_path, html)
    return {k: v for k, v in usos.items() if k not in nomes and k not in GANCHOS}


@pytest.mark.parametrize("tela", TELAS, ids=lambda p: str(p.parent.relative_to(WEB)) or "home")
def test_toda_classe_usada_existe_no_css_da_tela(tela):
    falta = faltando(tela)
    assert falta == {}, f"classes sem CSS em {tela.parent.name}: {sorted(falta.items())}"


def test_o_verificador_acusa_o_painel_sem_estilo():
    """O defeito que o motivou: um `div.detail` no /admin/, que só o CSS do
    laboratório define. Tem de ser acusado, e só ele."""
    falta = faltando(WEB / "admin" / "index.html", extra_js='el("div", { class: "detail" })')
    assert set(falta) == {"detail"}, falta


def test_ganchos_sao_so_ganchos():
    """Um gancho que ganhou estilo no CSS comum sai da lista (senão ela vira
    esconderijo). O CSS de uma tela pode usar o mesmo nome com outro sentido:
    `.mcard.usb` no laboratório é o destaque do alerta de pendrive."""
    comum = (WEB / "common" / "style.css").read_text(encoding="utf-8")
    comum = re.sub(r"/\*.*?\*/", "", comum, flags=re.S)
    nomes = set()
    for seletor in re.findall(r"([^{}]+)\{", comum):
        nomes |= set(re.findall(r"\.([a-zA-Z][\w-]*)", seletor))
    assert not (set(GANCHOS) & nomes)
