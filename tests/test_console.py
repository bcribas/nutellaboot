"""O console de administração tem três modos, e só três: lista, página de
detalhe e diálogo (para confirmar, criar, escolher e mostrar segredo).

A tela antiga chegou a 15 cartões numa página, 9 botões por linha de imagem,
quatro construtores de diálogo copiados um do outro, `prompt()`/`confirm()`
do navegador, um painel solto no fim da página (com o CSS de outra tela) e um
"cartão de credenciais" enfiado no topo por seis caminhos. Cada remendo
acrescentava mais um jeito. Estes testes seguram a porta.
"""

import re
from pathlib import Path

from tests.test_web_js import tirar_nao_codigo

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
ADMIN = sorted((WEB / "admin").glob("*.js"))


def _codigo(p: Path) -> str:
    return tirar_nao_codigo(p.read_text(encoding="utf-8"))


def test_o_console_nao_pergunta_pelo_navegador():
    """prompt(), confirm() e alert() fogem do diálogo comum: sem estilo, sem
    tradução, sem "digite para confirmar", e um prompt de "três números" era o
    editor de cotas."""
    for p in ADMIN:
        achados = re.findall(r"\b(prompt|confirm|alert)\s*\(", _codigo(p))
        assert achados == [], f"{p.name}: {achados}"


def test_dialog_so_nasce_no_dialogo_comum():
    """Um lugar só cria <dialog>: web/common/dialogo.js. Eram quatro."""
    for p in sorted(WEB.rglob("*.js")):
        if p.name == "dialogo.js" or "locales" in p.parts:
            continue
        codigo = _codigo(p)
        assert not re.search(r"""(createElement|el)\(\s*["']dialog["']""", p.read_text(encoding="utf-8")), p
        assert "showModal(" not in codigo or p.parent.name == "admin" and p.name == "chaves.js", (
            f"{p.relative_to(WEB)}: só o diálogo comum (e o reauth estático) abre modal"
        )


def test_o_console_nao_enfia_nada_fora_da_pagina():
    """O cartão de credenciais era enfiado no topo do <main> (longe do botão,
    empilhando) e o painel de camadas no fim do <body> (sem estilo): o que o
    console mostra fica na página do objeto ou num diálogo."""
    for p in ADMIN:
        codigo = _codigo(p)
        assert 'querySelector("main")' not in p.read_text(encoding="utf-8"), p.name
        assert "document.body.append" not in codigo, p.name
        assert '"detail"' not in p.read_text(encoding="utf-8"), f"{p.name}: div.detail é do laboratório"


def test_innerhtml_no_console_so_para_limpar():
    """Texto de fora (nome de sede, pedido de um anônimo, vendor de alerta)
    entra por textContent/el(). Sem innerHTML com conteúdo, o ponto cego do
    teste de esc() (template aninhado) deixa de importar aqui."""
    for p in ADMIN:
        for m in re.finditer(r"innerHTML\s*=\s*([^;]*)", _codigo(p)):
            assert m.group(1).strip() in ('""', "''"), f"{p.name}: innerHTML = {m.group(1)[:40]}"


def test_handler_assincrono_passa_pelo_acao():
    """`acao()` desliga o botão enquanto roda (dois cliques não criam duas
    imagens) e mostra o erro de um jeito só. Handler assíncrono solto era a
    promessa rejeitada sem dono: o usuário não via nada."""
    for p in ADMIN:
        codigo = _codigo(p)
        achados = re.findall(r"\.on(click|change|submit|input)\s*=\s*async\b", codigo)
        achados += re.findall(r"\bon(click|change|submit|input)\s*:\s*async\b", codigo)
        assert achados == [], f"{p.name}: {achados}"


def test_abas_rotas_e_modulos_batem():
    """Cada aba do HTML tem rota, cada rota tem um módulo com `vista`."""
    html = (WEB / "admin" / "index.html").read_text(encoding="utf-8")
    abas = re.findall(r'data-aba="([a-z]+)"', html)
    rotas = (WEB / "admin" / "rotas.js").read_text(encoding="utf-8")
    bloco = rotas.split("export const ROTAS = {", 1)[1].split("\n};", 1)[0]
    chaves = re.findall(r"^\s*([a-z]+): \{", bloco, re.M)
    assert abas == chaves, (abas, chaves)
    for aba in chaves:
        assert f'import * as {aba} from "./{aba}.js";' in rotas, aba
        assert "export const vista = " in (WEB / "admin" / f"{aba}.js").read_text(encoding="utf-8"), aba
    assert 'export const PADRAO = "imagens";' in rotas


def test_aba_desconhecida_ou_alheia_volta_ao_padrao():
    """#xyz e #pessoas (para um sub-admin) caem na aba padrão do MESMO jeito:
    a tela não diz o que existe para quem não pode ver."""
    rotas = (WEB / "admin" / "rotas.js").read_text(encoding="utf-8")
    trecho = rotas.split("export const renderizar", 1)[1].split("const vista", 1)[0]
    assert "if (!permitida(rota.aba))" in trecho
    assert 'history.replaceState(null, "", `#${PADRAO}`)' in trecho


def test_o_aviso_aparece_por_cima_do_dialogo():
    """Um toast no <body> fica atrás do <dialog> modal e da cortina dele: o
    erro de um "Salvar" feito dentro do diálogo não aparecia."""
    ui = (WEB / "common" / "ui.js").read_text(encoding="utf-8")
    trecho = ui.split("export function toast(", 1)[1].split("\n}\n", 1)[0]
    assert 'querySelectorAll("dialog[open]")' in trecho


def test_o_codigo_de_convite_nao_vai_para_o_endereco():
    """O código é a credencial do console do sub-admin: a página da pessoa usa
    o owner_ref, nunca o código, no hash (que vai para o histórico)."""
    js = (WEB / "admin" / "pessoas.js").read_text(encoding="utf-8")
    for m in re.finditer(r'(?:linkPara|irPara)\(([^)]*"pessoas"[^)]*)\)', js):
        assert ".code" not in m.group(1), m.group(0)
    assert "owner_ref" in js


def test_o_segredo_mostrado_uma_vez_nao_fecha_no_esc():
    """O navegador só deixa cancelar o fechamento depois de um gesto do usuário,
    e o segredo abre depois de uma chamada assíncrona: sem barrar o keydown do
    Esc, a chave nova sumia antes de ser copiada."""
    js = (WEB / "common" / "dialogo.js").read_text(encoding="utf-8")
    assert 'ev.key === "Escape"' in js and '"keydown"' in js
