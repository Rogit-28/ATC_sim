"""Initial schema — 6 tables for ATC simulator.

Revision ID: 001
Revises: None
Create Date: 2026-03-13

Tables:
  - sectors
  - runways
  - aircraft_states
  - event_log (partitioned by range on created_at, 8 daily partitions)
  - simulation_snapshots
  - analytics_metrics
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all initial tables."""

    # ── sectors ───────────────────────────────────────────────
    op.create_table(
        "sectors",
        sa.Column("id", sa.VARCHAR(50), primary_key=True),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("bounds_min_x", sa.Float(precision=53), nullable=False),
        sa.Column("bounds_min_y", sa.Float(precision=53), nullable=False),
        sa.Column("bounds_min_z", sa.Float(precision=53), nullable=False),
        sa.Column("bounds_max_x", sa.Float(precision=53), nullable=False),
        sa.Column("bounds_max_y", sa.Float(precision=53), nullable=False),
        sa.Column("bounds_max_z", sa.Float(precision=53), nullable=False),
        sa.Column("capacity", sa.Integer(), server_default="50"),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_sectors_active", "sectors", ["active"])

    # ── runways ───────────────────────────────────────────────
    op.create_table(
        "runways",
        sa.Column("id", sa.VARCHAR(50), primary_key=True),
        sa.Column("airport_icao", sa.VARCHAR(10), nullable=False),
        sa.Column("heading", sa.Float(precision=24), nullable=False),
        sa.Column("length_m", sa.Float(precision=24), nullable=False),
        sa.Column("position_x", sa.Float(precision=53), nullable=False),
        sa.Column("position_y", sa.Float(precision=53), nullable=False),
        sa.Column("position_z", sa.Float(precision=53), nullable=False),
        sa.Column("ils_available", sa.Boolean(), server_default="true"),
        sa.Column("approach_heading", sa.Float(precision=24), nullable=False),
        sa.Column(
            "glideslope_angle",
            sa.Float(precision=24),
            server_default="3.0",
        ),
        sa.Column("occupied", sa.Boolean(), server_default="false"),
        sa.Column("occupant_id", sa.VARCHAR(50), nullable=True),
        sa.Column("elevation_ft", sa.Float(precision=24), server_default="0.0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_runways_airport_icao", "runways", ["airport_icao"])

    # ── aircraft_states ───────────────────────────────────────
    op.create_table(
        "aircraft_states",
        sa.Column("aircraft_id", sa.VARCHAR(50), primary_key=True),
        sa.Column("callsign", sa.VARCHAR(20), nullable=False),
        sa.Column("aircraft_type", sa.VARCHAR(20), nullable=False),
        sa.Column("position_x", sa.Float(precision=53), nullable=False),
        sa.Column("position_y", sa.Float(precision=53), nullable=False),
        sa.Column("position_z", sa.Float(precision=53), nullable=False),
        sa.Column("velocity_x", sa.Float(precision=24), nullable=False),
        sa.Column("velocity_y", sa.Float(precision=24), nullable=False),
        sa.Column("velocity_z", sa.Float(precision=24), nullable=False),
        sa.Column("heading", sa.Float(precision=24)),
        sa.Column("bank_angle", sa.Float(precision=24)),
        sa.Column("altitude_ft", sa.Float(precision=24)),
        sa.Column("speed_knots", sa.Float(precision=24)),
        sa.Column("vertical_speed_fpm", sa.Float(precision=24)),
        sa.Column("fuel_remaining_kg", sa.Float(precision=24)),
        sa.Column("fuel_burn_rate_kg_s", sa.Float(precision=24)),
        sa.Column("souls_on_board", sa.Integer()),
        sa.Column("origin", sa.VARCHAR(10)),
        sa.Column("destination", sa.VARCHAR(10)),
        sa.Column("assigned_runway", sa.VARCHAR(50)),
        sa.Column("status", sa.VARCHAR(50)),
        sa.Column("intent", sa.VARCHAR(50)),
        sa.Column("sector_id", sa.VARCHAR(50)),
        sa.Column("spawn_time", sa.Float()),
        sa.Column("priority_score", sa.Float()),
        sa.Column("holding_fix", sa.VARCHAR(50), nullable=True),
        sa.Column("holding_start_time", sa.Float(), nullable=True),
        sa.Column("is_emergency", sa.Boolean(), server_default="false"),
        sa.Column("emergency_type", sa.VARCHAR(50), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_aircraft_states_status", "aircraft_states", ["status"])
    op.create_index("ix_aircraft_states_sector_id", "aircraft_states", ["sector_id"])
    op.create_index("ix_aircraft_states_updated_at", "aircraft_states", ["updated_at"])

    # ── event_log (partitioned by RANGE on created_at) ────────
    # Alembic doesn't natively support PARTITION BY, so use raw SQL.
    op.execute(
        """
        CREATE TABLE event_log (
            id          BIGSERIAL,
            event_type  VARCHAR(100)  NOT NULL,
            aircraft_id VARCHAR(50),
            data        JSONB,
            created_at  TIMESTAMP     NOT NULL DEFAULT NOW(),
            PRIMARY KEY (created_at, id)
        ) PARTITION BY RANGE (created_at);
        """
    )
    op.create_index("ix_event_log_aircraft_id", "event_log", ["aircraft_id"])
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])
    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])

    # Create 8 daily partitions (today + 7 days)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(8):
        day_start = today + timedelta(days=i)
        day_end = today + timedelta(days=i + 1)
        partition_name = f"event_log_{day_start.strftime('%Y%m%d')}"
        op.execute(
            f"CREATE TABLE {partition_name} PARTITION OF event_log "
            f"FOR VALUES FROM ('{day_start.isoformat()}') "
            f"TO ('{day_end.isoformat()}');"
        )

    # ── simulation_snapshots ──────────────────────────────────
    op.create_table(
        "simulation_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("simulation_time_sec", sa.Float(), nullable=False),
        sa.Column("tick_number", sa.BigInteger(), nullable=False),
        sa.Column("aircraft_count", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.VARCHAR(64), nullable=False),
        sa.Column("full_state", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_simulation_snapshots_created_at",
        "simulation_snapshots",
        ["created_at"],
    )
    op.create_index(
        "ix_simulation_snapshots_state_hash",
        "simulation_snapshots",
        ["state_hash"],
    )

    # ── analytics_metrics ─────────────────────────────────────
    op.create_table(
        "analytics_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("time_bucket", sa.TIMESTAMP(), nullable=False),
        sa.Column("aircraft_count", sa.Integer(), server_default="0"),
        sa.Column("landed_count", sa.Integer(), server_default="0"),
        sa.Column("diverted_count", sa.Integer(), server_default="0"),
        sa.Column("conflicts_detected", sa.Integer(), server_default="0"),
        sa.Column("avg_holding_time_sec", sa.Float(), server_default="0.0"),
        sa.Column("avg_fuel_remaining_kg", sa.Float(), server_default="0.0"),
        sa.Column("landing_throughput_per_hour", sa.Float(), server_default="0.0"),
    )
    op.create_index(
        "ix_analytics_metrics_time_bucket",
        "analytics_metrics",
        ["time_bucket"],
    )


def downgrade() -> None:
    """Drop all tables in reverse order."""
    op.drop_table("analytics_metrics")
    op.drop_table("simulation_snapshots")

    # Drop partitions first, then parent
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(8):
        day_start = today + timedelta(days=i)
        partition_name = f"event_log_{day_start.strftime('%Y%m%d')}"
        op.execute(f"DROP TABLE IF EXISTS {partition_name};")
    op.drop_table("event_log")

    op.drop_table("aircraft_states")
    op.drop_table("runways")
    op.drop_table("sectors")
