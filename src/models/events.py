"""Simulation event types for logging and pub/sub."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


class EventType(Enum):
    """Event categories."""

    AIRCRAFT_SPAWNED = "aircraft.spawned"
    AIRCRAFT_LANDED = "aircraft.landed"
    AIRCRAFT_DIVERTED = "aircraft.diverted"
    AIRCRAFT_REMOVED = "aircraft.removed"
    CONFLICT_DETECTED = "conflict.detected"
    CONFLICT_RESOLVED = "conflict.resolved"
    SECTOR_HANDOFF = "sector.handoff"
    HOLDING_ENTERED = "holding.entered"
    HOLDING_EXITED = "holding.exited"
    APPROACH_STARTED = "approach.started"
    GO_AROUND = "approach.go_around"
    SIMULATION_STARTED = "simulation.started"
    SIMULATION_STOPPED = "simulation.stopped"
    SIMULATION_SNAPSHOT = "simulation.snapshot"


@dataclass
class Event:
    """Base simulation event."""

    event_type: EventType = EventType.AIRCRAFT_SPAWNED  # Default, overridden by subclasses
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    simulation_time: float = 0.0  # Simulation clock in seconds
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "simulation_time": round(self.simulation_time, 3),
            "data": self.data,
        }


@dataclass
class AircraftSpawnedEvent(Event):
    """Aircraft entered the simulation."""

    aircraft_id: str = ""
    callsign: str = ""
    aircraft_type: str = ""
    origin: str = ""
    destination: str = ""
    intent: str = ""

    def __post_init__(self) -> None:
        self.event_type = EventType.AIRCRAFT_SPAWNED
        self.data = {
            "aircraft_id": self.aircraft_id,
            "callsign": self.callsign,
            "aircraft_type": self.aircraft_type,
            "origin": self.origin,
            "destination": self.destination,
            "intent": self.intent,
        }


@dataclass
class AircraftLandedEvent(Event):
    """Aircraft successfully landed."""

    aircraft_id: str = ""
    callsign: str = ""
    runway_id: str = ""
    holding_time_sec: float = 0.0
    fuel_remaining_kg: float = 0.0
    priority_score: float = 0.0

    def __post_init__(self) -> None:
        self.event_type = EventType.AIRCRAFT_LANDED
        self.data = {
            "aircraft_id": self.aircraft_id,
            "callsign": self.callsign,
            "runway_id": self.runway_id,
            "holding_time_sec": round(self.holding_time_sec, 1),
            "fuel_remaining_kg": round(self.fuel_remaining_kg, 1),
            "priority_score": round(self.priority_score, 4),
        }


@dataclass
class AircraftDivertedEvent(Event):
    """Aircraft diverted from original destination."""

    aircraft_id: str = ""
    callsign: str = ""
    original_destination: str = ""
    divert_destination: str = ""
    reason: str = ""  # FUEL, WEATHER, EMERGENCY
    fuel_remaining_kg: float = 0.0

    def __post_init__(self) -> None:
        self.event_type = EventType.AIRCRAFT_DIVERTED
        self.data = {
            "aircraft_id": self.aircraft_id,
            "callsign": self.callsign,
            "original_destination": self.original_destination,
            "divert_destination": self.divert_destination,
            "reason": self.reason,
            "fuel_remaining_kg": round(self.fuel_remaining_kg, 1),
        }


@dataclass
class ConflictDetectedEvent(Event):
    """Separation violation detected between aircraft."""

    aircraft_id_1: str = ""
    aircraft_id_2: str = ""
    callsign_1: str = ""
    callsign_2: str = ""
    horizontal_distance_nm: float = 0.0
    vertical_distance_ft: float = 0.0
    resolution_action: str = ""  # VECTOR, CLIMB, DESCEND, SPEED

    def __post_init__(self) -> None:
        self.event_type = EventType.CONFLICT_DETECTED
        self.data = {
            "aircraft_id_1": self.aircraft_id_1,
            "aircraft_id_2": self.aircraft_id_2,
            "callsign_1": self.callsign_1,
            "callsign_2": self.callsign_2,
            "horizontal_distance_nm": round(self.horizontal_distance_nm, 2),
            "vertical_distance_ft": round(self.vertical_distance_ft, 0),
            "resolution_action": self.resolution_action,
        }


@dataclass
class SectorHandoffEvent(Event):
    """Aircraft transferred between sectors."""

    aircraft_id: str = ""
    callsign: str = ""
    from_sector: str = ""
    to_sector: str = ""

    def __post_init__(self) -> None:
        self.event_type = EventType.SECTOR_HANDOFF
        self.data = {
            "aircraft_id": self.aircraft_id,
            "callsign": self.callsign,
            "from_sector": self.from_sector,
            "to_sector": self.to_sector,
        }
