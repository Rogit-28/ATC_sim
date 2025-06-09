"""Aircraft data model and enumerations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np


class AircraftStatus(Enum):
    """Current operational status of an aircraft."""

    SPAWNED = auto()
    CRUISING = auto()
    DESCENDING = auto()
    HOLDING = auto()
    APPROACH = auto()
    LANDING = auto()
    LANDED = auto()
    DEPARTING = auto()
    DIVERTED = auto()
    EMERGENCY = auto()
    REMOVED = auto()


class AircraftIntent(Enum):
    """Aircraft mission intent."""

    LAND = auto()
    OVERFLY = auto()
    DIVERT = auto()


class AircraftType(Enum):
    """Common aircraft types with performance profiles."""

    B737 = "B737"
    B747 = "B747"
    B777 = "B777"
    B787 = "B787"
    A320 = "A320"
    A330 = "A330"
    A350 = "A350"
    A380 = "A380"
    CRJ9 = "CRJ9"
    E190 = "E190"

    @property
    def max_speed_knots(self) -> float:
        """Maximum operating speed (Vmo) in knots."""
        speeds = {
            "B737": 340,
            "B747": 365,
            "B777": 350,
            "B787": 350,
            "A320": 350,
            "A330": 350,
            "A350": 350,
            "A380": 340,
            "CRJ9": 315,
            "E190": 320,
        }
        return speeds.get(self.value, 340)

    @property
    def min_speed_knots(self) -> float:
        """Minimum clean speed in knots."""
        speeds = {
            "B737": 210,
            "B747": 230,
            "B777": 225,
            "B787": 220,
            "A320": 210,
            "A330": 220,
            "A350": 215,
            "A380": 225,
            "CRJ9": 185,
            "E190": 195,
        }
        return speeds.get(self.value, 210)

    @property
    def approach_speed_knots(self) -> float:
        """Typical approach speed (Vref) in knots."""
        speeds = {
            "B737": 140,
            "B747": 155,
            "B777": 145,
            "B787": 140,
            "A320": 137,
            "A330": 140,
            "A350": 138,
            "A380": 150,
            "CRJ9": 132,
            "E190": 130,
        }
        return speeds.get(self.value, 140)

    @property
    def max_climb_rate_fpm(self) -> float:
        """Maximum climb rate in feet per minute."""
        rates = {
            "B737": 3000,
            "B747": 2500,
            "B777": 2800,
            "B787": 3200,
            "A320": 3000,
            "A330": 2600,
            "A350": 3100,
            "A380": 2400,
            "CRJ9": 3500,
            "E190": 3400,
        }
        return rates.get(self.value, 3000)

    @property
    def max_descent_rate_fpm(self) -> float:
        """Maximum descent rate in feet per minute."""
        rates = {
            "B737": 4000,
            "B747": 3500,
            "B777": 3800,
            "B787": 4000,
            "A320": 4000,
            "A330": 3600,
            "A350": 3800,
            "A380": 3200,
            "CRJ9": 4500,
            "E190": 4200,
        }
        return rates.get(self.value, 4000)

    @property
    def standard_turn_rate_deg_s(self) -> float:
        """Standard rate turn (degrees per second)."""
        return 3.0  # Standard rate for all types

    @property
    def max_bank_angle_deg(self) -> float:
        """Maximum bank angle in degrees."""
        return 30.0  # FAA standard for commercial

    @property
    def fuel_burn_rate_kg_s(self) -> float:
        """Base fuel burn rate in kg/second (cruise)."""
        rates = {
            "B737": 0.85,
            "B747": 3.20,
            "B777": 2.50,
            "B787": 1.80,
            "A320": 0.80,
            "A330": 1.90,
            "A350": 1.70,
            "A380": 3.50,
            "CRJ9": 0.45,
            "E190": 0.50,
        }
        return rates.get(self.value, 0.85)

    @property
    def typical_souls(self) -> int:
        """Typical passenger + crew count."""
        counts = {
            "B737": 175,
            "B747": 410,
            "B777": 350,
            "B787": 290,
            "A320": 180,
            "A330": 290,
            "A350": 325,
            "A380": 500,
            "CRJ9": 90,
            "E190": 100,
        }
        return counts.get(self.value, 175)


@dataclass
class Aircraft:
    """Aircraft state representation.

    All spatial coordinates use kilometers (km).
    Position array: [x, y, z] where z = altitude in km.
    Velocity array: [vx, vy, vz] in km/s.
    """

    # Identification
    id: str
    callsign: str
    aircraft_type: str  # String value from AircraftType enum

    # Spatial state (NumPy float64)
    position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))

    # Flight parameters
    heading: float = 0.0
    bank_angle: float = 0.0
    altitude_ft: float = 10000.0
    speed_knots: float = 350.0
    vertical_speed_fpm: float = 0.0

    # Target values (for autopilot)
    target_heading: float = 0.0
    target_altitude_ft: float = 10000.0
    target_speed_knots: float = 350.0

    # Fuel
    fuel_remaining_kg: float = 50000.0
    fuel_burn_rate_kg_s: float = 0.85
    min_fuel_kg: float = 5000.0  # Minimum fuel before diversion

    # Passengers
    souls_on_board: int = 150

    # Routing
    origin: str = ""
    destination: str = ""
    assigned_runway: Optional[str] = None

    # State
    status: AircraftStatus = AircraftStatus.SPAWNED
    intent: AircraftIntent = AircraftIntent.LAND
    sector_id: str = ""

    # Timing
    spawn_time: float = 0.0

    # Priority
    priority_score: float = 0.0

    # Holding
    holding_fix: Optional[str] = None
    holding_start_time: Optional[float] = None
    holding_leg_heading: float = 0.0
    holding_outbound: bool = True

    # Emergency
    is_emergency: bool = False
    emergency_type: str = ""

    # ILS approach state
    on_localizer: bool = False
    on_glideslope: bool = False
    go_around: bool = False

    def __post_init__(self) -> None:
        """Ensure NumPy arrays are float64."""
        if not isinstance(self.position, np.ndarray):
            self.position = np.array(self.position, dtype=np.float64)
        elif self.position.dtype != np.float64:
            self.position = self.position.astype(np.float64)

        if not isinstance(self.velocity, np.ndarray):
            self.velocity = np.array(self.velocity, dtype=np.float64)
        elif self.velocity.dtype != np.float64:
            self.velocity = self.velocity.astype(np.float64)

        # Set target to current values if not specified
        if self.target_heading == 0.0 and self.heading != 0.0:
            self.target_heading = self.heading
        if self.target_altitude_ft == 10000.0 and self.altitude_ft != 10000.0:
            self.target_altitude_ft = self.altitude_ft
        if self.target_speed_knots == 350.0 and self.speed_knots != 350.0:
            self.target_speed_knots = self.speed_knots

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "callsign": self.callsign,
            "aircraft_type": self.aircraft_type,
            "position": self.position.tolist(),
            "velocity": self.velocity.tolist(),
            "heading": round(self.heading, 2),
            "bank_angle": round(self.bank_angle, 2),
            "altitude_ft": round(self.altitude_ft, 1),
            "speed_knots": round(self.speed_knots, 1),
            "vertical_speed_fpm": round(self.vertical_speed_fpm, 1),
            "target_heading": round(self.target_heading, 2),
            "target_altitude_ft": round(self.target_altitude_ft, 1),
            "target_speed_knots": round(self.target_speed_knots, 1),
            "fuel_remaining_kg": round(self.fuel_remaining_kg, 1),
            "fuel_burn_rate_kg_s": round(self.fuel_burn_rate_kg_s, 4),
            "min_fuel_kg": round(self.min_fuel_kg, 1),
            "souls_on_board": self.souls_on_board,
            "origin": self.origin,
            "destination": self.destination,
            "assigned_runway": self.assigned_runway,
            "status": self.status.name,
            "intent": self.intent.name,
            "sector_id": self.sector_id,
            "spawn_time": round(self.spawn_time, 3),
            "priority_score": round(self.priority_score, 4),
            "holding_fix": self.holding_fix,
            "holding_start_time": (round(self.holding_start_time, 3) if self.holding_start_time is not None else None),
            "is_emergency": self.is_emergency,
            "emergency_type": self.emergency_type,
            "on_localizer": self.on_localizer,
            "on_glideslope": self.on_glideslope,
        }

    def to_msgpack(self) -> dict:
        """Minimal state for WebSocket binary frames (msgpack).

        Only includes fields needed for real-time visualization.
        """
        return {
            "id": self.id,
            "cs": self.callsign,
            "p": self.position.tolist(),
            "h": round(self.heading, 1),
            "a": round(self.altitude_ft, 0),
            "s": round(self.speed_knots, 0),
            "st": self.status.name,
            "em": self.is_emergency,
        }
