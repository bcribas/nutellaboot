"""Modelos Pydantic da API JSON."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SiteImageCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,31}$")
    fullname: str = ""
    model: str
    unlocked: bool = False
    wallpaper_locked: bool = False


class SiteImagePatch(BaseModel):
    fullname: str | None = None
    unlocked: bool | None = None
    model: str | None = None
    wallpaper_locked: bool | None = None


class BulkRow(BaseModel):
    id: str
    fullname: str = ""
    model: str
    unlocked: bool = False


class BulkRequest(BaseModel):
    rows: list[BulkRow]


class ModelLayers(BaseModel):
    layers: list[dict]
