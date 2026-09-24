"""Acesso ao banco-filesystem de modelos e site-images.

Um **modelo** é o que se configura uma vez: as camadas (telemetria, wifi,
pacotes) e o formulário (schema.json, com os cadeados por campo). Uma
**site-image** é derivada de um modelo — uma por sala/sede, com token, chaves
e configuração próprias.

Todo o resto do servidor fala com o disco através deste módulo.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .. import auth, fsdb
from ..settings import settings

IMAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
# nome de modelo vira nome de diretório: validar antes de qualquer escrita
MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}$")


def reserved_names() -> set[str]:
    """Nomes exatos que ninguém além da administração pode tomar. Sem isto,
    'livre por ordem de chegada' significa que o primeiro a chegar leva
    'maratona' ou 'icpc'."""
    padrao = ["admin", "api", "boot", "www", "root", "maratona", "icpc", "sbc", "nutellaboot"]
    return {n.lower() for n in server_conf().get("reserved_names", padrao)}


def name_is_reserved(name: str) -> bool:
    return bool(reserved_re().match(name)) or name.lower() in reserved_names()


def server_conf() -> dict:
    return fsdb.read_json(settings.data_root / "server.json", {}) or {}


def reserved_re() -> re.Pattern:
    return re.compile(server_conf().get("reserved_prefix_regex", "^[0-9]"))


# --- modelos ---


def model_dir(name: str) -> Path:
    return settings.data_root / "models" / name


def model_exists(name: str) -> bool:
    return (model_dir(name) / "model.json").is_file()


def list_models(owner: str | None = None) -> list[str]:
    """Nomes dos modelos. Com `owner`, só os daquele dono — é assim que o
    console de um sub-admin enxerga apenas o que ele criou."""
    base = settings.data_root / "models"
    if not base.is_dir():
        return []
    nomes = sorted(p.name for p in base.iterdir() if (p / "model.json").is_file())
    if owner is None:
        return nomes
    return [n for n in nomes if model_owner(n) == owner]


def model_owner(name: str) -> str:
    """Dono do modelo. Modelos anteriores ao conceito de dono não têm o campo;
    tratá-los como da administração é o certo — foram criados à mão no disco."""
    tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
    return str(tpl.get("owner") or "admin")


def model_is_public(name: str) -> bool:
    """Templates marcados `public: true` são os únicos que a criação por
    convite pode usar — protege os modelos bloqueados de prova."""
    tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
    return bool(tpl.get("public"))


def list_public_models() -> list[dict]:
    out = []
    for name in list_models():
        if model_is_public(name):
            tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
            out.append({"name": name, "description": tpl.get("description", "")})
    return out


def _esquema_cru(d: Path) -> dict:
    # o arquivo como está: só o `_esquema` e o `completar_esquemas` (que
    # compara os dois) podem usar isto (há teste)
    return fsdb.read_json(d / "schema.json", {"fields": []}) or {"fields": []}


def _esquema(d: Path) -> dict:
    """O formulário do modelo como todo leitor tem de vê-lo: o arquivo mais os
    campos novos do esquema padrão (`config._com_padroes`).

    O arquivo cru não tem o campo acrescentado ao padrão depois da criação do
    modelo: o "Salvar" dos cadeados validava contra ele e recusou todo modelo no
    dia em que entrou o MAXMONITORS, e o modelo derivado nascia copiando a
    falta.
    """
    from .config import _com_padroes

    return _com_padroes(_esquema_cru(d))


def get_model(name: str) -> dict | None:
    tpl = fsdb.read_json(model_dir(name) / "model.json")
    if tpl is None:
        return None
    tpl["name"] = name
    tpl["schema"] = _esquema(model_dir(name))
    return tpl


def set_model_layers(name: str, layers: list[dict]) -> None:
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        tpl["layers"] = layers
        fsdb.write_json(model_dir(name) / "model.json", tpl)


def get_schema(name: str) -> dict:
    return _esquema(model_dir(name))


def _o_que_mudou(cru: dict, completo: dict) -> list[str]:
    antes = {f.get("key"): f for f in cru.get("fields", [])}
    mudou = []
    for f in completo.get("fields", []):
        velho = antes.get(f.get("key"))
        if velho is None:
            mudou.append(f["key"])
            continue
        mudou += [f"{f['key']}.{k}" for k in sorted(set(f) | set(velho)) if f.get(k) != velho.get(k)]
    return mudou


def completar_esquemas() -> dict[str, list[str]]:
    """Grava em cada modelo o que o `_esquema` acrescenta ao arquivo.

    Roda quando o servidor sobe: o deploy é `git pull` + restart, e assim o
    campo novo do esquema padrão chega ao `schema.json` de TODO modelo sem passo
    à mão. Acrescenta campo e metadado que faltam e troca a regra que o padrão
    dita (`config.DITADOS_PELO_PADRAO`); o que é do modelo (padrão, cadeado,
    textos) fica. Não regrava o que já está completo. Devolve {modelo: o que
    mudou}: o campo novo pelo nome, o metadado como `CAMPO.metadado`.
    """
    base = settings.data_root / "models"
    feitos: dict[str, list[str]] = {}
    if not base.is_dir():
        return feitos
    for d in sorted(base.iterdir()):
        if not (d / "model.json").is_file():
            continue
        try:
            with fsdb.locked(d):
                cru = _esquema_cru(d)
                completo = _esquema(d)
                if completo == cru:
                    continue
                fsdb.write_json(d / "schema.json", completo)
            feitos[d.name] = _o_que_mudou(cru, completo)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            # um modelo com arquivo estragado não pode impedir o servidor de
            # subir nem os outros de serem completados
            feitos[d.name] = [f"erro: {e}"]
    return feitos


def set_schema_locks(name: str, locks: dict) -> dict:
    """Liga/desliga o cadeado de campos do modelo.

    Só mexe na chave `locked` de cada campo — o resto do schema (tipos,
    opções, rótulos) fica intacto. Vale para todas as imagens Oficiais que
    usam este modelo; imagens Livres continuam ignorando as travas.
    """
    d = model_dir(name)
    with fsdb.locked(d):
        # a tela manda o cadeado de TODOS os campos que o GET /schema mostrou
        schema = _esquema(d)
        conhecidos = {f["key"] for f in schema.get("fields", [])}
        desconhecidos = set(locks) - conhecidos
        if desconhecidos:
            raise ImageError(f"campos que não existem no modelo: {', '.join(sorted(desconhecidos))}")
        for field in schema.get("fields", []):
            if field["key"] in locks:
                field["locked"] = bool(locks[field["key"]])
        fsdb.write_json(d / "schema.json", schema)
    return schema


def set_schema_field(name: str, key: str, patch: dict) -> dict:
    """Ajusta um campo já existente do formulário: valor padrão, rótulo, ajuda
    e cadeado. Não cria nem apaga campos — variável nova só teria efeito se
    algum módulo do `stuff` a lesse, e isso é mudança de cliente, não de dados.
    """
    d = model_dir(name)
    with fsdb.locked(d):
        # com os metadados de formato do esquema padrão: o schema.json gravado
        # na criação do modelo não os tem, e sem eles a validação abaixo não
        # sabe o que exigir
        schema = _esquema(d)
        alvo = next((f for f in schema.get("fields", []) if f["key"] == key), None)
        if alvo is None:
            raise ImageError(f"campo '{key}' não existe neste modelo")
        if "default" in patch:
            # Pelo MESMO caminho que valida o que a sede digita. O padrão de um
            # campo `locked` é o que vai para TODA máquina da sala — e daí para
            # o /etc/.nb3, que o agente carrega como root. Sem esta linha,
            # qualquer valor entrava: uma aspa simples no lugar certo virava
            # comando executado como root em toda a sala, e um `None` fazia a
            # comparação de RAM do boot dar erro de aritmética.
            from .config import ConfigError, _coerce, hash_do_campo

            try:
                valor = _coerce(alvo, patch["default"])
                if alvo.get("type") == "password":
                    # senha em claro NÃO fica no schema.json: o console lê o
                    # arquivo inteiro, e o padrão de um campo de senha é
                    # justamente a senha que a organização escolheu. Guarda-se
                    # o hash, no formato que aquele campo pede. Em branco
                    # significa "sem padrão", e aí a máquina não é tocada.
                    alvo["default"] = ""
                    if valor:
                        alvo["default_hash"] = hash_do_campo(alvo, valor)
                    else:
                        alvo.pop("default_hash", None)
                else:
                    alvo["default"] = valor
            except ConfigError as e:
                raise ImageError(str(e))
        if "locked" in patch:
            alvo["locked"] = bool(patch["locked"])
        for texto in ("label", "help"):
            valor = patch.get(texto)
            if isinstance(valor, dict):
                faltando = {"pt", "en", "es"} - set(valor)
                if faltando:
                    raise ImageError(f"{texto} precisa dos três idiomas (falta: {', '.join(sorted(faltando))})")
                alvo[texto] = {k: str(valor[k]) for k in ("pt", "en", "es")}
        fsdb.write_json(d / "schema.json", schema)
    return schema


def set_model_meta(
    name: str,
    *,
    public: bool | None = None,
    description: str | None = None,
    wallpaper_locked: bool | None = None,
) -> None:
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        if public is not None:
            tpl["public"] = bool(public)
        if description is not None:
            tpl["description"] = str(description)
        if wallpaper_locked is not None:
            # trava do MODELO: vale para toda sede dele e não se contorna sede
            # a sede. Destravar aqui libera todas de uma vez.
            tpl["wallpaper_locked"] = bool(wallpaper_locked)
        fsdb.write_json(model_dir(name) / "model.json", tpl)


def models_using(name: str) -> list[str]:
    """Site-images que derivam deste modelo — quem impede de apagá-lo."""
    return [i["id"] for i in list_site_images() if i.get("model") == name]


def create_model(
    name: str,
    *,
    description: str = "",
    public: bool = False,
    owner: str = "admin",
    from_model: str | None = None,
) -> dict:
    """Cria um modelo. Com `from_model`, copia camadas e formulário (inclusive
    os cadeados) — é assim que se faz um modelo novo já com telemetria e wifi,
    partindo de um que já os tem."""
    from .default_schema import build_default_schema

    if not MODEL_NAME_RE.match(name):
        raise ImageError(
            "nome inválido: use 2-49 caracteres [a-z0-9._-], começando por letra ou dígito"
        )
    if model_exists(name):
        raise ImageError(f"modelo '{name}' já existe")

    layers: list[dict] = []
    schema = build_default_schema()
    if from_model:
        if not model_exists(from_model):
            raise ImageError(f"modelo de origem '{from_model}' não existe")
        base = fsdb.read_json(model_dir(from_model) / "model.json", {}) or {}
        layers = list(base.get("layers", []))
        # completo: copiar o arquivo cru fazia o derivado nascer sem os campos
        # acrescentados ao padrão depois da origem
        schema = _esquema(model_dir(from_model))

    d = model_dir(name)
    with fsdb.locked(d):
        fsdb.write_json(
            d / "model.json",
            {
                "name": name,
                "description": description,
                "owner": owner,
                "public": bool(public),
                "created_at": time.time(),
                "derived_from": from_model,
                "layers": layers,
            },
        )
        fsdb.write_json(d / "schema.json", schema)
    return get_model(name)


def delete_model(name: str) -> None:
    """Recusa se alguma site-image ainda deriva dele — apagar deixaria essas
    máquinas com manifest sem base, ou seja, sem sistema para bootar."""
    em_uso = models_using(name)
    if em_uso:
        raise ImageError("modelo em uso por: " + ", ".join(sorted(em_uso)))
    d = model_dir(name)
    if d.is_dir():
        shutil.rmtree(d)


def add_model_layer(
    name: str, camada: dict, position: int = 0, replace_role: str | None = None
) -> list[dict]:
    """Insere uma camada. A ordem é a prioridade no overlay: posição 0 é a que
    sobrepõe as demais.

    Com `replace_role`, a camada que tiver aquele papel sai e a nova entra **no
    lugar dela**, mantendo a posição. É assim que se troca a base de uma
    temporada para outra: casar por nome de arquivo não funciona, porque o nome
    da base muda todo ano (icpc-latam2025 → maratonalinux2026) e o resultado é
    ficar com duas bases empilhadas — a máquina baixa 13 GB e monta duas raízes
    sobrepostas, em silêncio.
    """
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        atuais = list(tpl.get("layers", []))

        def sai(c: dict) -> bool:
            if c.get("file") == camada["file"]:
                return True
            return bool(replace_role) and c.get("role") == replace_role

        if replace_role:
            # onde estava a camada substituída — a nova entra no mesmo lugar
            alvo = next((i for i, c in enumerate(atuais) if sai(c)), None)
            if alvo is not None:
                position = alvo

        layers = [c for c in atuais if not sai(c)]
        layers.insert(max(0, min(position, len(layers))), camada)
        tpl["layers"] = layers
        fsdb.write_json(model_dir(name) / "model.json", tpl)
    return layers


def remove_model_layer(name: str, file: str) -> list[dict]:
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        tpl["layers"] = [c for c in tpl.get("layers", []) if c.get("file") != file]
        fsdb.write_json(model_dir(name) / "model.json", tpl)
    return tpl["layers"]


def reorder_model_layers(name: str, files: list[str]) -> list[dict]:
    """Reordena pela lista de nomes de arquivo (a primeira ganha no overlay)."""
    with fsdb.locked(model_dir(name)):
        tpl = fsdb.read_json(model_dir(name) / "model.json", {}) or {}
        por_arquivo = {c["file"]: c for c in tpl.get("layers", [])}
        novas = [por_arquivo[f] for f in files if f in por_arquivo]
        # o que não veio na lista fica no fim, para nada sumir por engano
        novas += [c for c in tpl.get("layers", []) if c["file"] not in set(files)]
        tpl["layers"] = novas
        fsdb.write_json(model_dir(name) / "model.json", tpl)
    return novas


# --- site-images (as imagens derivadas de um modelo) ---


def site_image_dir(image_id: str) -> Path:
    return settings.data_root / "site-images" / image_id


def site_image_exists(image_id: str) -> bool:
    return (site_image_dir(image_id) / "image.json").is_file()


def get_site_image(image_id: str) -> dict | None:
    return fsdb.read_json(site_image_dir(image_id) / "image.json")


def list_site_images(prefix: str = "", owner: str | None = None) -> list[dict]:
    base = settings.data_root / "site-images"
    out = []
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if prefix and not p.name.startswith(prefix):
            continue
        info = fsdb.read_json(p / "image.json")
        if not info:
            continue
        if owner is not None and str(info.get("owner") or "admin") != owner:
            continue
        out.append(info)
    return out


def site_image_owner(image_id: str) -> str:
    info = get_site_image(image_id) or {}
    return str(info.get("owner") or "admin")


class ImageError(ValueError):
    pass


def create_site_image(
    image_id: str,
    fullname: str,
    model: str,
    *,
    unlocked: bool = False,
    owner: str = "admin",
    extra: dict | None = None,
) -> dict:
    """Cria a imagem e devolve dict com credenciais em claro (única vez).

    `extra` mescla campos adicionais no image.json (ex.: self_service,
    build_quota, criada por auto-atendimento)."""
    if not IMAGE_ID_RE.match(image_id):
        raise ImageError(
            "id inválido: use 2-32 caracteres [a-z0-9._-], começando por letra ou dígito"
        )
    if not model_exists(model):
        raise ImageError(f"modelo '{model}' não existe")
    if site_image_exists(image_id):
        raise ImageError(f"imagem '{image_id}' já existe")

    namespace = "contest" if reserved_re().match(image_id) else "personal"
    token = auth.new_key("nb3i")
    machine_key = auth.new_key("nb3m")
    boot_key = auth.new_key("nb3b")
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_json(
            d / "image.json",
            {
                "id": image_id,
                "fullname": fullname,
                "model": model,
                "namespace": namespace,
                "unlocked": bool(unlocked),
                "owner": owner,
                "created_at": time.time(),
                **(extra or {}),
            },
        )
        fsdb.write_text(d / "token", token + "\n", mode=0o600)
        fsdb.write_text(d / "machine.key", machine_key + "\n", mode=0o600)
        # a chave de boot vai no nutellaboot.conf do pendrive
        fsdb.write_text(d / "boot.key", boot_key + "\n", mode=0o600)
        fsdb.write_json(d / "config.json", {"values": {}})
        fsdb.write_json(d / "layers-extra.json", [])
    return {
        "id": image_id,
        "fullname": fullname,
        "model": model,
        "namespace": namespace,
        "unlocked": bool(unlocked),
        "owner": owner,
        "token": token,
        "machine_key": machine_key,
        "boot_key": boot_key,
        **_links(image_id, token),
    }


def _links(image_id: str, token: str) -> dict:
    """Links prontos para entregar ao coordenador (com o token embutido)."""
    q = f"?id={image_id}&tk={token}"
    return {
        "configureitor_url": f"{settings.base_url}/configureitor/{q}",
        "hotconfig_url": f"{settings.base_url}/hotconfig/{q}",
    }


def credentials(image_id: str) -> dict:
    """Todas as credenciais e links de uma imagem já existente. Só o admin lê
    isto — os segredos ficam em claro no disco (são o que se distribui, não
    hashes), então é seguro devolvê-los para quem tem a chave de admin."""
    token = (fsdb.read_text(site_image_dir(image_id) / "token") or "").strip()
    info = get_site_image(image_id) or {}
    return {
        "id": image_id,
        "fullname": info.get("fullname", ""),
        "token": token,
        "machine_key": machine_key(image_id),
        "boot_key": boot_key(image_id),
        **_links(image_id, token),
    }


def boot_key(image_id: str) -> str:
    return (fsdb.read_text(site_image_dir(image_id) / "boot.key") or "").strip()


def rotate_boot_key(image_id: str) -> str:
    """Gera nova chave de boot. Atenção: todo pendrive daquela imagem precisa
    ter o nutellaboot.conf atualizado depois disso."""
    chave = auth.new_key("nb3b")
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_text(d / "boot.key", chave + "\n", mode=0o600)
    return chave


def rotate_machine_key(image_id: str, grace_hours: float) -> dict:
    """Troca a chave de máquina. A máquina só recebe a chave no BOOT (ela vem
    no stuff), então quem está ligada continua com a antiga até reiniciar: sem
    carência, a sala inteira fica muda na hora, inclusive para a ordem de
    destravar. Na carência a antiga continua valendo (`machine.key.prev`)."""
    nova = auth.new_key("nb3m")
    d = site_image_dir(image_id)
    ate = int(time.time() + max(0.0, grace_hours) * 3600)
    with fsdb.locked(d):
        antiga = (fsdb.read_text(d / "machine.key") or "").strip()
        if antiga and grace_hours > 0:
            fsdb.write_json(d / "machine.key.prev", {"key": antiga, "valid_until": ate}, mode=0o600)
        else:
            (d / "machine.key.prev").unlink(missing_ok=True)
        fsdb.write_text(d / "machine.key", nova + "\n", mode=0o600)
    return {"machine_key": nova, "previous_valid_until": ate if antiga and grace_hours > 0 else None}


def patch_site_image(image_id: str, fields: dict) -> dict:
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        info = fsdb.read_json(d / "image.json") or {}
        for k in (
            "fullname", "unlocked", "model", "wallpaper_locked", "build_quota",
            "dashboard_hidden", "country",
        ):
            if k in fields and fields[k] is not None:
                if k == "model" and not model_exists(fields[k]):
                    raise ImageError(f"modelo '{fields[k]}' não existe")
                info[k] = fields[k]
        fsdb.write_json(d / "image.json", info)
    return info


# ISO 3166-1 alpha-2. Lista fechada de propósito: o país derivado do id só vale
# se as duas letras forem mesmo um país (`26tete` e `26icpclatamtest` dariam
# "TE" e "IC", que não existem).
_PAISES = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS "
    "BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE "
    "EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM "
    "HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC "
    "LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA "
    "NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
    "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO "
    "TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split()
)
_PAIS_NO_ID = re.compile(r"^\d{2}([a-z]{2})")


def country_of(info: dict) -> str:
    """País da sede (alpha-2), ou "" quando não dá para saber. O campo
    explícito vence; senão, o id das sedes da competição (`26brspsp`) o traz
    depois do ano. Imagem pessoal sem o campo fica sem país: inventar um é
    pior que não dizer."""
    explicito = str(info.get("country") or "").upper()
    if explicito in _PAISES:
        return explicito
    if info.get("namespace") == "contest":
        m = _PAIS_NO_ID.match(str(info.get("id", "")))
        if m and m.group(1).upper() in _PAISES:
            return m.group(1).upper()
    return ""


def site_image_visivel_na_frota(info: dict) -> bool:
    """Falso para a imagem marcada `dashboard_hidden` (a de teste dos times):
    ela existe, tem hotconfig e configureitor, mas não entra em /labs*."""
    return not bool(info.get("dashboard_hidden"))


def delete_site_image(image_id: str) -> None:
    d = site_image_dir(image_id)
    if not d.is_dir():
        return
    # O pendrive pré-configurado (~400 MB) e o estado de publicação vivem fora
    # do diretório da imagem e só o usb.json sabe o nome deles: sem isto o
    # rmtree deixava um .img órfão e um publish/*.json que o retry_failed
    # tentaria reenviar. O .img.gz no servidor de arquivos fica (não há rota
    # de remoção lá).
    from . import publish, usb

    estado = fsdb.read_json(d / "usb.json", {}) or {}
    nome = estado.get("file")
    if nome:
        usb.file_path(nome).unlink(missing_ok=True)
        publish._state_path(nome).unlink(missing_ok=True)
    shutil.rmtree(d)


def rotate_token(image_id: str) -> str:
    token = auth.new_key("nb3i")
    d = site_image_dir(image_id)
    with fsdb.locked(d):
        fsdb.write_text(d / "token", token + "\n", mode=0o600)
    return token


def site_image_layers(image_id: str) -> list[dict]:
    """Camadas extras da site-image primeiro (prioridade no overlay), depois
    as do modelo — mesma semântica do nb2 (template.extra antes do template)."""
    info = get_site_image(image_id) or {}
    extra = fsdb.read_json(site_image_dir(image_id) / "layers-extra.json", []) or []
    tpl = fsdb.read_json(model_dir(info.get("model", "")) / "model.json", {}) or {}
    # a mesma camada pode estar na imagem e no modelo (anexada à imagem pela
    # construção e, depois, ao modelo inteiro): a máquina a montaria duas vezes
    # no lowerdir. Fica a primeira, que é a de maior prioridade.
    vistas: set[str] = set()
    camadas = []
    for c in list(extra) + list(tpl.get("layers", [])):
        arquivo = str(c.get("file", ""))
        if arquivo in vistas:
            continue
        vistas.add(arquivo)
        camadas.append(c)
    return camadas


def config_values(image_id: str) -> dict:
    conf = fsdb.read_json(site_image_dir(image_id) / "config.json", {}) or {}
    return conf.get("values", {})


def machine_key(image_id: str) -> str:
    return (fsdb.read_text(site_image_dir(image_id) / "machine.key") or "").strip()
