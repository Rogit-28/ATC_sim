"""Runway data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Runway:
    """Runway definition and real-time state.

    Position is the runway threshold in km coordinates.
    """

    id: str
    airport_icao: str
    heading: float  # Runway heading in degrees
    length_m: float  # Runway length in meters

    position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))

    # ILS
    ils_available: bool = True
    approach_heading: float = 0.0  # Inbound heading for approach
    glideslope_angle: float = 3.0  # Standard 3-degree glideslope
    localizer_width_deg: float = 2.5  # Half-width of localizer beam

    # State
    occupied: bool = False
    occupant_id: Optional[str] = None
    elevation_ft: float = 0.0  # Runway elevation MSL

    # Approach geometry (computed)
    decision_altitude_ft: float = 200.0  # DA for CAT I ILS
    glideslope_intercept_altitude_ft: float = 3000.0

    def __post_init__(self) -> None:
        """Ensure position is NumPy float64."""
        if not isinstance(self.position, np.ndarray):
            self.position = np.array(self.position, dtype=np.float64)
        elif self.position.dtype != np.float64:
            self.position = self.position.astype(np.float64)

        # Compute approach heading (reciprocal of runway heading)
        if self.approach_heading == 0.0 and self.heading != 0.0:
            self.approach_heading = (self.heading + 180.0) % 360.0

    @property
    def threshold_position(self) -> np.ndarray:
        """Runway threshold position (same as position)."""
        return self.position.copy()

    def glideslope_altitude_at_distance(self, distance_km: float) -> float:
        """Compute glideslope altitude at a given distance from threshold.

        Args:
            distance_km: Distance from threshold in km.

        Returns:
            Altitude in feet MSL.
        """
        distance_ft = distance_km * 3280.84  # km to feet
        altitude_above_threshold = distance_ft * np.tan(np.radians(self.glideslope_angle))
        return self.elevation_ft + altitude_above_threshold

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "airport_icao": self.airport_icao,
            "heading": round(self.heading, 1),
            "length_m": round(self.length_m, 1),
            "position": self.position.tolist(),
            "ils_available": self.ils_available,
            "approach_heading": round(self.approach_heading, 1),
            "glideslope_angle": self.glideslope_angle,
            "localizer_width_deg": self.localizer_width_deg,
            "occupied": self.occupied,
            "occupant_id": self.occupant_id,
            "elevation_ft": round(self.elevation_ft, 1),
            "decision_altitude_ft": self.decision_altitude_ft,
        }
