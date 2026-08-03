import shutil

from fastapi import APIRouter

from ..settings import VERSION, settings

router = APIRouter()


@router.get("/api/v1/health")
async def health() -> dict:
    from ..services import store

    usage = shutil.disk_usage(settings.data_root if settings.data_root.exists() else "/")
    return {
        "status": "ok",
        "version": VERSION,
        "images": len(store.list_site_images()),
        "models": len(store.list_models()),
        "disk_free_gb": round(usage.free / 2**30, 1),
    }


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}
