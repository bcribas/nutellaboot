"""Configuração por imagem: leitura, validação contra o esquema e escrita.

Regras que valem a pena ter em mente:
 - campos `locked` são o "perfil bloqueado" da maratona: só a administração
   muda (o nb2 fazia isso mantendo DOIS diretórios de modelo, um normal e um
   "-desbloqueado", que precisavam ser mantidos em sincronia à mão);
 - senha nunca volta pela API nem fica em claro no disco: guardamos
   `<chave>_HASH` = sha256(salt + senha) e só o hash chega à máquina;
 - salvar configuração NUNCA faz download (o nb2 buscava o wallpaper pela URL
   na hora de salvar, e uma URL ruim derrubava o salvamento inteiro).
"""

from __future__ import annotations

import hashlib
import re
import secrets

from .. import fsdb
from .store import config_values, get_site_image, model_dir, site_image_dir


class ConfigError(ValueError):
    pass


# Metadados que descrevem o CONTRATO com o cliente, não uma escolha do modelo:
# como a lista é juntada no stuff e que forma um item precisa ter. O
# schema.json de um modelo é gravado na criação e nunca mais revisto, então
# sem isto uma regra nova só valeria para modelos criados depois dela — e os
# que estão em produção seguiriam aceitando o valor que quebra a máquina.
HERDADOS_DO_PADRAO = ("sep", "item_pattern")


def schema_for(image_id: str) -> dict:
    info = get_site_image(image_id) or {}
    schema = fsdb.read_json(model_dir(info.get("model", "")) / "schema.json", {"fields": []})
    return _com_padroes(schema)


def _com_padroes(schema: dict) -> dict:
    from .default_schema import build_default_schema

    padrao = {f["key"]: f for f in build_default_schema().get("fields", [])}
    for f in schema.get("fields", []):
        base = padrao.get(f.get("key"))
        if not base:
            continue
        for chave in HERDADOS_DO_PADRAO:
            if chave not in f and chave in base:
                f[chave] = base[chave]
    return schema


def _field_map(schema: dict) -> dict:
    return {f["key"]: f for f in schema.get("fields", [])}


def effective_values(image_id: str) -> dict:
    """Valores atuais: padrão do esquema, sobrescrito pelo que a imagem salvou.
    Campos bloqueados sempre voltam ao padrão do modelo."""
    schema = schema_for(image_id)
    info = get_site_image(image_id) or {}
    unlocked = bool(info.get("unlocked"))
    saved = config_values(image_id)

    if not schema.get("fields"):
        # Template sem schema.json: em vez de mandar a máquina bootar sem
        # nenhuma configuração (falha silenciosa), repassa o que foi salvo.
        return {k: v for k, v in saved.items() if not k.endswith("_HASH")}

    out = {}
    for f in schema.get("fields", []):
        key = f["key"]
        if f.get("type") == "password":
            continue  # senha não é devolvida
        if f.get("locked") and not unlocked:
            out[key] = f.get("default")
        else:
            out[key] = saved.get(key, f.get("default"))
    return out


def _coerce(field: dict, value):
    ftype = field.get("type", "text")
    key = field["key"]
    if ftype == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("t", "true", "1", "yes", "sim"):
            return True
        if str(value).lower() in ("f", "false", "0", "no", "não", "nao"):
            return False
        raise ConfigError(f"{key}: valor booleano inválido ({value!r})")
    if ftype == "select":
        allowed = [o["value"] for o in field.get("options", [])]
        if str(value) not in allowed:
            raise ConfigError(f"{key}: opção inválida ({value!r})")
        return str(value)
    if ftype == "list":
        if not isinstance(value, list):
            raise ConfigError(f"{key}: esperava uma lista")
        allowed = [o["value"] for o in field.get("options", [])]
        if allowed:
            for v in value:
                if v not in allowed:
                    raise ConfigError(f"{key}: item inválido ({v!r})")
            return [str(v) for v in value]
        # Lista livre: o item vira texto dentro do stuff e o consumidor o
        # separa por `sep`. Um item vazio, com quebra de linha ou com o próprio
        # separador dentro vira entrada fantasma lá na frente — e o `text` já
        # recusava quebra de linha, então a assimetria era só descuido.
        sep = field.get("sep", ",")
        padrao = field.get("item_pattern")
        itens = []
        for v in value:
            v = str(v).strip()
            if not v:
                raise ConfigError(f"{key}: item vazio")
            if "\n" in v or "\r" in v:
                raise ConfigError(f"{key}: item não pode conter quebra de linha")
            if sep in v:
                raise ConfigError(f"{key}: item não pode conter {sep!r} ({v!r})")
            if padrao and not re.fullmatch(padrao, v):
                raise ConfigError(f"{key}: formato inválido ({v!r})")
            itens.append(v)
        return itens
    if ftype in ("text", "password"):
        if not isinstance(value, str):
            raise ConfigError(f"{key}: esperava texto")
        if "\n" in value or "\r" in value:
            raise ConfigError(f"{key}: não pode conter quebra de linha")
        return value
    raise ConfigError(f"{key}: tipo desconhecido ({ftype})")


def hash_password(password: str) -> str:
    """sha256(salt + senha), no formato salt$hash — a máquina confere offline."""
    salt = secrets.token_hex(8)
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${digest}"


def check_password(stored: str, password: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    return secrets.compare_digest(
        digest, hashlib.sha256((salt + password).encode()).hexdigest()
    )


def write_values(image_id: str, incoming: dict, *, is_admin: bool) -> dict:
    schema = schema_for(image_id)
    fields = _field_map(schema)
    info = get_site_image(image_id) or {}
    unlocked = bool(info.get("unlocked"))

    d = site_image_dir(image_id)
    with fsdb.locked(d):
        current = fsdb.read_json(d / "config.json", {"values": {}}) or {"values": {}}
        values = dict(current.get("values", {}))

        for key, value in incoming.items():
            field = fields.get(key)
            if field is None:
                raise ConfigError(f"{key}: campo não existe neste modelo")
            if field.get("locked") and not (is_admin or unlocked):
                raise ConfigError(f"{key}: campo bloqueado pela organização da maratona")

            if field.get("type") == "password":
                # em branco = manter a senha atual
                if value == "":
                    continue
                values[f"{key}_HASH"] = hash_password(_coerce(field, value))
                continue
            values[key] = _coerce(field, value)

        fsdb.write_json(d / "config.json", {"values": values})
    return effective_values(image_id)
