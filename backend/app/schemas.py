"""Pydantic-Schemas der API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_url: str
    vision_description: str | None = None
    deleted_at: datetime | None = None


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    site: str | None = None
    title: str | None = None
    model: str | None = None
    price: int | None = None
    year: int | None = None
    km: int | None = None
    location: str | None = None
    description: str | None = None
    status: str
    final_class: str | None = None
    text_verdict: dict[str, Any] | None = None
    text_reasoning: str | None = None
    optical_verdict: dict[str, Any] | None = None
    optical_reasoning: str | None = None
    rank_score: float | None = None
    rank_reasoning: str | None = None
    rank_position: int | None = None
    thumbnail_url: str | None = None
    first_seen: datetime
    last_updated: datetime
    images: list[ImageOut] = Field(default_factory=list)


class ListingPage(BaseModel):
    items: list[ListingOut]
    total: int
    hidden: int = 0


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    stage_stats: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    ts: datetime
    level: str
    stage: str | None
    message: str


class ModelOut(BaseModel):
    name: str
    size_gb: float | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    family: str | None = None
    fit: str
    vision_capable: bool = False


class ModelsResponse(BaseModel):
    endpoints: list[dict[str, Any]]
    models: list[ModelOut]
    error: str | None = None


class SettingsIn(BaseModel):
    """Alle Felder optional - es wird nur überschrieben, was gesendet wird."""

    text_model: str | None = None
    vision_model: str | None = None
    interpretation_model: str | None = None
    ranking_model: str | None = None
    criteria: dict[str, Any] | None = None
    text_exclusions: str | None = None
    optical_criteria: str | None = None
    top_n_rejected: int | None = Field(default=None, ge=0, le=100)
    keep_thumbnail: bool | None = None
    max_listings_per_run: int | None = Field(default=None, ge=1, le=5000)
    schedule_enabled: bool | None = None
    schedule_cron: str | None = None


class DashboardOut(BaseModel):
    runner: dict[str, Any]
    scheduler: dict[str, Any]
    latest_run: RunOut | None = None
    counts: dict[str, int]
    ollama: list[dict[str, Any]]


class SiteOut(BaseModel):
    key: str
    name: str
    enabled: bool
    fetcher: str
    search_url_template: str
