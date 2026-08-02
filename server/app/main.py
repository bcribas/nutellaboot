from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from .routers import (
    boot,
    config,
    health,
    images,
    invites,
    layers,
    machines,
    public,
    roster,
    webhooks,
)
from .settings import REPO_ROOT, VERSION, settings


def _operation_id(route: APIRoute) -> str:
    """Identificador único por rota+método.

    Várias rotas de boot aceitam GET e POST (a chave de boot pode vir no
    corpo ou no cabeçalho); sem incluir o método, o OpenAPI publicado sai com
    identificadores repetidos.
    """
    metodos = "_".join(sorted(m.lower() for m in route.methods if m != "HEAD"))
    return f"{route.name}_{metodos}"


def create_app() -> FastAPI:
    app = FastAPI(
        title="NutellaBoot 3",
        version=VERSION,
        description="Sistema de boot em rede da Maratona SBC de Programação",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        generate_unique_id_function=_operation_id,
    )
    app.include_router(health.router)
    app.include_router(boot.router)
    app.include_router(images.router)
    app.include_router(config.router)
    app.include_router(machines.router)
    app.include_router(roster.router)
    app.include_router(webhooks.router)
    app.include_router(layers.router)
    app.include_router(invites.router)
    app.include_router(public.router)

    # squashfs construídos localmente (camadas extras) ficam disponíveis para
    # o boot baixar, com o md5 conferido pelo manifest.
    blobs = settings.data_root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    app.mount("/blobs", StaticFiles(directory=blobs), name="blobs")

    # Os temas da tela de bloqueio moram junto com o agente (vão embarcados na
    # imagem); aqui são servidos só para pré-visualização em /lock/.
    temas = REPO_ROOT / "client" / "telemetry" / "usr" / "share" / "maratona-lock" / "themes"
    if temas.is_dir():
        app.mount("/lock/themes", StaticFiles(directory=temas, html=True), name="lock-themes")

    # documentação legível a partir do próprio servidor (a home aponta para cá)
    docs = REPO_ROOT / "docs"
    if docs.is_dir():
        app.mount("/docs", StaticFiles(directory=docs), name="docs")

    web = REPO_ROOT / "web"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app


app = create_app()
