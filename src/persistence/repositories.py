"""Repository classes for all ATC simulator tables.

Each repository wraps raw asyncpg SQL against a single logical table,
converting between domain dataclass instances and database rows.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from src.models import Aircraft, AircraftStatus, AircraftIntent, Sector, Runway
from src.models.events import Event, EventType
from src.persistence.database import Database

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── AircraftStateRepository ──────────────────────────────────


class AircraftStateRepository:
    """CRUD for the ``aircraft_states`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, ac: Aircraft) -> None:
        """Insert or update an aircraft state row."""
        await self._db.execute(
            """
            INSERT INTO aircraft_states (
                aircraft_id, callsign, aircraft_type,
                position_x, position_y, position_z,
                velocity_x, velocity_y, velocity_z,
                heading, bank_angle,
                altitude_ft, speed_knots, vertical_speed_fpm,
                fuel_remaining_kg, fuel_burn_rate_kg_s,
                souls_on_board,
                origin, destination, assigned_runway,
                status, intent, sector_id,
                spawn_time, priority_score,
                holding_fix, holding_start_time,
                is_emergency, emergency_type,
                updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                $21,$22,$23,$24,$25,$26,$27,$28,$29,$30
            )
            ON CONFLICT (aircraft_id) DO UPDATE SET
                callsign           = EXCLUDED.callsign,
                aircraft_type      = EXCLUDED.aircraft_type,
                position_x         = EXCLUDED.position_x,
                position_y         = EXCLUDED.position_y,
                position_z         = EXCLUDED.position_z,
                velocity_x         = EXCLUDED.velocity_x,
                velocity_y         = EXCLUDED.velocity_y,
                velocity_z         = EXCLUDED.velocity_z,
                heading            = EXCLUDED.heading,
                bank_angle         = EXCLUDED.bank_angle,
                altitude_ft        = EXCLUDED.altitude_ft,
                speed_knots        = EXCLUDED.speed_knots,
                vertical_speed_fpm = EXCLUDED.vertical_speed_fpm,
                fuel_remaining_kg  = EXCLUDED.fuel_remaining_kg,
                fuel_burn_rate_kg_s= EXCLUDED.fuel_burn_rate_kg_s,
                souls_on_board     = EXCLUDED.souls_on_board,
                origin             = EXCLUDED.origin,
                destination        = EXCLUDED.destination,
                assigned_runway    = EXCLUDED.assigned_runway,
                status             = EXCLUDED.status,
                intent             = EXCLUDED.intent,
                sector_id          = EXCLUDED.sector_id,
                spawn_time         = EXCLUDED.spawn_time,
                priority_score     = EXCLUDED.priority_score,
                holding_fix        = EXCLUDED.holding_fix,
                holding_start_time = EXCLUDED.holding_start_time,
                is_emergency       = EXCLUDED.is_emergency,
                emergency_type     = EXCLUDED.emergency_type,
                updated_at         = EXCLUDED.updated_at
            """,
            ac.id,
            ac.callsign,
            ac.aircraft_type,
            float(ac.position[0]),
            float(ac.position[1]),
            float(ac.position[2]),
            float(ac.velocity[0]),
            float(ac.velocity[1]),
            float(ac.velocity[2]),
            ac.heading,
            ac.bank_angle,
            ac.altitude_ft,
            ac.speed_knots,
            ac.vertical_speed_fpm,
            ac.fuel_remaining_kg,
            ac.fuel_burn_rate_kg_s,
            ac.souls_on_board,
            ac.origin,
            ac.destination,
            ac.assigned_runway,
            ac.status.name if isinstance(ac.status, AircraftStatus) else str(ac.status),
            ac.intent.name if isinstance(ac.intent, AircraftIntent) else str(ac.intent),
            ac.sector_id,
            ac.spawn_time,
            ac.priority_score,
            ac.holding_fix,
            ac.holding_start_time,
            ac.is_emergency,
            ac.emergency_type,
            _now_utc(),
        )

    async def get_all(self) -> list[Aircraft]:
        """Return every aircraft state."""
        rows = await self._db.fetch("SELECT * FROM aircraft_states ORDER BY aircraft_id")
        return [self._row_to_aircraft(r) for r in rows]

    async def get_by_id(self, aircraft_id: str) -> Optional[Aircraft]:
        """Return a single aircraft or None."""
        row = await self._db.fetchrow("SELECT * FROM aircraft_states WHERE aircraft_id = $1", aircraft_id)
        return self._row_to_aircraft(row) if row else None

    async def delete(self, aircraft_id: str) -> None:
        """Delete an aircraft state row."""
        await self._db.execute("DELETE FROM aircraft_states WHERE aircraft_id = $1", aircraft_id)

    # ── private ───────────────────────────────────────────────

    @staticmethod
    def _row_to_aircraft(row: Any) -> Aircraft:
        """Convert an asyncpg Record to an Aircraft dataclass."""
        status_str = row["status"] or "SPAWNED"
        intent_str = row["intent"] or "LAND"

        return Aircraft(
            id=row["aircraft_id"],
            callsign=row["callsign"],
            aircraft_type=row["aircraft_type"],
            position=np.array(
                [row["position_x"], row["position_y"], row["position_z"]],
                dtype=np.float64,
            ),
            velocity=np.array(
                [row["velocity_x"], row["velocity_y"], row["velocity_z"]],
                dtype=np.float64,
            ),
            heading=row["heading"] or 0.0,
            bank_angle=row["bank_angle"] or 0.0,
            altitude_ft=row["altitude_ft"] or 0.0,
            speed_knots=row["speed_knots"] or 0.0,
            vertical_speed_fpm=row["vertical_speed_fpm"] or 0.0,
            fuel_remaining_kg=row["fuel_remaining_kg"] or 0.0,
            fuel_burn_rate_kg_s=row["fuel_burn_rate_kg_s"] or 0.0,
            souls_on_board=row["souls_on_board"] or 0,
            origin=row["origin"] or "",
            destination=row["destination"] or "",
            assigned_runway=row["assigned_runway"],
            status=AircraftStatus[status_str],
            intent=AircraftIntent[intent_str],
            sector_id=row["sector_id"] or "",
            spawn_time=row["spawn_time"] or 0.0,
            priority_score=row["priority_score"] or 0.0,
            holding_fix=row["holding_fix"],
            holding_start_time=row["holding_start_time"],
            is_emergency=row["is_emergency"] or False,
            emergency_type=row["emergency_type"] or "",
        )


# ── EventRepository ──────────────────────────────────────────


class EventRepository:
    """Read/write for the partitioned ``event_log`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, event: Event) -> None:
        """Insert a single event."""
        await self._db.execute(
            """
            INSERT INTO event_log (event_type, aircraft_id, data, created_at)
            VALUES ($1, $2, $3, $4)
            """,
            event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type),
            event.data.get("aircraft_id") or event.data.get("aircraft_id_1"),
            json.dumps(event.data),
            event.timestamp,
        )

    async def insert_batch(self, events: list[Event]) -> None:
        """Bulk-insert events using COPY protocol."""
        if not events:
            return
        records = []
        for ev in events:
            records.append(
                (
                    ev.event_type.value if isinstance(ev.event_type, EventType) else str(ev.event_type),
                    ev.data.get("aircraft_id") or ev.data.get("aircraft_id_1"),
                    json.dumps(ev.data),
                    ev.timestamp,
                )
            )
        await self._db.copy_records_to_table(
            "event_log",
            records=records,
            columns=["event_type", "aircraft_id", "data", "created_at"],
        )

    async def get_by_aircraft(self, aircraft_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch events for a specific aircraft, newest first."""
        rows = await self._db.fetch(
            """
            SELECT id, event_type, aircraft_id, data, created_at
            FROM event_log
            WHERE aircraft_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            aircraft_id,
            limit,
        )
        return [
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "aircraft_id": r["aircraft_id"],
                "data": json.loads(r["data"]) if isinstance(r["data"], str) else r["data"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


# ── SnapshotRepository ───────────────────────────────────────


class SnapshotRepository:
    """Read/write for the ``simulation_snapshots`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        simulation_time_sec: float,
        tick_number: int,
        aircraft_count: int,
        state_hash: str,
        full_state: dict[str, Any],
    ) -> int:
        """Insert a snapshot and return its id."""
        row_id: int = await self._db.fetchval(
            """
            INSERT INTO simulation_snapshots
                (simulation_time_sec, tick_number, aircraft_count, state_hash, full_state)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            simulation_time_sec,
            tick_number,
            aircraft_count,
            state_hash,
            json.dumps(full_state),
        )
        return row_id

    async def get_latest(self) -> Optional[dict[str, Any]]:
        """Return the most recent snapshot or None."""
        row = await self._db.fetchrow(
            """
            SELECT id, created_at, simulation_time_sec, tick_number,
                   aircraft_count, state_hash, full_state
            FROM simulation_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        )
        return self._row_to_dict(row) if row else None

    async def get_by_time(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Return snapshots within a time range."""
        rows = await self._db.fetch(
            """
            SELECT id, created_at, simulation_time_sec, tick_number,
                   aircraft_count, state_hash, full_state
            FROM simulation_snapshots
            WHERE created_at >= $1 AND created_at <= $2
            ORDER BY created_at
            """,
            start,
            end,
        )
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        full_state = row["full_state"]
        if isinstance(full_state, str):
            full_state = json.loads(full_state)
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "simulation_time_sec": row["simulation_time_sec"],
            "tick_number": row["tick_number"],
            "aircraft_count": row["aircraft_count"],
            "state_hash": row["state_hash"],
            "full_state": full_state,
        }


# ── SectorRepository ─────────────────────────────────────────


class SectorRepository:
    """Read for the ``sectors`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_all(self) -> list[Sector]:
        """Return all active sectors."""
        rows = await self._db.fetch("SELECT * FROM sectors WHERE active = true ORDER BY id")
        return [self._row_to_sector(r) for r in rows]

    @staticmethod
    def _row_to_sector(row: Any) -> Sector:
        return Sector(
            id=row["id"],
            name=row["name"],
            bounds_min=np.array(
                [row["bounds_min_x"], row["bounds_min_y"], row["bounds_min_z"]],
                dtype=np.float64,
            ),
            bounds_max=np.array(
                [row["bounds_max_x"], row["bounds_max_y"], row["bounds_max_z"]],
                dtype=np.float64,
            ),
            capacity=row["capacity"],
            active=row["active"],
        )


# ── RunwayRepository ─────────────────────────────────────────


class RunwayRepository:
    """Read for the ``runways`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_all(self) -> list[Runway]:
        """Return all runways."""
        rows = await self._db.fetch("SELECT * FROM runways ORDER BY id")
        return [self._row_to_runway(r) for r in rows]

    @staticmethod
    def _row_to_runway(row: Any) -> Runway:
        return Runway(
            id=row["id"],
            airport_icao=row["airport_icao"],
            heading=row["heading"],
            length_m=row["length_m"],
            position=np.array(
                [row["position_x"], row["position_y"], row["position_z"]],
                dtype=np.float64,
            ),
            ils_available=row["ils_available"],
            approach_heading=row["approach_heading"],
            glideslope_angle=row["glideslope_angle"],
            occupied=row["occupied"],
            occupant_id=row["occupant_id"],
            elevation_ft=row["elevation_ft"],
        )


# ── AnalyticsRepository ──────────────────────────────────────


class AnalyticsRepository:
    """Read/write for the ``analytics_metrics`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        time_bucket: datetime,
        aircraft_count: int = 0,
        landed_count: int = 0,
        diverted_count: int = 0,
        conflicts_detected: int = 0,
        avg_holding_time_sec: float = 0.0,
        avg_fuel_remaining_kg: float = 0.0,
        landing_throughput_per_hour: float = 0.0,
    ) -> int:
        """Insert a metrics row and return its id."""
        row_id: int = await self._db.fetchval(
            """
            INSERT INTO analytics_metrics (
                time_bucket, aircraft_count, landed_count,
                diverted_count, conflicts_detected,
                avg_holding_time_sec, avg_fuel_remaining_kg,
                landing_throughput_per_hour
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            time_bucket,
            aircraft_count,
            landed_count,
            diverted_count,
            conflicts_detected,
            avg_holding_time_sec,
            avg_fuel_remaining_kg,
            landing_throughput_per_hour,
        )
        return row_id

    async def get_by_time_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch metrics within a time range, ordered by bucket."""
        rows = await self._db.fetch(
            """
            SELECT id, timestamp, time_bucket,
                   aircraft_count, landed_count, diverted_count,
                   conflicts_detected,
                   avg_holding_time_sec, avg_fuel_remaining_kg,
                   landing_throughput_per_hour
            FROM analytics_metrics
            WHERE time_bucket >= $1 AND time_bucket <= $2
            ORDER BY time_bucket
            """,
            start,
            end,
        )
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "time_bucket": r["time_bucket"],
                "aircraft_count": r["aircraft_count"],
                "landed_count": r["landed_count"],
                "diverted_count": r["diverted_count"],
                "conflicts_detected": r["conflicts_detected"],
                "avg_holding_time_sec": r["avg_holding_time_sec"],
                "avg_fuel_remaining_kg": r["avg_fuel_remaining_kg"],
                "landing_throughput_per_hour": r["landing_throughput_per_hour"],
            }
            for r in rows
        ]
