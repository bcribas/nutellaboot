import shutil

from fastapi import APIRouter

from ..settings import VERSION, settings

router = APIRouter()


@router.get("/api/v1/health")
async def health() -> dict:
    images_dir = settings.data_root / "images"
    images = sum(1 for p in images_dir.iterdir() if p.is_dir()) if images_dir.is_dir() else 0
    usage = shutil.disk_usage(settings.data_root if settings.data_root.exists() else "/")
    return {
        "status": "ok",
        "version": VERSION,
        "images": images,
        "disk_free_gb": round(usage.free / 2**30, 1),
    }


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}
