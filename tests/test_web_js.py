"""Variável não declarada no JavaScript das telas.

"Erro: template is not defined" ao criar uma imagem: um renomeio trocou a
declaração (`const model = ...`) e esqueceu um uso (`model: template`). Esse
tipo de erro não aparece ao carregar a página — só explode no clique, na frente
do usuário. Foi a segunda vez que resíduo de renomeio passou por todos os
testes (a primeira foi o `sleep RAM` do shell).

Não há motor de JS nesta máquina (sem node), então isto é um *no-undef* mínimo
em Python: tokeniza fora comentários/strings/regex (preservando o código de
`${...}` em template literals), coleta declarações e usos, e acusa uso sem
declaração que não seja um global do navegador.

Não é um linter de verdade. O desenho pende para o falso negativo (na dúvida,
não acusa — ex.: o consequente de um ternário se confunde com chave de objeto
e é pulado); falso positivo é que mataria o teste. Erros de tipo e de lógica
continuam fora do alcance.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARQUIVOS = sorted(
    p for p in (REPO / "web").rglob("*.js") if "locales" not in p.parts
)

PALAVRAS_CHAVE = {
    "const", "let", "var", "function", "return", "if", "else", "for", "while",
    "do", "of", "in", "new", "try", "catch", "finally", "throw", "async",
    "await", "class", "extends", "true", "false", "null", "undefined", "this",
    "typeof", "instanceof", "delete", "void", "break", "continue", "switch",
    "case", "default", "export", "import", "from", "as", "yield", "static",
    "get", "set", "constructor", "super",
}

# Globals que o navegador fornece. Conjunto explícito de propósito: um nome
# novo aqui é uma linha; um conjunto "esperto" seria um buraco.
GLOBALS = {
    "document", "window", "location", "history", "navigator", "console",
    "fetch", "alert", "confirm", "prompt",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "sessionStorage", "localStorage",
    "URLSearchParams", "URL", "FormData", "Blob", "File",
    "EventSource", "WebSocket", "AudioContext", "DOMParser", "CustomEvent",
    "JSON", "Math", "Date", "Promise", "Array", "Object", "String", "Number",
    "Boolean", "Set", "Map", "Error", "TypeError", "RegExp",
    "encodeURIComponent", "decodeURIComponent", "parseInt", "parseFloat",
    "isNaN", "isFinite", "structuredClone", "requestAnimationFrame",
}

IDENT = r"[A-Za-z_$][\w$]*"


def tirar_nao_codigo(texto: str) -> str:
    """Troca por espaços o que não é código: comentários, strings, regex e o
    texto de template literals — preservando o código dentro de `${...}`.
    Mantém os \\n para os números de linha continuarem certos."""
    saida = list(texto)
    i, n = 0, len(texto)

    def apagar(a, b):
        for k in range(a, min(b, n)):
            if saida[k] != "\n":
                saida[k] = " "

    # pilha de contexto para `${ ... }` aninhado dentro de template literal
    modo = ["codigo"]
    ultimo_relevante = ""  # último caractere de código, para detectar regex
    inicio = 0

    while i < n:
        c = texto[i]
        estado = modo[-1]

        if estado == "codigo":
            if c == "/" and texto[i + 1 : i + 2] == "/":
                fim = texto.find("\n", i)
                fim = n if fim == -1 else fim
                apagar(i, fim)
                i = fim
                continue
            if c == "/" and texto[i + 1 : i + 2] == "*":
                fim = texto.find("*/", i)
                fim = n if fim == -1 else fim + 2
                apagar(i, fim)
                i = fim
                continue
            if c in "'\"":
                inicio, alvo = i, c
                i += 1
                while i < n and texto[i] != alvo:
                    i += 2 if texto[i] == "\\" else 1
                apagar(inicio + 1, i)
                i += 1
                continue
            if c == "`":
                modo.append("template")
                inicio = i + 1
                i += 1
                continue
            if c == "/" and ultimo_relevante in "(,=:[!&|?{};\n" + "":
                # heurística clássica: '/' depois de operador abre regex,
                # depois de valor é divisão
                inicio = i
                i += 1
                dentro_classe = False
                while i < n:
                    if texto[i] == "\\":
                        i += 2
                        continue
                    if texto[i] == "[":
                        dentro_classe = True
                    elif texto[i] == "]":
                        dentro_classe = False
                    elif texto[i] == "/" and not dentro_classe:
                        break
                    elif texto[i] == "\n":
                        break  # não era regex; desiste sem apagar
                    i += 1
                if i < n and texto[i] == "/":
                    apagar(inicio + 1, i)
                    i += 1
                continue
            if c == "}" and len(modo) > 1 and modo[-1] == "codigo":
                # fecha um ${ ... }: volta ao texto do template
                modo.pop()
                inicio = i + 1
                i += 1
                continue
            if not c.isspace():
                ultimo_relevante = c
            i += 1
            continue

        if estado == "template":
            if c == "\\":
                apagar(i, i + 2)
                i += 2
                continue
            if c == "`":
                apagar(inicio, i)
                modo.pop()
                i += 1
                continue
            if c == "$" and texto[i + 1 : i + 2] == "{":
                apagar(inicio, i + 2)
                modo.append("codigo")
                ultimo_relevante = "{"
                i += 2
                continue
            i += 1
            continue

    return "".join(saida)


def _nomes(trecho: str) -> set[str]:
    """Identificadores declarados num pedaço de lista (params, destructuring).
    Em `a = 1` e `a: b` (rename de destructuring), o declarado é o certo."""
    achados = set()
    for parte in trecho.split(","):
        # corta o valor padrao (`a = 1`, `{ x } = {}`) e desembrulha o
        # destructuring — depois do split por virgula, `{a, b}` chega como
        # `{a` e `b}`, e tirar as chaves resolve os dois
        parte = parte.split("=")[0]
        parte = parte.strip().lstrip(".").strip("{}[] \t")
        if not parte:
            continue
        m = re.match(rf"({IDENT})\s*:\s*({IDENT})", parte)
        if m:
            achados.add(m.group(2))  # {original: renomeado} declara o renomeado
            continue
        m = re.match(rf"({IDENT})", parte)
        if m:
            achados.add(m.group(1))
    return achados


def declarados(codigo: str) -> set[str]:
    d: set[str] = set()
    for m in re.finditer(rf"\bimport\s+\*\s+as\s+({IDENT})", codigo):
        d.add(m.group(1))
    for m in re.finditer(r"\bimport\s*\{([^}]*)\}", codigo):
        d |= _nomes(m.group(1))
    for m in re.finditer(rf"\b(?:const|let|var)\s+({IDENT})", codigo):
        d.add(m.group(1))
    for m in re.finditer(r"\b(?:const|let|var)\s*\{([^}]*)\}", codigo):
        d |= _nomes(m.group(1))
    for m in re.finditer(r"\b(?:const|let|var)\s*\[([^\]]*)\]", codigo):
        d |= _nomes(m.group(1))
    for m in re.finditer(rf"\bfunction\s+({IDENT})?\s*\(([^)]*)\)", codigo):
        if m.group(1):
            d.add(m.group(1))
        d |= _nomes(m.group(2))
    for m in re.finditer(r"\(([^()]*)\)\s*=>", codigo):
        d |= _nomes(m.group(1))
    for m in re.finditer(rf"\b({IDENT})\s*=>", codigo):
        d.add(m.group(1))
    for m in re.finditer(rf"\bcatch\s*\(\s*({IDENT})", codigo):
        d.add(m.group(1))
    for m in re.finditer(rf"\bclass\s+({IDENT})", codigo):
        d.add(m.group(1))
    # parâmetros de método de classe (`constructor(a, b) {`). O padrão também
    # casa `if (x) {` e declara `x` a mais — sobre-declarar só gera falso
    # negativo, que é o lado escolhido deste verificador.
    for m in re.finditer(rf"\b{IDENT}\s*\(([^()]*)\)\s*\{{", codigo):
        d |= _nomes(m.group(1))
    return d


def usos_sem_declaracao(texto: str) -> list[tuple[int, str]]:
    codigo = tirar_nao_codigo(texto)
    conhecidos = declarados(codigo) | PALAVRAS_CHAVE | GLOBALS
    problemas = []
    for m in re.finditer(IDENT, codigo):
        nome = m.group(0)
        if nome in conhecidos:
            continue
        antes = codigo[: m.start()].rstrip()
        depois = codigo[m.end() :].lstrip()
        # acesso de propriedade (obj.x, obj?.x) não é uso de variável
        if antes.endswith(".") or antes.endswith("?."):
            continue
        # chave de objeto ({x: ...}) e rótulo não são usos. O consequente de
        # um ternário também cai aqui — falso negativo aceito de propósito.
        if depois.startswith(":"):
            continue
        linha = texto[: m.start()].count("\n") + 1
        problemas.append((linha, nome))
    return problemas


# --- o verificador aplicado às telas ---


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda p: str(p.relative_to(REPO / "web")))
def test_nenhuma_variavel_sem_declaracao(arquivo):
    problemas = usos_sem_declaracao(arquivo.read_text(encoding="utf-8"))
    assert problemas == [], "; ".join(
        f"{arquivo.name}:{linha}: '{nome}' não é declarado nem é um global conhecido"
        for linha, nome in problemas
    )


# --- o verificador precisa pegar o bug que o motivou ---


def test_o_verificador_acusa_o_bug_original():
    """Reintroduz o `model: template` no admin/app.js de verdade (em memória)
    e confere que o verificador aponta exatamente o `template`. Se um dia o
    verificador afrouxar a ponto de deixar isso passar, este teste avisa."""
    texto = (REPO / "web" / "admin" / "app.js").read_text(encoding="utf-8")
    alvo = "{ id, fullname, model, unlocked, wallpaper_locked }"
    assert alvo in texto, "a linha da criação de imagem mudou; atualize o teste"
    quebrado = texto.replace(alvo, "{ id, fullname, model: template, unlocked, wallpaper_locked }")

    nomes = {nome for _, nome in usos_sem_declaracao(quebrado)}
    assert nomes == {"template"}, nomes


def test_o_verificador_entende_o_que_nao_e_codigo():
    """As três armadilhas do tokenizador: string com aspas, template literal
    com código dentro, e regex com aspas no meio."""
    trecho = '''
const a = "isto nao e codigo: fantasma1";
const b = `texto ${a} mais texto ${outra} fim`;
const c = a.split(/["']+/);
const d = { chave: valor };
obj.propriedade = 1;
'''
    nomes = {nome for _, nome in usos_sem_declaracao(trecho)}
    # `outra` (dentro do ${}) e `valor` (valor de chave) são usos reais sem
    # declaração; `fantasma1` (string), `chave` (chave) e `propriedade`
    # (acesso) não são
    assert nomes == {"outra", "valor", "obj"}, nomes


def test_as_telas_da_sede_se_enxergam():
    """Quem coordena recebe dois links e, dentro de um, não tinha como chegar
    no outro — e a home, que tem os dois botões, não é onde a pessoa está.

    O `href` sai do JS, e não do HTML, porque leva o `?id=&tk=`: escrever a
    credencial no HTML servido seria a única forma de errar isso."""
    pares = [
        ("configureitor", "gohot", "hotconfig"),
        ("hotconfig", "goconfig", "configureitor"),
    ]
    for tela, elemento, irma in pares:
        html = (REPO / "web" / tela / "index.html").read_text(encoding="utf-8")
        js = (REPO / "web" / tela / "app.js").read_text(encoding="utf-8")
        assert f'id="{elemento}"' in html, f"{tela}: falta o link para o {irma}"
        assert "href=" not in html.split(f'id="{elemento}"')[1].split(">")[0], (
            f"{tela}: o href está no HTML; a credencial tem que vir do JS"
        )
        assert f'api.telaIrma("{irma}")' in js, f"{tela}: o link não é montado"

    api = (REPO / "web" / "common" / "api.js").read_text(encoding="utf-8")
    assert "location.search" in api.split("export function telaIrma")[1][:200], (
        "telaIrma precisa preservar o ?id=&tk= da tela atual"
    )


def test_o_bloco_do_pendrive_nao_fixa_credencial_de_console():
    """`kind: "admin"` faz o api.js NÃO mandar o token da URL — e o
    configureitor, que se autentica só por `?tk=`, recebia 401 e ficava sem o
    bloco do pendrive inteiro. O bloco serve três telas; a credencial tem que
    ser a que cada uma tem."""
    js = (REPO / "web" / "common" / "usb.js").read_text(encoding="utf-8")
    codigo = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
    assert 'kind: "admin"' not in codigo
    assert '"image" : "admin"' not in codigo


def test_o_comando_de_gravar_sai_da_url():
    """O arquivo publicado vem compactado; `dd` num .gz grava o compactado no
    pendrive, que não boota e não diz por quê."""
    js = (REPO / "web" / "common" / "usb.js").read_text(encoding="utf-8")
    assert "comandoGravar" in js
    assert "zcat" in js
    codigo = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
    assert "if=nutellaboot3.img" not in codigo, "o comando voltou a ser fixo"


def test_nenhuma_tela_baixa_direto_do_servidor_de_arquivos():
    """A URL pública só serve quando corresponde à construção ATUAL, e quem
    sabe isso é o servidor. Uma tela que lê `public_url` e a usa como destino
    entrega o arquivo velho — com a chave de boot anterior — quando a imagem foi
    regerada sem republicar."""
    for tela in ("common/usb.js", "admin/app.js"):
        js = (REPO / "web" / tela).read_text(encoding="utf-8")
        codigo = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
        assert "public_url ||" not in codigo, tela
        assert "href = img.public_url" not in codigo, tela


def test_o_hotconfig_pergunta_o_que_pode_mandar():
    """O servidor recusa comando que contradiz campo travado no modelo — o
    botão não pode prometer o que ele vai negar. E falhar essa consulta não
    pode esconder a tela: sem a lista, todos os botões continuam oferecidos e
    a recusa vem do servidor, que é o que valia antes."""
    js = (REPO / "web" / "hotconfig" / "app.js").read_text(encoding="utf-8")
    assert "/commands`" in js and "desabilitarComandosBloqueados" in js
    trecho = js[js.index("async function desabilitarComandosBloqueados") :]
    trecho = trecho[: trecho.index("async function sendCommand")]
    assert "catch" in trecho and "return" in trecho, "a consulta pode derrubar a tela"
    assert "b.disabled = true" in trecho


def test_todo_arquivo_do_relatorio_tem_rotulo():
    """A tela traduz o nome do arquivo por um `ARQ_LABEL[nome]`, e essa chave é
    montada em tempo de execução — o guarda de i18n, que lê `t("literal")`, não
    a enxerga. Acrescentar um arquivo no servidor sem rótulo aqui daria um
    botão escrito `report_f_qualquercoisa` na tela, e nenhum teste reclamaria.
    """
    import json

    from server.app.services import fleet_report

    js = (REPO / "web" / "laboratorios" / "app.js").read_text(encoding="utf-8")
    bloco = js.split("const ARQ_LABEL = {")[1].split("};")[0]
    mapa = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', bloco))
    assert set(mapa) == set(fleet_report.ARQUIVOS), (
        "a lista da tela e a do servidor divergiram"
    )
    pt = json.loads(
        (REPO / "web" / "common" / "locales" / "pt.json").read_text(encoding="utf-8")
    )
    assert not (set(mapa.values()) - set(pt)), "rótulo sem tradução"


def test_o_precontest_tem_confirmacao_forte():
    """A macro apaga o trabalho de todos os times da seleção: um confirm() de
    um clique não está à altura. O botão existe, e a confirmação exige digitar
    o número de máquinas — se alguém "simplificar" de volta para o confirm,
    este teste cai."""
    html = (REPO / "web" / "hotconfig" / "index.html").read_text(encoding="utf-8")
    assert 'data-cmd="precontest"' in html
    js = (REPO / "web" / "hotconfig" / "app.js").read_text(encoding="utf-8")
    assert "confirmarPrecontest" in js
    trecho = js.split("async function sendCommand")[1].split("try {")[0]
    assert 'cmd === "precontest"' in trecho, "o precontest caiu no confirm() simples"


def test_virar_livre_solta_tambem_a_trava_propria_do_wallpaper():
    """A trava DA IMAGEM vence o `unlocked` (é a do convite, de propósito).
    Então o botão Livre do console manda as duas coisas — sem isso, "liberei a
    sede" deixava o wallpaper preso sem nada na tela explicando (o caso
    26tete, visto em produção)."""
    js = (REPO / "web" / "admin" / "app.js").read_text(encoding="utf-8")
    trecho = js.split('t("make_official")')[1].split("load()")[0]
    assert '{ unlocked: true, wallpaper_locked: false }' in trecho


def test_a_identidade_da_sede_e_evidente_nas_duas_telas():
    """O hotconfig não mostrava o FULLNAME (nenhuma resposta que ele buscava o
    trazia) e o id vivia num .sub apagado. Quem opera várias abas precisa saber
    em qual sala está mandando comando — a identidade é a primeira coisa da
    barra, e o title distingue as abas."""
    for tela in ("hotconfig", "configureitor"):
        html = (REPO / "web" / tela / "index.html").read_text(encoding="utf-8")
        assert 'class="siteident"' in html, f"{tela}: sem o bloco de identidade"
        js = (REPO / "web" / tela / "app.js").read_text(encoding="utf-8")
        assert "identname" in js, f"{tela}: o fullname não é preenchido"
        assert "document.title" in js, f"{tela}: o title não identifica a aba"
    # o hotconfig busca a identidade (é a tela que não a tinha)
    js = (REPO / "web" / "hotconfig" / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/site-images/${api.imageId}`" in js


def test_o_dashboard_e_so_leitura_e_o_zoom_abre_no_clique():
    """Tela de transmissão: fica aberta num telão, então NENHUM comando pode
    sair dela — quem precisa agir usa o link para o hotconfig. E o cartão da
    sede abre o zoom (o "entender a situação")."""
    js = (REPO / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
    codigo = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
    assert "api.post" not in codigo, "comando numa tela de telão"
    assert "abrirZoom" in codigo
    assert 'e.key === "Escape"' in codigo, "Esc precisa fechar o zoom"


def test_o_overlay_do_zoom_respeita_o_hidden():
    """O atributo hidden é um display:none de USER-AGENT: qualquer display de
    autor (o flex do overlay) ganha dele. O overlay nasceu visível em produção
    e o fechar não fechava — o JS setava hidden e o CSS mantinha a tela."""
    css = (REPO / "web" / "dashboard" / "dash.css").read_text(encoding="utf-8")
    assert "[hidden]" in css and "!important" in css
