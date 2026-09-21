"""Modelos Pydantic da API JSON."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SiteImageCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,31}$")
    fullname: str = ""
    model: str
    unlocked: bool = False
    wallpaper_locked: bool = False
    # fora das visões da frota (/labs*, dashboard, laboratórios): a imagem de
    # teste dos times não pode inflar o placar nem o perfil de hardware
    dashboard_hidden: bool = False
    # ISO 3166-1 alpha-2. Opcional: nas sedes da Maratona o id já diz o país
    # (`26brsp…`); serve para a imagem cujo id não diz (ver store.country_of)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class SiteImagePatch(BaseModel):
    fullname: str | None = None
    unlocked: bool | None = None
    model: str | None = None
    wallpaper_locked: bool | None = None
    dashboard_hidden: bool | None = None
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    # só o admin altera (ver routers/images.py): é a cota que contém o
    # auto-atendimento, e quem pode aumentá-la sozinho não tem cota
    build_quota: int | None = Field(default=None, ge=0)


class BulkRow(BaseModel):
    id: str
    fullname: str = ""
    model: str
    unlocked: bool = False
    wallpaper_locked: bool = False


class BulkRequest(BaseModel):
    rows: list[BulkRow]


class ModelLayers(BaseModel):
    layers: list[dict]
