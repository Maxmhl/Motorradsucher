"""SQLAlchemy-Modelle - entspricht Abschnitt 4 des Projektplans."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class ListingStatus(enum.StrEnum):
    """Lebenszyklus eines Inserats durch die Pipeline."""

    new = "new"
    text_rejected = "text_rejected"
    text_ok = "text_ok"
    optical_rejected = "optical_rejected"
    optical_ok = "optical_ok"
    analyzed = "analyzed"
    error = "error"


class FinalClass(enum.StrEnum):
    passend = "passend"
    unpassende_optik = "unpassende_optik"
    unpassender_zustand = "unpassender_zustand"


class RunStatus(enum.StrEnum):
    running = "running"
    finished = "finished"
    failed = "failed"
    cancelled = "cancelled"


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    search_url_template: Mapped[str] = mapped_column(Text)
    filter_params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)

    listings: Mapped[list[Listing]] = relationship(back_populates="site")


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"))

    title: Mapped[str | None] = mapped_column(String(512))
    model: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer)
    km: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ListingStatus] = mapped_column(
        String(32), default=ListingStatus.new, index=True
    )
    final_class: Mapped[FinalClass | None] = mapped_column(String(32), index=True)

    # Stufe 2
    text_verdict: Mapped[dict | None] = mapped_column(JSON)
    text_reasoning: Mapped[str | None] = mapped_column(Text)
    # Stufe 3
    optical_verdict: Mapped[dict | None] = mapped_column(JSON)
    optical_reasoning: Mapped[str | None] = mapped_column(Text)
    # Stufe 6
    rank_score: Mapped[float | None] = mapped_column(Float, index=True)
    rank_reasoning: Mapped[str | None] = mapped_column(Text)
    rank_position: Mapped[int | None] = mapped_column(Integer)

    thumbnail_path: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)

    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    site: Mapped[Site | None] = relationship(back_populates="listings")
    images: Mapped[list[Image]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (UniqueConstraint("listing_id", "source_url", name="uq_image_listing_src"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    local_path: Mapped[str | None] = mapped_column(String(512))
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Bleibt dauerhaft erhalten, auch nachdem die Bilddatei geloescht wurde.
    vision_description: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    listing: Mapped[Listing] = relationship(back_populates="images")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[RunStatus] = mapped_column(String(16), default=RunStatus.running, index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual | schedule
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)

    logs: Mapped[list[LogEntry]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(16), default="info")
    stage: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)

    run: Mapped[Run | None] = relationship(back_populates="logs")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
