"""Endpoints consumidos pelo initrd, pelo agente e pela tela de bloqueio.

Formato: texto puro, porque quem lê é shell dentro do initramfs, sem jq.

Autenticação: cada imagem tem uma CHAVE DE BOOT (data/images/<id>/boot.key),
que o pendrive carrega no nutellaboot.conf e envia por POST. Sem ela, o
servidor não entrega manifest nem script de boot — no NutellaBoot 2 esses
endpoints eram completamente abertos e bastava saber o nome da sede.

A chave pode chegar de três formas, todas equivalentes:
  - corpo de POST:      key=<chave>          (o que o initrd usa)
  - cabeçalho:          X-NB-Boot-Key        (usado pelo aria2c e pelo curl)
  - query string:       ?key=<chave>         (conveniência para depuração)

Imagens sem boot.key continuam abertas — é o modo de depuração, e some
assim que a imagem é criada pelo próprio nutellaboot3.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .. import auth
from ..services import seeders, store, stuffgen, webhook_push
from ..services.notify import notify
from ..settings import settings

router = APIRouter(prefix="/boot/v3", default_response_class=PlainTextResponse)


async def _key_from(request: Request, header: str | None, query: str | None) -> str | None:
    if header:
        return header
    if query:
        return query
    if request.method == "POST":
        try:
            form = await request.form()
        except Exception:
            return None
        valor = form.get("key")
        return str(valor) if valor is not None else None
    return None


async def _autorizar(request: Request, image: str, header: str | None, query: str | None) -> None:
    """Confere que a imagem existe e que a chave de boot confere."""
    if not store.site_image_exists(image):
        raise HTTPException(404, "imagem não existe")
    chave = await _key_from(request, header, query)
    if not auth.check_boot_key(image, chave):
        raise HTTPException(401, "chave de boot inválida ou ausente")


@router.get("/sanity")
async def sanity() -> str:
    return "penguin\n"


@router.get("/time")
async def server_time() -> str:
    """Hora do servidor, em texto. É o único endpoint que o cliente consulta
    sem validar certificado — existe justamente para corrigir o relógio e
    tornar a validação de TLS possível logo em seguida."""
    return f"{int(time.time())}\n"


@router.get("/{image}/manifest", name="manifest")
@router.post("/{image}/manifest", name="manifest_post")
async def manifest(
    image: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
) -> str:
    """Linhas `MD5 ARQUIVO URL1 URL2 ...` — camadas extras primeiro (maior
    prioridade no overlay). URLs: todos os seeders vivos + CDN por último;
    o aria2c usa todas como espelhos do mesmo arquivo."""
    await _autorizar(request, image, x_nb_boot_key, key)
    live = seeders.live(image)
    out = []
    for layer in store.site_image_layers(image):
        urls = [f"http://{ip}/{layer['file']}" for ip in live]
        if layer.get("cdn_url"):
            urls.append(layer["cdn_url"])
        if not urls:
            raise HTTPException(500, f"camada {layer['file']} sem nenhuma fonte")
        out.append(f"{layer['md5']} {layer['file']} {' '.join(urls)}")
    return "\n".join(out) + "\n"


@router.get("/{image}/stuff", name="stuff")
@router.post("/{image}/stuff", name="stuff_post")
async def stuff(
    image: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
) -> str:
    await _autorizar(request, image, x_nb_boot_key, key)
    return stuffgen.render(image)


@router.post("/{image}/seeders/join", name="seeder_join")
@router.post("/{image}/seeders/heartbeat", name="seeder_heartbeat")
async def seeder_join(
    image: str,
    request: Request,
    ip: str = Query(...),
    key: str | None = Query(None),
    x_nb_boot_key: str | None = Header(None),
) -> str:
    """join e heartbeat: registra/renova o seeder com a chave de boot."""
    await _autorizar(request, image, x_nb_boot_key, key)
    if not seeders.valid_ip(ip):
        raise HTTPException(400, "bad ip")
    novo = ip not in seeders.live(image)
    seeders.touch(image, ip)
    if novo:
        # também estava no catálogo sem nunca ser emitido; só no join, não no
        # heartbeat, senão viraria um evento por máquina a cada poucos minutos
        notify.publish(image, {"event": "seeder.joined", "data": {"ip": ip}, "at": time.time()})
        webhook_push.emit(image, "seeder.joined", {"ip": ip})
    return "ok\n"


@router.post("/{image}/seeders/leave")
async def seeder_leave(image: str, ip: str = Query(...)) -> str:
    # sem chave, como o `out` do nb2: só remove uma entrada — inócuo.
    if not store.site_image_exists(image):
        raise HTTPException(404, "imagem não existe")
    seeders.leave(image, ip)
    return "ok\n"


@router.get("/{image}/machines/{mac}/lockstate", name="lockstate")
@router.post("/{image}/machines/{mac}/lockstate", name="lockstate_post")
async def lockstate(
    image: str,
    mac: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
) -> str:
    """Consultado pela própria tela de bloqueio a cada poucos segundos —
    redundância caso o agente esteja travado."""
    await _autorizar(request, image, x_nb_boot_key, key)
    from ..services import machines as m

    return "locked\n" if m.get_lock(image, m.normalize_mac(mac)).get("locked") else "unlocked\n"


@router.get("/{image}/lockinfo/{mac}", name="lockinfo", response_class=JSONResponse)
@router.post("/{image}/lockinfo/{mac}", name="lockinfo_post", response_class=JSONResponse)
async def lockinfo(
    image: str,
    mac: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
) -> dict:
    """Dados exibidos na tela de bloqueio (time, organização, país, lugar)."""
    await _autorizar(request, image, x_nb_boot_key, key)
    from ..services import machines as m
    from .roster import lockinfo as build

    return build(image, m.normalize_mac(mac))


@router.get("/{image}/roster/logos/{org_id}", name="roster_logo")
@router.post("/{image}/roster/logos/{org_id}", name="roster_logo_post")
async def roster_logo(
    image: str,
    org_id: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
):
    await _autorizar(request, image, x_nb_boot_key, key)
    from .roster import logo_response

    return logo_response(image, org_id)


@router.get("/{image}/usb", name="usbcheck")
@router.post("/{image}/usb", name="usbcheck_post")
async def usbcheck(
    image: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
) -> str:
    """Como a máquina descobre que o pendrive de onde ela bootou está velho.

    Primeira linha `BUILD <id>`; depois, uma linha por arquivo no MESMO formato
    do manifest de camadas (`MD5 ARQUIVO URL`), para o cliente reaproveitar
    `nb_download` e `nutella_md5sum` sem parser novo.

    Sem `build.json` em client/build (construção anterior a isto), responde
    `BUILD unknown` e o cliente não faz nada — não dá para exigir que um
    pendrive se atualize para uma versão que o servidor não sabe nomear.
    """
    await _autorizar(request, image, x_nb_boot_key, key)
    from ..services import usb

    info = usb.build_info()
    if not info["build"]:
        return "BUILD unknown\n"
    base = f"{settings.base_url}/boot/v3/{image}/usbfile"
    linhas = [f"BUILD {info['build']}"]
    linhas += [f"{info['files'][n]['md5']} {n} {base}/{n}" for n in usb.ARQUIVOS_DE_BOOT]
    return "\n".join(linhas) + "\n"


@router.get("/{image}/usbfile/{name}", name="usbfile")
@router.post("/{image}/usbfile/{name}", name="usbfile_post")
async def usbfile(
    image: str,
    name: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
):
    """O kernel e o initrd desta construção, para a máquina regravar o pendrive.

    `name` sai de uma lista fechada: é caminho vindo da URL indo para o disco,
    e o diretório vizinho tem a chave de boot de todas as sedes.
    """
    await _autorizar(request, image, x_nb_boot_key, key)
    from ..services import usb

    if name not in usb.ARQUIVOS_DE_BOOT:
        raise HTTPException(404, "arquivo desconhecido")
    caminho = usb.build_dir() / name
    if not caminho.is_file():
        raise HTTPException(404, "arquivo não existe")
    return FileResponse(caminho, media_type="application/octet-stream", filename=name)


@router.get("/{image}/clionkey", name="clionkey")
@router.post("/{image}/clionkey", name="clionkey_post")
async def clionkey(
    image: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
):
    """A licença do CLion, com credencial de boot.

    No nb2 ela ficava num /secret/ público — licença paga atrás de URL
    obscura. Aqui só sai para quem tem a chave de boot de uma sede, pelo mesmo
    caminho do wallpaper. O arquivo é DADO, não código: mora em
    data/secret/clion.key (o repositório é público, a chave nunca entra nele).
    """
    await _autorizar(request, image, x_nb_boot_key, key)
    caminho = settings.data_root / "secret" / "clion.key"
    if not caminho.is_file():
        raise HTTPException(404, "chave do CLion não instalada neste servidor")
    return FileResponse(caminho, media_type="application/octet-stream")


@router.get("/{image}/wallpaper", name="wallpaper")
@router.post("/{image}/wallpaper", name="wallpaper_post")
async def wallpaper(
    image: str,
    request: Request,
    x_nb_boot_key: str | None = Header(None),
    key: str | None = Query(None),
):
    await _autorizar(request, image, x_nb_boot_key, key)
    from ..services import wallpaper as wp

    # o da sede, ou o do modelo: a herança é resolvida na hora de servir, para
    # que trocar no modelo chegue a toda sede no boot seguinte
    achado = wp.efetivo(image)
    if not achado:
        raise HTTPException(404, "sem wallpaper")
    path, meta = achado
    return FileResponse(
        path,
        media_type=meta.get("content_type", "image/png"),
        headers={"ETag": f'"{meta["md5"]}"'},
    )
