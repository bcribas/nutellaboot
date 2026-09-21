"""Lista de times/usuários (roster) e vínculo usuário↔máquina.

O MOJ envia o roster com os dados que a tela de bloqueio exibe (nome do time,
organização, país) e os logotipos como blob. O vínculo aponta para uma entrada
do roster.

No nb2 isso era um grafo de symlinks em times-maquina/ criado por um CGI SEM
autenticação nenhuma, que interpolava parâmetros do usuário direto em `rm` e
`ln -s`.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from .. import auth, fsdb
from ..errors import codigo_de, erro
from ..services import bindings
from ..services import roster as ros
from ..services import machines as m
from ..services import store
from ..services import eventos

router = APIRouter(prefix="/api/v1")


def _publish(image: str, event: str, data: dict) -> None:
    """Avisa a tela (SSE) E os sistemas externos (webhooks).

    Estas duas rotas publicavam só no SSE: o painel via o vínculo mudar em
    tempo real, mas um webhook do MOJ inscrito em machine.bound nunca
    disparava, apesar de a documentacao prometer.
    """
    eventos.publicar(image, event, data)

LOGO_MAX = 2 * 1024 * 1024
LOGO_TYPES = {
    b"<svg": ("svg", "image/svg+xml"),
    b"<?xm": ("svg", "image/svg+xml"),
    b"\x89PNG": ("png", "image/png"),
}


def _roster(image: str) -> list[dict]:
    return ros.ler(image)


# As rotas de escrita são `def`: seguram lock e varrem disco (invariante 2), e
# publicam por `_publish` DEPOIS de soltar o lock.


@router.get("/site-images/{image}/roster")
async def get_roster(
    image: str, p=Depends(auth.require_image_access(service_scope="roster:read"))
) -> dict:
    # `logos`: quais organizações já têm logotipo (a tela não tinha como saber)
    return {"roster": _roster(image), "logos": ros.logos(image)}


@router.put("/site-images/{image}/roster")
def put_roster(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="roster:write"))
) -> dict:
    """A lista inteira. Nunca apaga vínculo: o time omitido que está vinculado a
    uma máquina continua no roster, marcado `source: "binding"` (`kept_bound`)."""
    roster = body.get("roster", body if isinstance(body, list) else None)
    if not isinstance(roster, list):
        raise HTTPException(400, "esperava {roster: [...]}")
    try:
        n, mantidos = ros.substituir(image, roster)
    except ValueError as e:
        raise erro(400, "invalid_roster_entry", str(e))
    return {"ok": True, "entries": n, "kept_bound": mantidos}


@router.post("/site-images/{image}/roster")
def upsert_roster_entry(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="roster:write"))
) -> dict:
    """Acrescenta ou atualiza UM time, pelo `user_id`, sem ler-e-regravar a
    lista (que era corrida entre a tela e o MOJ)."""
    try:
        entrada, criada = ros.upsert(image, body)
    except ValueError as e:
        raise erro(400, "invalid_roster_entry", str(e))
    return {"ok": True, "created": criada, "entry": entrada}


@router.delete("/site-images/{image}/roster/{user_id}", status_code=204)
def delete_roster_entry(
    image: str, user_id: str, p=Depends(auth.require_image_access(service_scope="roster:write"))
) -> None:
    """Tira UM time. O vínculo dele, se houver, NÃO é desfeito: desvincular é
    outra rota, e a tela de bloqueio segue mostrando o que o vínculo guardou."""
    if not ros.remover(image, user_id):
        raise erro(404, "user_not_in_roster", f"user_id {user_id} não está no roster desta imagem")


@router.get("/site-images/{image}/roster/logos/{org_id}")
async def get_logo(image: str, org_id: str, request: Request, tk: str = Query("")) -> FileResponse:
    """O logotipo, para a tela (`<img>` não manda cabeçalho: vale `?tk=` ou o
    cookie, como a prévia do wallpaper). O SVG vem de quem tem o token da sede,
    então sai trancado: aberto direto no navegador não roda script."""
    p = auth.principal_de_link(request, tk, image)
    if p is None:
        raise erro(401, "unauthorized", "credencial ausente ou inválida")
    if p.kind == "service":
        if "roster:read" not in p.scopes:
            raise erro(403, "insufficient_scope", "escopo insuficiente")
        if not p.can_see_image(image):
            raise erro(403, "image_out_of_scope", "sem acesso a esta imagem")
    elif not p.can_see_image(image):
        raise erro(404, "image_not_found", "imagem não existe")
    resposta = logo_response(image, org_id)
    resposta.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta


@router.put("/site-images/{image}/roster/logos/{org_id}")
async def put_logo(
    image: str,
    org_id: str,
    file: UploadFile = File(...),
    p=Depends(auth.require_image_access(service_scope="roster:write")),
) -> dict:
    if "/" in org_id or ".." in org_id:
        raise HTTPException(400, "identificador de organização inválido")
    data = await file.read(LOGO_MAX + 1)
    if len(data) > LOGO_MAX:
        raise HTTPException(413, "logotipo grande demais")
    head = data[:4]
    kind = next((v for k, v in LOGO_TYPES.items() if head.startswith(k)), None)
    if kind is None:
        raise HTTPException(400, "envie SVG ou PNG")
    ext, _ = kind
    d = store.site_image_dir(image) / "roster" / "logos"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{org_id}.*"):
        old.unlink()
    (d / f"{org_id}.{ext}").write_bytes(data)
    return {"ok": True, "org_id": org_id, "format": ext, "size": len(data)}


def _fonte(p, body: dict) -> str:
    """Quem afirmou o vínculo: o MOJ diz `source` explícito (ex.: "moj-login");
    sem ele, deriva da credencial."""
    s = str(body.get("source") or "").strip()[:40]
    if s:
        return s
    return f"service:{p.name}" if p.kind == "service" else "console"


def _entrada_do_corpo(body: dict, opcao) -> dict:
    """Os campos do time para `create_roster_entry`: o objeto, ou o próprio
    corpo do vínculo quando a opção é só `true`."""
    fonte = opcao if isinstance(opcao, dict) else body
    return {
        "user_id": body.get("user_id"),
        **{k: fonte[k] for k in ("name", "display_name", "organization", "country", "seat") if k in fonte},
    }


def _vincular(image: str, mac: str, body: dict, p, lista: list[dict], criar) -> tuple[dict, bool]:
    """Monta e grava um vínculo. `lista` é o roster já lido (quem chama segura
    o lock do roster); devolve o vínculo e se criou entrada no roster."""
    mac = m.normalize_mac(mac)
    if not m.valid_mac(mac):
        raise erro(400, "invalid_mac", "MAC inválido")
    user_id = body.get("user_id")
    binding = {"bound_at": int(time.time()), "by": p.name, "source": _fonte(p, body)}
    if body.get("at") is not None:
        try:
            binding["client_at"] = int(float(body["at"]))
        except (TypeError, ValueError):
            raise HTTPException(400, "at precisa ser epoch numérico")
    if body.get("boot_id"):
        binding["boot_id"] = str(body["boot_id"])[:64]
    if body.get("note"):
        binding["note"] = str(body["note"])[:200]
    criou = False
    if user_id:
        entry = ros.achar(lista, user_id)
        if entry is None and criar:
            # opt-in: o user_id nasce de um User-Agent, que é entrada do cliente
            entry, criou = ros.garantir(lista, _entrada_do_corpo(body, criar))
        if entry is None:
            raise erro(404, "user_not_in_roster", f"user_id {user_id} não está no roster desta imagem")
        binding.update({"user_id": entry["user_id"], "seat": body.get("seat", entry.get("seat", ""))})
    else:
        binding.update(
            {
                "name": str(body.get("name", "")),
                "seat": str(body.get("seat", "")),
            }
        )
    bindings.gravar(image, mac, binding)
    return {"mac": mac, **binding}, criou


@router.put("/site-images/{image}/machines/{mac}/binding")
def put_binding(
    image: str, mac: str, body: dict, p=Depends(auth.require_image_access(service_scope="bindings:write"))
) -> dict:
    """Vincula a máquina a um time. `bound_at`/`by` são do servidor; `at` do
    cliente vira `client_at` (o instante do login no juiz), `boot_id` diz em
    qual boot, `note` é texto livre. Toda mudança fica no histórico.

    `create_roster_entry` (`true`, ou um objeto com os campos do time) cria a
    entrada do roster quando o `user_id` ainda não está lá, marcada
    `source: "binding"`: é o login do time funcionando com o roster vazio."""
    criar = body.get("create_roster_entry")
    with ros.trava(image):
        lista = ros.ler(image)
        com_mac, criou = _vincular(image, mac, body, p, lista, criar)
        if criou:
            ros.gravar(image, lista)
    binding = {k: v for k, v in com_mac.items() if k != "mac"}
    _publish(image, "machine.bound", com_mac)
    return {**binding, "roster_entry_created": True} if criou else binding


LOTE_MAX = 1000


@router.put("/site-images/{image}/bindings")
def put_bindings(
    image: str, body: dict, p=Depends(auth.require_image_access(service_scope="bindings:write"))
) -> dict:
    """Vários vínculos de uma vez (a largada da prova são milhares de logins em
    minutos; o replay do MOJ, a frota inteira). Cada item é o corpo do vínculo
    unitário mais `mac`. Um item ruim não derruba os outros: o resultado vem
    por item."""
    itens = body.get("bindings")
    if not isinstance(itens, list):
        raise HTTPException(400, "esperava {bindings: [...]}")
    if len(itens) > LOTE_MAX:
        raise erro(413, "payload_too_large", f"no máximo {LOTE_MAX} vínculos por pedido")
    geral = body.get("create_roster_entry")
    resultados, feitos = [], []
    with ros.trava(image):
        lista = ros.ler(image)
        mexeu = False
        for item in itens:
            if not isinstance(item, dict):
                resultados.append({"mac": "", "ok": False, "code": "bad_request", "detail": "cada item é um objeto"})
                continue
            try:
                com_mac, criou = _vincular(
                    image, str(item.get("mac", "")), item, p, lista, item.get("create_roster_entry", geral)
                )
            except HTTPException as e:
                resultados.append(
                    {"mac": str(item.get("mac", "")), "ok": False, "code": codigo_de(e), "detail": e.detail}
                )
                continue
            mexeu = mexeu or criou
            feitos.append(com_mac)
            resultados.append({"mac": com_mac["mac"], "ok": True, "binding": {k: v for k, v in com_mac.items() if k != "mac"}})
        if mexeu:
            ros.gravar(image, lista)
    # um evento por vínculo, como no unitário (o painel e os webhooks já o
    # entendem), e só agora, com o lock solto
    for com_mac in feitos:
        _publish(image, "machine.bound", com_mac)
    return {"results": resultados, "bound": len(feitos), "failed": len(itens) - len(feitos)}


@router.delete("/site-images/{image}/machines/{mac}/binding", status_code=204)
async def delete_binding(
    image: str, mac: str, p=Depends(auth.require_image_access(service_scope="bindings:write"))
) -> None:
    mac = m.normalize_mac(mac)
    bindings.remover(image, mac, by=p.name, source=_fonte(p, {}))
    _publish(image, "machine.unbound", {"mac": mac})


@router.get("/site-images/{image}/machines/{mac}/binding/history")
async def binding_history(
    image: str,
    mac: str,
    n: int = Query(200, ge=1, le=2000),
    p=Depends(auth.require_image_access(service_scope="machines:read")),
) -> dict:
    """As últimas mudanças de vínculo da máquina (bound/unbound): a troca de
    máquina no meio da prova é informação, não ruído."""
    return {"history": bindings.history(image, m.normalize_mac(mac), n)}


@router.get("/site-images/{image}/bindings")
async def list_bindings(
    image: str, p=Depends(auth.require_image_access(service_scope="machines:read"))
) -> dict:
    out = []
    for mac in m.list_macs(image):
        b = fsdb.read_json(m.machine_dir(image, mac) / "binding.json")
        if b:
            out.append({"mac": mac, **b})
    return {"bindings": out}


# --- consumido pela tela de bloqueio (sem autenticação, como o resto do boot) ---


def lockinfo(image: str, mac: str) -> dict:
    info = store.get_site_image(image) or {}
    binding = fsdb.read_json(m.machine_dir(image, mac) / "binding.json") or {}
    entry = {}
    if binding.get("user_id"):
        entry = next(
            (e for e in _roster(image) if e["user_id"] == binding["user_id"]), {}
        )
    org = entry.get("organization") or {}
    org_id = str(org.get("id", ""))
    logo_url = ""
    if org_id:
        d = store.site_image_dir(image) / "roster" / "logos"
        if any(d.glob(f"{org_id}.*")) if d.is_dir() else False:
            logo_url = f"/boot/v3/{image}/roster/logos/{org_id}"
    return {
        "site": info.get("fullname", image),
        "image": image,
        "mac": mac,
        "seat": binding.get("seat", ""),
        "team": {
            "name": entry.get("name", binding.get("name", "")),
            "display_name": entry.get("display_name", ""),
        },
        "organization": {"id": org_id, "name": org.get("name", ""), "logo_url": logo_url},
        "country": entry.get("country", ""),
    }


def logo_response(image: str, org_id: str) -> FileResponse:
    if "/" in org_id or ".." in org_id:
        raise HTTPException(400, "identificador inválido")
    d = store.site_image_dir(image) / "roster" / "logos"
    for ext, media in (("svg", "image/svg+xml"), ("png", "image/png")):
        f = d / f"{org_id}.{ext}"
        if f.is_file():
            return FileResponse(f, media_type=media)
    raise HTTPException(404, "sem logotipo")
