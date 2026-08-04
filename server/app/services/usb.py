"""A imagem do pendrive de boot, pela API.

Até aqui o pendrive só existia em `tools/nb3-genusb`, na máquina de gestão.
Quem coordena uma sede não tem acesso a isso, e o console não dizia uma palavra
sobre o único jeito de a máquina ligar.

São duas coisas, e a ordem importa:

  * a **imagem genérica** — uma só, igual para todas as sedes. É o ponto do
    redesenho do nb3 (o nb2 tinha ~45 imagens de 400 MB que só diferiam num
    token). Não leva segredo nenhum dentro, então pode ir para um diretório
    público do servidor de arquivos;
  * o **`nutellaboot.conf` da sala** — quatro linhas de texto que o initrd lê e
    copia para a memória antes de desmontar o pendrive. Preencher isso à mão é
    o erro mais comum do sistema: sem `IMAGEROOT` a máquina para na tela
    "NO IMAGE".

Para quem prefere não copiar arquivo nenhum, existe a terceira: a imagem **já
configurada** para a sala, que é a genérica com esses valores já dentro. Essa
leva a chave de boot, então o nome ganha um sufixo aleatório e ela nunca vai
para `/blobs` (que é servido sem autenticação).

A geração roda por subprocesso assíncrono, não pela fila de camadas: o
`nb3-layer-worker` não tem supervisor, e um botão que só funciona quando
alguém lembrou de deixar um processo de pé é pior que não ter botão. Também não
roda no laço de eventos — o servidor tem um worker só, e bloqueá-lo congela o
SSE e o long-poll da sala inteira.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import shlex
import time
from pathlib import Path

from .. import fsdb
from ..settings import REPO_ROOT, settings
from . import publish

FERRAMENTA = REPO_ROOT / "tools" / "nb3-genusb"

# quanto tempo uma geração pode levar antes de ser considerada travada
TIMEOUT = 1800

DEFAULT = {"auto_generate": True, "size_mb": 400}


def conf() -> dict:
    server = fsdb.read_json(settings.data_root / "server.json", {}) or {}
    return {**DEFAULT, **(server.get("usb") or {})}


def build_dir() -> Path:
    """Onde moram o vmlinuz e o initrd.img (compartilhados por todas as sedes).

    `NB3_BUILD_DIR` existe para os testes: gerar um initrd de verdade precisa de
    root, e a suíte não pode depender disso.
    """
    return Path(os.environ.get("NB3_BUILD_DIR", str(REPO_ROOT / "client" / "build")))


def _usb_dir() -> Path:
    return settings.data_root / "usb"


# --- kernel e initrd: sem eles não há pendrive nenhum ---


def kernel_state() -> dict:
    """O que existe em client/build, com o comando para produzir o que falta."""
    partes = {}
    for nome in ("vmlinuz", "initrd.img"):
        p = build_dir() / nome
        if p.is_file():
            st = p.stat()
            partes[nome] = {"size": st.st_size, "mtime": st.st_mtime}
        else:
            partes[nome] = None
    ok = all(partes.values())
    return {
        "ok": ok,
        "dir": str(build_dir()),
        "files": partes,
        # é o único passo do sistema que precisa de root, então a mensagem tem
        # que ser o comando exato — não "veja a documentação"
        "hint": "" if ok else "sudo tools/nb3-build-initrd --raw <imagem-mestre>.raw",
    }


ARQUIVOS_DE_BOOT = ("vmlinuz", "initrd.img")


def build_info() -> dict:
    """O que `tools/nb3-build-initrd` carimbou na construção atual.

    `{"build": "20260803-…", "files": {"vmlinuz": {"md5":…, "size":…}, …}}`.

    O md5 vem da ferramenta e NÃO é calculado aqui: são 200 MB, e o servidor
    roda com um worker só (invariante 2) — refazer o hash a cada boot da sala
    congelaria o SSE e o long-poll de todo mundo.

    Construção anterior a isto não tem o arquivo. Aí `build` volta vazio, a
    rota de boot diz `unknown` e a máquina não confere nada: é o único
    comportamento honesto quando não se sabe a própria versão.
    """
    d = fsdb.read_json(build_dir() / "build.json", {}) or {}
    arquivos = d.get("files") or {}
    if not d.get("build") or not all(
        isinstance(arquivos.get(n), dict) and arquivos[n].get("md5") for n in ARQUIVOS_DE_BOOT
    ):
        return {"build": "", "files": {}}
    return {"build": str(d["build"]), "files": {n: arquivos[n] for n in ARQUIVOS_DE_BOOT}}


def _kernel_fingerprint() -> str:
    """Impressão do par kernel+initrd usado numa geração.

    `(mtime, size)` em vez de md5: são 200 MB, e a pergunta é só "mudou desde
    que esta imagem foi gerada".
    """
    partes = []
    for nome in ("vmlinuz", "initrd.img"):
        p = build_dir() / nome
        if not p.is_file():
            return ""
        st = p.stat()
        partes.append(f"{nome}:{st.st_size}:{int(st.st_mtime)}")
    return "|".join(partes)


def _boot_fingerprint(image_id: str) -> str:
    """Impressão da chave de boot da sala — nunca a chave em si, porque este
    valor vai para a tela e para o disco sem proteção."""
    chave = (fsdb.read_text(settings.data_root / "site-images" / image_id / "boot.key") or "").strip()
    return hashlib.sha256(chave.encode()).hexdigest()[:16] if chave else ""


# --- o nutellaboot.conf da sala ---

# O que não pode entrar num valor que o GRUB vai receber por `source`.
#
# `$` é o pior: `set NB_SITE_NAME="R$ 10"` faz o `source` FALHAR inteiro, e com
# ele some o IMAGEROOT — o menu perde a sede por causa do nome. Aspa fecha a
# string, barra invertida e crase são escape. Acento não entra nesta lista de
# propósito: `São`, `nº` e travessão passam pelo grub-script-check sem chiar, e
# transliterar deixaria o nome errado na tela por medo de um problema que não
# existe.
_GRUB_PROIBIDO = re.compile(r'["$\\`\x00-\x1f\x7f]')


def nome_para_grub(texto: str) -> str:
    """O `fullname` como o GRUB pode receber."""
    return " ".join(_GRUB_PROIBIDO.sub(" ", texto or "").split())


def conf_text(image_id: str) -> str:
    """As linhas que o initrd lê do pendrive (`nb_conf_value`).

    O `set ` na frente não é enfeite: com ele o MESMO arquivo serve ao GRUB,
    que só entende `set VAR=valor` (para ele, `IMAGEROOT=26spsp` é o nome de um
    comando inexistente). É assim que o menu de boot passa a dizer a sede sem
    pedir um segundo arquivo para o operador copiar.

    O parser do initrd aceita o prefixo como OPCIONAL, então pendrive já
    gravado continua bootando. O caminho inverso não vale: um initrd anterior a
    esta mudança, com um arquivo novo, não acha a sede e para na tela "NO
    IMAGE" — por isso o aviso está no próprio arquivo.
    """
    d = settings.data_root / "site-images" / image_id
    chave = (fsdb.read_text(d / "boot.key") or "").strip()
    info = fsdb.read_json(d / "image.json", {}) or {}
    nome = info.get("fullname") or image_id
    return "\n".join(
        [
            f"# nutellaboot.conf — {nome} ({image_id})",
            "# Gerado pelo NutellaBoot 3. Copie para a raiz do pendrive, por cima",
            "# do arquivo que já está lá. É só texto: dá para conferir e editar.",
            "#",
            "# O initrd lê este arquivo, copia para a memória e desmonta a partição",
            "# logo no início: o pendrive pode ser retirado assim que a mensagem",
            "# aparecer na tela, e servir para a próxima máquina.",
            "#",
            "# O `set` na frente faz este mesmo arquivo servir ao menu do GRUB.",
            "# Precisa de um pendrive gerado a partir de agosto de 2026: num",
            "# initrd mais antigo, use as linhas sem o `set`.",
            f'set IMAGEROOT="{image_id}"',
            # só o menu do GRUB usa: o sistema recebe o mesmo nome pelo stuff,
            # que é gerado por imagem e não depende de o pendrive estar em dia
            f'set NB_SITE_NAME="{nome_para_grub(nome)}"',
            f'set NB_BOOT_KEY="{chave}"',
            f'set NB_SERVER="{settings.base_url}"',
            "",
        ]
    )


# --- estado ---


def _generic_state_path() -> Path:
    return _usb_dir() / "generic.json"


def _image_state_path(image_id: str) -> Path:
    return settings.data_root / "site-images" / image_id / "usb.json"


def _com_derivados(estado: dict, *, esperado_kernel: str, esperado_boot: str = "") -> dict:
    """Acrescenta `stale` e o motivo, calculados na leitura.

    Não são campos gravados: a chave de boot pode ser rotacionada por outra
    rota, e um campo velho no disco mentiria até alguém regerar.
    """
    e = dict(estado)
    motivos = []
    if e.get("status") == "done":
        if esperado_boot and e.get("boot_fingerprint") and e["boot_fingerprint"] != esperado_boot:
            motivos.append("boot_key")
        if esperado_kernel and e.get("kernel_fingerprint") and e["kernel_fingerprint"] != esperado_kernel:
            motivos.append("kernel")
        if e.get("server") and e["server"] != settings.base_url:
            motivos.append("server")
    e["stale"] = bool(motivos)
    e["stale_reason"] = motivos
    if e.get("file"):
        pub = publish.state(e["file"]) or {}
        e["published"] = pub.get("status") == "done"
        # Publicada VELHA é pior que não publicada: o arquivo lá tem a chave de
        # boot anterior, e a sede que o gravar não boota sem nada explicando.
        # Por isso `public_url` só sai quando a cópia de lá corresponde à
        # construção daqui — quem quiser entregar o arquivo tem que passar pela
        # rota, que sabe escolher.
        e["publish_stale"] = bool(
            e["published"] and pub.get("published_at", 0) < e.get("built_at", 0)
        )
        e["public_url"] = "" if e["publish_stale"] else pub.get("url", "")
        e["publish_error"] = pub.get("error", "") if pub.get("status") == "failed" else ""
    return e


def url_publicada_atual(estado: dict) -> str:
    """A URL pública, se e só se ela serve o arquivo desta construção."""
    return estado.get("public_url", "") if estado.get("status") == "done" else ""


def generic_state() -> dict:
    estado = fsdb.read_json(_generic_state_path(), {}) or {}
    if not estado:
        estado = {"status": "missing"}
    return _com_derivados(estado, esperado_kernel=_kernel_fingerprint())


def image_state(image_id: str) -> dict:
    estado = fsdb.read_json(_image_state_path(image_id), {}) or {}
    if not estado:
        estado = {"status": "missing"}
    return _com_derivados(
        estado,
        esperado_kernel=_kernel_fingerprint(),
        esperado_boot=_boot_fingerprint(image_id),
    )


def _sufixo(image_id: str) -> str:
    """O sufixo do nome do arquivo da sala, sorteado uma vez e mantido.

    Existe porque o arquivo carrega a chave de boot: `26spsp.img` é adivinhável,
    e quem adivinhar o nome no servidor de arquivos leva a chave da sala junto.
    Mantido estável entre gerações para que regerar sobrescreva o mesmo arquivo
    lá — o rsync não apaga o que ficou para trás.
    """
    p = _image_state_path(image_id)
    atual = fsdb.read_json(p, {}) or {}
    if atual.get("suffix"):
        return atual["suffix"]
    return secrets.token_hex(4)


def _nome_generico() -> str:
    return "nutellaboot3.img"


def _nome_da_sala(image_id: str, sufixo: str) -> str:
    return f"{image_id}-{sufixo}.img"


def file_path(nome: str) -> Path:
    return _usb_dir() / nome


# --- geração ---


def _marcar(caminho: Path, **campos) -> dict:
    atual = fsdb.read_json(caminho, {}) or {}
    novo = {**atual, **campos, "updated_at": time.time()}
    fsdb.write_json(caminho, novo)
    return novo


_lock: asyncio.Lock | None = None
_lock_loop = None


def _obter_lock() -> asyncio.Lock:
    """Um lock por laço de eventos.

    Guardar primitiva de asyncio entre requisições quebra quando o laço muda —
    já aconteceu com os eventos do long-poll, e a suíte cria um laço por teste.
    """
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


async def _rodar(args: list[str]) -> tuple[int, str]:
    base = os.environ.get("NB3_GENUSB_CMD")
    cmd = [*shlex.split(base), *args] if base else [str(FERRAMENTA), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(REPO_ROOT),
        env={**os.environ, "NB3_DATA_ROOT": str(settings.data_root)},
    )
    try:
        saida, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, f"a geração passou de {TIMEOUT // 60} minutos e foi interrompida"
    return proc.returncode or 0, (saida or b"").decode(errors="replace")[-4000:]


async def _gerar(caminho_estado: Path, nome: str, extras: list[str], **campos) -> dict:
    k = kernel_state()
    if not k["ok"]:
        return _marcar(
            caminho_estado,
            status="unavailable",
            error=f"vmlinuz/initrd.img não encontrados em {k['dir']}",
            hint=k["hint"],
        )

    destino = file_path(nome)
    destino.parent.mkdir(parents=True, exist_ok=True)
    args = ["--output", str(destino), *extras]
    if publish.enabled():
        args.append("--publish")

    fingerprint = _kernel_fingerprint()
    _marcar(caminho_estado, status="building", file=nome, error="", hint="", **campos)

    # uma geração por vez: são 400 MB de escrita cada, e a criação em massa
    # dispararia uma por sede ao mesmo tempo
    async with _obter_lock():
        rc, saida = await _rodar(args)

    if rc != 0:
        return _marcar(caminho_estado, status="failed", error=saida.strip()[-800:] or f"código {rc}")

    tamanho = destino.stat().st_size if destino.is_file() else 0
    return _marcar(
        caminho_estado,
        status="done",
        file=nome,
        size=tamanho,
        built_at=time.time(),
        kernel_fingerprint=fingerprint,
        server=settings.base_url,
        error="",
        hint="",
    )


async def gerar_generica() -> dict:
    """A imagem que serve todas as sedes. Sem IMAGEROOT e sem chave dentro."""
    return await _gerar(_generic_state_path(), _nome_generico(), [])


async def gerar_da_sala(image_id: str) -> dict:
    """A imagem já configurada para uma sala. Leva a chave de boot dentro."""
    d = settings.data_root / "site-images" / image_id
    chave = (fsdb.read_text(d / "boot.key") or "").strip()
    info = fsdb.read_json(d / "image.json", {}) or {}
    sufixo = _sufixo(image_id)
    extras = ["--imageroot", image_id, "--server", settings.base_url]
    if info.get("fullname"):
        extras += ["--fullname", info["fullname"]]
    if chave:
        extras += ["--boot-key", chave]
    return await _gerar(
        _image_state_path(image_id),
        _nome_da_sala(image_id, sufixo),
        extras,
        suffix=sufixo,
        boot_fingerprint=_boot_fingerprint(image_id),
    )


# --- agendamento ---

_tarefas: set[asyncio.Task] = set()


def _agendar(corotina) -> bool:
    """Dispara em segundo plano, se houver laço rodando.

    Fora do servidor (ferramentas de linha de comando, testes síncronos) não há
    laço: devolve False em vez de estourar.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        corotina.close()
        return False
    tarefa = loop.create_task(corotina)
    # sem a referência forte, o coletor de lixo pode levar a tarefa no meio
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)
    return True


def agendar(image_id: str, *, forcado: bool = False) -> bool:
    """Gera a imagem da sala em segundo plano.

    Chamado na criação de toda site-image. `usb.auto_generate: false` no
    server.json desliga o automático (são 400 MB por sede) sem tirar o botão.
    """
    if not forcado and not conf().get("auto_generate", True):
        return False
    if image_state(image_id).get("status") == "building":
        return False
    # a genérica é o download em destaque das três telas: não adianta a sala
    # ter a sua e a principal não existir
    if generic_state().get("status") == "missing":
        agendar_generica()
    return _agendar(gerar_da_sala(image_id))


def agendar_generica(*, forcado: bool = False) -> bool:
    if generic_state().get("status") == "building" and not forcado:
        return False
    return _agendar(gerar_generica())
