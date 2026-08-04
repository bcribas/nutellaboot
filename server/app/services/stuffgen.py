"""Monta o stuff v3 servido em /boot/v3/{image}/stuff.

Saída = header + variáveis de config renderizadas + módulos shell de
client/stuff/ concatenados em ordem lexical (60-postmount.d/* entra na
posição natural da ordenação). O initrd baixa e faz `.` (source) disso a
cada boot — é o mecanismo de auto-atualização do NutellaBoot.
"""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

from .. import fsdb
from ..settings import REPO_ROOT, settings
from . import config, store

STUFF_DIR = REPO_ROOT / "client" / "stuff"
VAR_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _sh_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


# Separador entre os itens de um campo `list`, quando o esquema não diz outro.
#
# Vírgula porque é o que os dois consumidores esperam, e um deles precisa: cada
# item de FIREWALL_ALLOWLIST é o par "NOME IP", com um espaço DENTRO. Juntar
# com espaço não separava errado — apagava a fronteira entre os itens, e o laço
# do firewall (`IFS=,`) via tudo como uma entrada só. Com duas linhas na lista,
# a segunda simplesmente não era liberada, sem erro e sem log; na prova isso é
# o servidor do BOCA fora do firewall.
#
# O outro é `sources=[$INPUT_SOURCES]` do dconf, uma lista GVariant, onde
# espaço entre as tuplas é erro de sintaxe — e o `dconf update` que recusa o
# arquivo derruba junto os outros ajustes da sala.
SEP_PADRAO = ","


def _render_value(value, sep: str = SEP_PADRAO) -> str:
    if value is None:
        # sem este ramo, `_sh_quote(None)` emitia a string 'None' — e
        # `MINRAM='None'` faz a comparação aritmética do boot dar erro
        return "''"
    if isinstance(value, bool):
        return "'t'" if value else "'f'"
    if isinstance(value, list):
        return _sh_quote(sep.join(str(v) for v in value))
    return _sh_quote(value)


def modules() -> list[Path]:
    if not STUFF_DIR.is_dir():
        return []
    files = [p for p in STUFF_DIR.rglob("*.sh") if p.is_file()]
    return sorted(files, key=lambda p: str(p.relative_to(STUFF_DIR)))


def render(image_id: str) -> str:
    # effective_values aplica o esquema: campos bloqueados voltam ao padrão do
    # modelo mesmo que a imagem tenha salvo outro valor antes do bloqueio.
    values = dict(config.effective_values(image_id))
    raw = store.config_values(image_id)
    wallpaper = fsdb.read_json(store.site_image_dir(image_id) / "wallpaper.json")

    lines = [
        "#!/bin/sh",
        f"# nutellaboot3 stuff — imagem {image_id} — gerado em "
        + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "# Este arquivo é baixado e sourced pelo initrd a cada boot.",
        "",
        f"NBUID={secrets.randbelow(2**32)}",
        f"IMAGEROOT={_sh_quote(image_id)}",
        # o nome de exibição da sede. Vem por aqui, e não do pendrive, porque o
        # stuff é gerado por imagem a cada boot: numa imagem genérica com o
        # IMAGEROOT digitado à mão — que é o fluxo previsto — o pendrive não
        # teria nome nenhum para dar.
        f"NB_SITE_NAME={_sh_quote((store.get_site_image(image_id) or {}).get('fullname', ''))}",
        f"NB_SERVER={_sh_quote(settings.base_url)}",
        f"NB_MACHINE_KEY={_sh_quote(store.machine_key(image_id))}",
        f"NB_BOOT_KEY={_sh_quote(store.boot_key(image_id))}",
    ]
    if wallpaper and wallpaper.get("md5"):
        lines.append(f"NB_WALLPAPER_MD5={_sh_quote(wallpaper['md5'])}")

    # o separador é do CAMPO, não global: `60-polkit.sh` percorre
    # NB_HIDE_DOCS_APPS com o IFS padrão, então uma lista de aplicativos
    # precisaria de espaço. Ainda não é campo de formulário, mas no dia em que
    # for, um separador único seria esta mesma armadilha ao contrário.
    seps = {
        f["key"]: f.get("sep", SEP_PADRAO)
        for f in config.schema_for(image_id).get("fields", [])
        if isinstance(f, dict) and f.get("key")
    }

    for name in sorted(values):
        if not VAR_NAME_RE.match(name):
            continue  # nomes fora do padrão nunca viram código shell
        if name.startswith("LOCK_FALLBACK"):
            continue  # hash da senha vai como NB_LOCK_FALLBACK_HASH abaixo
        lines.append(f"{name}={_render_value(values[name], seps.get(name, SEP_PADRAO))}")

    lockhash = raw.get("LOCK_FALLBACK_PASSWORD_HASH", "")
    if lockhash:
        lines.append(f"NB_LOCK_FALLBACK_HASH={_sh_quote(lockhash)}")

    parts = ["\n".join(lines), ""]
    for mod in modules():
        rel = mod.relative_to(STUFF_DIR)
        parts.append(f"# ===== módulo: {rel} =====")
        parts.append(mod.read_text())
    return "\n".join(parts) + "\n"
