"""Airspace sector data model."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Sector:
    """Airspace sector definition.

    Sectors are rectangular 3D volumes defined by min/max corners in km.
    """

    id: str
    name: str
    bounds_min: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    bounds_max: np.ndarray = field(default_factory=lambda: np.array([100.0, 100.0, 15.0], dtype=np.float64))
    capacity: int = 50
    active: bool = True

    def __post_init__(self) -> None:
        """Ensure bounds are NumPy float64 arrays."""
        if not isinstance(self.bounds_min, np.ndarray):
            self.bounds_min = np.array(self.bounds_min, dtype=np.float64)
        elif self.bounds_min.dtype != np.float64:
            self.bounds_min = self.bounds_min.astype(np.float64)

        if not isinstance(self.bounds_max, np.ndarray):
            self.bounds_max = np.array(self.bounds_max, dtype=np.float64)
        elif self.bounds_max.dtype != np.float64:
            self.bounds_max = self.bounds_max.astype(np.float64)

    @property
    def center(self) -> np.ndarray:
        """Center point of the sector."""
        return (self.bounds_min + self.bounds_max) / 2.0

    @property
    def size(self) -> np.ndarray:
        """Dimensions of the sector [dx, dy, dz] in km."""
        return self.bounds_max - self.bounds_min

    def contains(self, position: np.ndarray) -> bool:
        """Check if a 3D position is within this sector."""
        return bool(np.all(position >= self.bounds_min) and np.all(position <= self.bounds_max))

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "bounds_min": self.bounds_min.tolist(),
            "bounds_max": self.bounds_max.tolist(),
            "capacity": self.capacity,
            "active": self.active,
            "center": self.center.tolist(),
            "size": self.size.tolist(),
        }
