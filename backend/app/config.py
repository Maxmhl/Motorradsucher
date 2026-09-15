"""Prozessweite Konfiguration (aus Umgebungsvariablen / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_base_url_text: str = ""
    ollama_base_url_vision: str = ""
    ollama_timeout_seconds: float = 600.0

    # Pfade
    data_dir: Path = Path("./data")
    database_url: str = ""

    # Pipeline
    text_concurrency: int = 2
    vision_concurrency: int = 2
    max_images_per_listing: int = 8
    scrape_delay_seconds: float = 2.5
    thumbnail_max_px: int = 480

    # Scheduler
    scheduler_timezone: str = "Europe/Berlin"

    # API
    cors_origins: str = "http://localhost:5173"

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, v: str | Path) -> Path:
        return Path(str(v)).expanduser()

    @property
    def image_dir(self) -> Path:
        """Vollbilder waehrend der Analyse (werden in Stufe 5 geloescht)."""
        return self.data_dir / "images"

    @property
    def thumb_dir(self) -> Path:
        """Dauerhaft aufbewahrte Vorschaubilder (eines je Inserat)."""
        return self.data_dir / "thumbs"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'motorradsucher.db').as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ollama_url_for(self, stage: str) -> str:
        """Ollama-Endpunkt je Stage - erlaubt eine Instanz pro GPU."""
        if stage in ("text", "interpretation", "ranking") and self.ollama_base_url_text:
            return self.ollama_base_url_text
        if stage == "vision" and self.ollama_base_url_vision:
            return self.ollama_base_url_vision
        return self.ollama_base_url


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.image_dir.mkdir(parents=True, exist_ok=True)
    s.thumb_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
