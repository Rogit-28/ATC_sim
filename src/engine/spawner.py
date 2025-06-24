"""Aircraft spawner for ATC simulation.

Generates new aircraft at sector boundaries using Poisson inter-arrival
times and deterministic RNG for reproducible scenarios.
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.engine.physics import KT_TO_KM_S, FT_TO_KM, DEG_TO_RAD
from src.models.aircraft import Aircraft, AircraftIntent, AircraftStatus, AircraftType
from src.models.sector import Sector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AIRLINE_CODES: list[str] = [
    "AAL",
    "BAW",
    "DAL",
    "DLH",
    "EIN",
    "FIN",
    "IBE",
    "JAL",
    "KAL",
    "KLM",
    "QFA",
    "SAS",
    "SIA",
    "SWA",
    "THY",
    "UAL",
    "VIR",
    "ACA",
    "AFR",
    "ANZ",
    "ANA",
    "CPA",
    "ETH",
    "EVA",
    "GIA",
    "HAL",
    "LAN",
    "TAP",
    "THA",
    "TAM",
]

ORIGINS: list[str] = [
    "KJFK",
    "KLAX",
    "EGLL",
    "LFPG",
    "EDDF",
    "RJTT",
    "VHHH",
    "WSSS",
    "OMDB",
    "YSSY",
    "CYYZ",
    "LEMD",
    "LIRF",
    "ZBAA",
    "VIDP",
    "RKSI",
    "VTBS",
    "WMKK",
    "NZAA",
    "SBGR",
]

DESTINATIONS: list[str] = [
    "KJFK",
    "KLAX",
    "EGLL",
    "LFPG",
    "EDDF",
    "RJTT",
    "VHHH",
    "WSSS",
    "OMDB",
    "YSSY",
    "CYYZ",
    "LEMD",
    "LIRF",
    "ZBAA",
]

EMERGENCY_TYPES: list[str] = [
    "ENGINE",
    "FUEL",
    "MEDICAL",
    "HYDRAULIC",
    "FIRE",
]

# Aircraft type distribution weights (higher = more common)
_TYPE_WEIGHTS: dict[str, float] = {
    "B737": 0.25,
    "A320": 0.25,
    "B777": 0.10,
    "B787": 0.10,
    "A330": 0.08,
    "A350": 0.07,
    "B747": 0.05,
    "A380": 0.03,
    "E190": 0.04,
    "CRJ9": 0.03,
}


@dataclass
class SpawnConfig:
    """Configuration for the aircraft spawner.

    Attributes
    ----------
    spawn_rate_per_minute : float
        Average number of aircraft to spawn per minute (Poisson lambda).
    max_aircraft : int
        Maximum aircraft allowed in the simulation simultaneously.
    emergency_probability : float
        Probability that a spawned aircraft declares an emergency.
    overfly_probability : float
        Probability that a spawned aircraft is an overflight (not landing).
    seed : int or None
        RNG seed for deterministic spawning.  ``None`` = random.
    """

    spawn_rate_per_minute: float = 2.0
    max_aircraft: int = 5000
    emergency_probability: float = 0.02
    overfly_probability: float = 0.15
    seed: Optional[int] = None


class AircraftSpawner:
    """Generates new aircraft at sector boundaries.

    All randomness uses instance-level RNG seeded deterministically
    so that replays produce identical traffic patterns.

    Parameters
    ----------
    config : SpawnConfig
        Spawn parameters.
    sector : Sector
        The airspace sector; aircraft spawn on its boundary edges.
    """

    def __init__(self, config: SpawnConfig, sector: Sector) -> None:
        self._config = config
        self._sector = sector

        # Deterministic RNG instances
        self._rng = random.Random(config.seed)
        self._np_rng = np.random.default_rng(config.seed)

        # Inter-arrival tracking
        self._time_since_last_spawn: float = 0.0
        self._next_spawn_interval: float = self._sample_interval()

        # Counters
        self._total_spawned: int = 0

        # Pre-compute type selection arrays
        self._type_names = list(_TYPE_WEIGHTS.keys())
        self._type_probs = np.array([_TYPE_WEIGHTS[t] for t in self._type_names], dtype=np.float64)
        self._type_probs /= self._type_probs.sum()  # normalise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_spawn(self, dt: float, current_count: int) -> bool:
        """Check if a new aircraft should spawn this tick.

        Uses exponential inter-arrival times (Poisson process).

        Parameters
        ----------
        dt : float
            Tick interval in seconds.
        current_count : int
            Number of aircraft currently in simulation.

        Returns
        -------
        bool
            True if an aircraft should be spawned.
        """
        if current_count >= self._config.max_aircraft:
            return False

        self._time_since_last_spawn += dt

        if self._time_since_last_spawn >= self._next_spawn_interval:
            self._time_since_last_spawn = 0.0
            self._next_spawn_interval = self._sample_interval()
            return True

        return False

    def spawn_aircraft(self, sim_time: float) -> Aircraft:
        """Create a new aircraft at a random sector boundary position.

        Parameters
        ----------
        sim_time : float
            Current simulation clock (seconds).

        Returns
        -------
        Aircraft
            Fully initialised aircraft ready for simulation.
        """
        ac_id = str(uuid.UUID(int=self._rng.getrandbits(128), version=4))
        ac_type_name = self._np_rng.choice(self._type_names, p=self._type_probs)
        ac_type = AircraftType(ac_type_name)

        callsign = self._generate_callsign()
        origin = self._rng.choice(ORIGINS)
        destination = self._rng.choice(DESTINATIONS)

        # Ensure origin != destination
        while destination == origin:
            destination = self._rng.choice(DESTINATIONS)

        # Intent
        is_overfly = self._rng.random() < self._config.overfly_probability
        intent = AircraftIntent.OVERFLY if is_overfly else AircraftIntent.LAND

        # Emergency
        is_emergency = self._rng.random() < self._config.emergency_probability
        emergency_type = self._rng.choice(EMERGENCY_TYPES) if is_emergency else ""

        # Position: random point on sector boundary
        position, heading = self._boundary_spawn_point()

        # Altitude: 10,000 - 35,000 ft (arrivals lower, overflights higher)
        if intent == AircraftIntent.OVERFLY:
            altitude_ft = float(self._rng.randint(25000, 40000))
        else:
            altitude_ft = float(self._rng.randint(10000, 25000))

        # Speed
        speed_knots = float(self._rng.uniform(ac_type.min_speed_knots, ac_type.max_speed_knots))

        # Fuel: 30-90% of max (smaller aircraft carry less)
        max_fuel_map = {
            "B737": 26000,
            "A320": 24000,
            "B777": 145000,
            "B787": 101000,
            "A330": 139000,
            "A350": 141000,
            "B747": 216000,
            "A380": 253000,
            "E190": 12900,
            "CRJ9": 8800,
        }
        max_fuel_kg = max_fuel_map.get(ac_type_name, 50000)
        fuel_pct = self._rng.uniform(0.3, 0.9)
        fuel_remaining_kg = max_fuel_kg * fuel_pct

        # Reduce fuel for emergency-fuel scenarios
        if is_emergency and emergency_type == "FUEL":
            fuel_remaining_kg = max_fuel_kg * self._rng.uniform(0.05, 0.15)

        # Souls
        souls = max(1, int(ac_type.typical_souls * self._rng.uniform(0.6, 1.0)))

        # Convert altitude to z-position in km
        position[2] = altitude_ft * FT_TO_KM

        # Compute velocity vector
        heading_rad = heading * DEG_TO_RAD
        speed_km_s = speed_knots * KT_TO_KM_S
        velocity = np.array(
            [
                speed_km_s * math.sin(heading_rad),
                speed_km_s * math.cos(heading_rad),
                0.0,
            ],
            dtype=np.float64,
        )

        aircraft = Aircraft(
            id=ac_id,
            callsign=callsign,
            aircraft_type=ac_type_name,
            position=position,
            velocity=velocity,
            heading=heading,
            altitude_ft=altitude_ft,
            speed_knots=speed_knots,
            target_heading=heading,
            target_altitude_ft=altitude_ft,
            target_speed_knots=speed_knots,
            fuel_remaining_kg=fuel_remaining_kg,
            fuel_burn_rate_kg_s=ac_type.fuel_burn_rate_kg_s,
            souls_on_board=souls,
            origin=origin,
            destination=destination,
            status=AircraftStatus.SPAWNED,
            intent=intent,
            spawn_time=sim_time,
            is_emergency=is_emergency,
            emergency_type=emergency_type,
        )

        self._total_spawned += 1
        logger.info(
            "Spawned %s (%s) %s -> %s  alt=%.0f ft  intent=%s%s",
            callsign,
            ac_type_name,
            origin,
            destination,
            altitude_ft,
            intent.name,
            " EMERGENCY:" + emergency_type if is_emergency else "",
        )

        return aircraft

    def spawn_batch(self, sim_time: float, count: int) -> list[Aircraft]:
        """Spawn multiple aircraft at once (useful for initialisation).

        Parameters
        ----------
        sim_time : float
            Current simulation clock.
        count : int
            Number of aircraft to spawn.

        Returns
        -------
        list[Aircraft]
        """
        return [self.spawn_aircraft(sim_time) for _ in range(count)]

    @property
    def total_spawned(self) -> int:
        return self._total_spawned

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sample_interval(self) -> float:
        """Sample next inter-arrival time from exponential distribution.

        rate_per_minute -> lambda = rate / 60 (per second)
        interval = Exponential(1 / lambda) = Exponential(60 / rate)
        """
        rate = self._config.spawn_rate_per_minute
        if rate <= 0:
            return float("inf")
        mean_interval = 60.0 / rate
        return float(self._np_rng.exponential(mean_interval))

    def _generate_callsign(self) -> str:
        """Generate a realistic airline callsign like 'AAL1234'."""
        airline = self._rng.choice(AIRLINE_CODES)
        flight_num = self._rng.randint(100, 9999)
        return f"{airline}{flight_num}"

    def _boundary_spawn_point(self) -> tuple[np.ndarray, float]:
        """Pick a random point on the sector boundary and an inward heading.

        Returns
        -------
        tuple[np.ndarray, float]
            ``(position, heading_deg)`` — position is on a face of the sector
            bounding box and heading points toward the sector center.
        """
        bmin = self._sector.bounds_min
        bmax = self._sector.bounds_max
        center = self._sector.center

        # Pick a random face: 0=xmin, 1=xmax, 2=ymin, 3=ymax
        face = self._rng.randint(0, 3)

        # Random y/x along the chosen face
        ry = self._rng.uniform(float(bmin[1]), float(bmax[1]))
        rx = self._rng.uniform(float(bmin[0]), float(bmax[0]))

        if face == 0:  # x = min
            pos = np.array([float(bmin[0]), ry, 0.0], dtype=np.float64)
        elif face == 1:  # x = max
            pos = np.array([float(bmax[0]), ry, 0.0], dtype=np.float64)
        elif face == 2:  # y = min
            pos = np.array([rx, float(bmin[1]), 0.0], dtype=np.float64)
        else:  # y = max
            pos = np.array([rx, float(bmax[1]), 0.0], dtype=np.float64)

        # Heading toward sector center
        dx = center[0] - pos[0]
        dy = center[1] - pos[1]
        heading = math.degrees(math.atan2(dx, dy)) % 360.0

        # Add some jitter (±15°)
        heading = (heading + self._rng.uniform(-15.0, 15.0)) % 360.0

        return pos, heading
