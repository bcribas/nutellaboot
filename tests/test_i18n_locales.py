"""As três traduções precisam ter exatamente as mesmas chaves.

Sem isto, uma string nova entra só em português e as telas em inglês/espanhol
mostram a chave crua para quem estiver operando a sala.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "web" / "common" / "locales"
LANGS = ("pt", "en", "es")


def load(lang: str) -> dict:
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_same_keys_in_all_languages():
    dicts = {lang: load(lang) for lang in LANGS}
    base = set(dicts["pt"])
    for lang in LANGS[1:]:
        faltando = base - set(dicts[lang])
        sobrando = set(dicts[lang]) - base
        assert not faltando, f"{lang}.json sem: {sorted(faltando)}"
        assert not sobrando, f"{lang}.json tem chaves a mais: {sorted(sobrando)}"


def test_no_empty_translations():
    for lang in LANGS:
        vazias = [k for k, v in load(lang).items() if not str(v).strip()]
        assert vazias == [], f"{lang}.json com valores vazios: {vazias}"


def test_placeholders_match_across_languages():
    """{n}, {cmd}… precisam existir nas três versões, senão o texto sai furado."""
    dicts = {lang: load(lang) for lang in LANGS}
    for key, pt_value in dicts["pt"].items():
        esperado = set(re.findall(r"\{(\w+)\}", pt_value))
        for lang in LANGS[1:]:
            achado = set(re.findall(r"\{(\w+)\}", dicts[lang][key]))
            assert achado == esperado, (
                f"{key}: placeholders diferentes entre pt {sorted(esperado)} "
                f"e {lang} {sorted(achado)}"
            )


def test_keys_used_in_pages_exist():
    """Toda chave referenciada no HTML/JS precisa existir nos dicionários."""
    base = set(load("pt"))
    faltando = set()
    for path in (REPO / "web").rglob("*"):
        if path.suffix not in (".html", ".js") or "locales" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', text):
            if m.group(1) not in base:
                faltando.add(f"{path.name}:{m.group(1)}")
        for m in re.finditer(r"\bt\(\s*[\"']([a-z0-9_]+)[\"']", text):
            if m.group(1) not in base:
                faltando.add(f"{path.name}:{m.group(1)}")
    assert faltando == set(), f"chaves usadas mas não traduzidas: {sorted(faltando)}"


def test_schema_labels_are_trilingual():
    """Os rótulos do esquema de configuração vêm da API e também precisam
    existir nos três idiomas."""
    import sys

    sys.path.insert(0, str(REPO))
    from server.app.services.default_schema import build_default_schema

    for field in build_default_schema()["fields"]:
        for attr in ("label", "help"):
            value = field.get(attr)
            if value is None:
                continue
            assert set(value) == set(LANGS), f"{field['key']}.{attr}: idiomas {sorted(value)}"
            for lang, text in value.items():
                assert text.strip(), f"{field['key']}.{attr}.{lang} vazio"
