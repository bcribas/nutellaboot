"""As chaves de administração e de serviço: um lugar só que lê e escreve.

`admin.json` e `services.json` eram mexidos por três pontos (a rota das chaves
de serviço, o `nb3-init`, e à mão na produção), sem lock e sem data. Aqui toda
escrita segura o lock do diretório `keys/`, toda chave nasce com `created_at` e
`created_by`, e as regras que não podem ser esquecidas moram junto do arquivo:

- nunca se revoga a ÚLTIMA chave de admin (seria trancar-se para fora);
- o id de uma chave de admin é único (o `nb3-init` aceitava repetir: com dois
  "admin", revogar um não derrubava sessão nenhuma);
- criar chave de serviço com nome que já existe é erro, não sobrescrita: recriar
  "moj" pela tela trocaria a credencial do MOJ calado. Trocar é `rotacionar`.

Só o hash fica em disco. `fp` é a impressão digital curta (o começo do hash):
serve para dizer "esta chave" sem revelar nada útil sobre uma chave aleatória
de 128 bits.
"""

from __future__ import annotations

import re
import time

from .. import auth, fsdb
from ..settings import settings
from . import keyusage

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
NOME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ErroDeChave(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _dir():
    return settings.data_root / "keys"


def _trava():
    return fsdb.locked(_dir())


def fp_de(sha256: str) -> str:
    return str(sha256)[:8]


# --- administração ---


def _admin() -> dict:
    return fsdb.read_json(_dir() / "admin.json", {"keys": []}) or {"keys": []}


def admin_listar() -> list[dict]:
    out = []
    for e in _admin().get("keys", []):
        fp = fp_de(e.get("sha256", ""))
        out.append(
            {
                "id": e.get("id", "admin"),
                "fp": fp,
                "created_at": e.get("created_at"),
                "created_by": e.get("created_by", ""),
                "last_used": keyusage.ultimo("admin", fp),
            }
        )
    return out


def admin_criar(ident: str, by: str = "") -> dict:
    ident = str(ident or "").strip()
    if not ID_RE.match(ident):
        raise ErroDeChave(400, "invalid_key_id", "id: 1 a 32 caracteres [a-z0-9._-], começando por letra ou dígito")
    chave = auth.new_key("nb3a")
    with _trava():
        atual = _admin()
        if any(e.get("id", "admin") == ident for e in atual.get("keys", [])):
            raise ErroDeChave(409, "key_exists", f"já existe uma chave de admin com o id {ident}")
        agora = int(time.time())
        atual.setdefault("keys", []).append(
            {"id": ident, "sha256": auth.key_hash(chave), "created_at": agora, "created_by": by}
        )
        fsdb.write_json(_dir() / "admin.json", atual, mode=0o600)
    return {"id": ident, "key": chave, "fp": fp_de(auth.key_hash(chave)), "created_at": agora}


def admin_revogar(ident: str, fp: str = "") -> dict:
    with _trava():
        atual = _admin()
        chaves = atual.get("keys", [])
        alvo = [e for e in chaves if e.get("id", "admin") == ident and (not fp or fp_de(e.get("sha256", "")) == fp)]
        if not alvo:
            raise ErroDeChave(404, "key_not_found", "chave de admin não existe")
        if len(alvo) > 1:
            # herança do nb3-init antigo: dois ids iguais. Só a impressão digital desempata.
            raise ErroDeChave(409, "key_ambiguous", f"há {len(alvo)} chaves com o id {ident}: informe fp")
        if len(chaves) <= 1:
            raise ErroDeChave(409, "last_admin_key", "é a última chave de admin: crie outra antes de revogar esta")
        chaves.remove(alvo[0])
        fsdb.write_json(_dir() / "admin.json", atual, mode=0o600)
    revogada = fp_de(alvo[0].get("sha256", ""))
    keyusage.esquecer("admin", revogada)
    return {"id": ident, "fp": revogada, "remaining": len(chaves)}


# --- serviço ---


def _servicos() -> dict:
    return fsdb.read_json(_dir() / "services.json", {}) or {}


def _servico_publico(nome: str, v: dict) -> dict:
    return {
        "name": nome,
        "scopes": v.get("scopes", []),
        "images": v.get("images", []),
        "follow": v.get("follow", ""),
        "created_at": v.get("created_at"),
        "created_by": v.get("created_by", ""),
        "rotated_at": v.get("rotated_at"),
        "last_used": keyusage.ultimo("service", nome),
    }


def servico_listar() -> list[dict]:
    return [_servico_publico(n, v) for n, v in _servicos().items()]


def _confere_follow(follow, escopos) -> str:
    follow = str(follow or "")
    if follow and follow != "admin":
        raise ErroDeChave(400, "bad_request", 'follow: só "admin" (a visão da frota da administração) ou vazio')
    if follow and "labs:read" not in escopos:
        raise ErroDeChave(400, "bad_request", "follow só faz sentido numa chave com labs:read")
    return follow


def servico_criar(nome: str, escopos: list, imagens: list, follow: str = "", by: str = "") -> dict:
    nome = str(nome or "").strip()
    if not nome:
        raise ErroDeChave(400, "bad_request", "informe um nome")
    if not NOME_RE.match(nome):
        raise ErroDeChave(400, "bad_request", "nome: até 64 caracteres [A-Za-z0-9._-]")
    follow = _confere_follow(follow, escopos)
    chave = auth.new_key("nb3s")
    with _trava():
        conf = _servicos()
        if nome in conf:
            raise ErroDeChave(409, "key_exists", f"já existe uma chave de serviço chamada {nome}: rotacione ou revogue")
        conf[nome] = {
            "sha256": auth.key_hash(chave),
            "scopes": list(escopos),
            "images": list(imagens),
            "created_at": int(time.time()),
            "created_by": by,
        }
        if follow:
            conf[nome]["follow"] = follow
        fsdb.write_json(_dir() / "services.json", conf, mode=0o600)
    return {**_servico_publico(nome, conf[nome]), "key": chave}


def servico_alterar(nome: str, campos: dict) -> dict:
    with _trava():
        conf = _servicos()
        if nome not in conf:
            raise ErroDeChave(404, "key_not_found", "chave de serviço não existe")
        v = conf[nome]
        if "scopes" in campos:
            v["scopes"] = list(campos["scopes"] or [])
        if "images" in campos:
            v["images"] = list(campos["images"] or [])
        if "follow" in campos or "scopes" in campos:
            follow = _confere_follow(campos.get("follow", v.get("follow", "")), v["scopes"])
            v.pop("follow", None)
            if follow:
                v["follow"] = follow
        fsdb.write_json(_dir() / "services.json", conf, mode=0o600)
    return _servico_publico(nome, conf[nome])


def servico_rotacionar(nome: str) -> dict:
    """Chave nova, MESMO nome, escopos e globs: a antiga morre na hora."""
    chave = auth.new_key("nb3s")
    with _trava():
        conf = _servicos()
        if nome not in conf:
            raise ErroDeChave(404, "key_not_found", "chave de serviço não existe")
        conf[nome]["sha256"] = auth.key_hash(chave)
        conf[nome]["rotated_at"] = int(time.time())
        fsdb.write_json(_dir() / "services.json", conf, mode=0o600)
    return {**_servico_publico(nome, conf[nome]), "key": chave}


def servico_apagar(nome: str) -> bool:
    with _trava():
        conf = _servicos()
        if nome not in conf:
            return False
        conf.pop(nome)
        fsdb.write_json(_dir() / "services.json", conf, mode=0o600)
    keyusage.esquecer("service", nome)
    return True
