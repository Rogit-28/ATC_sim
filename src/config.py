"""Application configuration using pydantic-settings v2."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file.

    Environment variables override .env file values.
    All variable names are case-insensitive.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql://postgres:changeme@localhost:5434/atc_simulator",
        description="PostgreSQL connection URL",
    )
    database_pool_min_size: int = Field(default=5, ge=1)
    database_pool_max_size: int = Field(default=20, ge=1)
    database_pool_timeout: float = Field(default=60.0, description="Query timeout in seconds")

    # ── Simulation ────────────────────────────────────────────
    simulation_tick_rate: int = Field(default=20, ge=1, le=100, description="Ticks per second (Hz)")
    max_aircraft: int = Field(default=5000, ge=1)
    spawn_rate_per_minute: float = Field(default=2.0, ge=0.0, description="Average aircraft spawns per minute")
    octree_max_depth: int = Field(default=8, ge=2, le=16)
    octree_rebuild_interval: int = Field(default=10, ge=1, description="Rebuild octree every N ticks")
    snapshot_interval: int = Field(default=1200, ge=1, description="Snapshot every N ticks (60s @ 20Hz)")

    # ── Landing Priority Weights ──────────────────────────────
    priority_weight_fuel: float = Field(default=0.35, ge=0.0, le=1.0)
    priority_weight_emergency: float = Field(default=0.30, ge=0.0, le=1.0)
    priority_weight_souls: float = Field(default=0.15, ge=0.0, le=1.0)
    priority_weight_wait_time: float = Field(default=0.10, ge=0.0, le=1.0)
    priority_weight_runway: float = Field(default=0.05, ge=0.0, le=1.0)
    priority_weight_distance: float = Field(default=0.05, ge=0.0, le=1.0)

    # ── Separation Standards ──────────────────────────────────
    separation_horizontal_nm: float = Field(default=5.0, description="Min horizontal separation (nautical miles)")
    separation_vertical_ft: float = Field(default=1000.0, description="Min vertical separation (feet)")

    # ── API ───────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8000",
        ]
    )

    # ── Security ──────────────────────────────────────────────
    jwt_secret: str = Field(default="", description="JWT secret (empty = auth disabled)")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_hours: int = Field(default=24, ge=1)

    # ── Logging ───────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    debug_mode: bool = Field(default=False)

    # ── Environment ───────────────────────────────────────────
    environment: str = Field(default="development")

    # ── Derived Properties ────────────────────────────────────

    @property
    def tick_interval_sec(self) -> float:
        """Seconds between simulation ticks."""
        return 1.0 / self.simulation_tick_rate

    @property
    def auth_enabled(self) -> bool:
        """Whether JWT authentication is enabled."""
        return bool(self.jwt_secret)

    @property
    def priority_weights(self) -> dict[str, float]:
        """All priority weights as a dictionary."""
        return {
            "fuel": self.priority_weight_fuel,
            "emergency": self.priority_weight_emergency,
            "souls": self.priority_weight_souls,
            "wait_time": self.priority_weight_wait_time,
            "runway": self.priority_weight_runway,
            "distance": self.priority_weight_distance,
        }

    # ── Validators ────────────────────────────────────────────

    @model_validator(mode="after")
    def validate_pool_sizes(self) -> "Settings":
        """Ensure pool max >= pool min."""
        if self.database_pool_max_size < self.database_pool_min_size:
            raise ValueError(
                f"database_pool_max_size ({self.database_pool_max_size}) "
                f"must be >= database_pool_min_size ({self.database_pool_min_size})"
            )
        return self

    @model_validator(mode="after")
    def validate_weight_sum(self) -> "Settings":
        """Priority weights should sum to approximately 1.0."""
        total = sum(self.priority_weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(
                "Priority weights sum to %.3f (expected ~1.0). Results may not be normalized.",
                total,
            )
        return self


# ── Singleton Access ──────────────────────────────────────────

_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings singleton (useful for testing)."""
    global _settings
    _settings = None
