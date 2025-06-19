"""Conflict detection and resolution engine for ATC simulation.

Detects separation violations between aircraft using octree-accelerated
neighbor queries, tracks active conflicts, and generates resolution
advisories (altitude / heading adjustments).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from src.engine.physics import FT_TO_KM, NM_TO_KM
from src.models.aircraft import Aircraft, AircraftStatus
from src.models.events import ConflictDetectedEvent
from src.spatial.octree import Octree

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------
_SEARCH_RADIUS_MULTIPLIER: float = 2.0  # query 2x separation to catch approaching conflicts
_RESOLUTION_ALT_OFFSET_FT: float = 500.0
_RESOLUTION_HDG_OFFSET_DEG: float = 30.0

# Statuses that should be excluded from conflict detection
_INACTIVE_STATUSES: frozenset[AircraftStatus] = frozenset(
    {AircraftStatus.LANDED, AircraftStatus.REMOVED, AircraftStatus.DEPARTING}
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ConflictInfo:
    """Record of a detected separation violation between two aircraft.

    Attributes
    ----------
    aircraft_id_1 : str
        Identifier of the first aircraft (lexicographically smaller).
    aircraft_id_2 : str
        Identifier of the second aircraft.
    horizontal_distance_nm : float
        Horizontal distance between the pair in nautical miles at detection.
    vertical_distance_ft : float
        Vertical distance between the pair in feet at detection.
    detected_at : float
        Simulation time (seconds) when the conflict was first detected.
    resolution_applied : bool
        ``True`` once a resolution advisory has been issued for this conflict.
    """

    aircraft_id_1: str
    aircraft_id_2: str
    horizontal_distance_nm: float
    vertical_distance_ft: float
    detected_at: float
    resolution_applied: bool = False


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------
class ConflictDetector:
    """Detects and resolves separation violations between aircraft.

    Uses an :class:`Octree` for efficient spatial queries and tracks active
    conflicts across successive simulation ticks.

    Parameters
    ----------
    horizontal_separation_nm : float
        Required horizontal separation standard in nautical miles.
    vertical_separation_ft : float
        Required vertical separation standard in feet.
    """

    def __init__(
        self,
        horizontal_separation_nm: float = 5.0,
        vertical_separation_ft: float = 1000.0,
    ) -> None:
        self.horizontal_separation_nm: float = horizontal_separation_nm
        self.vertical_separation_ft: float = vertical_separation_ft
        self._active_conflicts: dict[tuple[str, str], ConflictInfo] = {}

    # ------------------------------------------------------------------
    # 1. Detection
    # ------------------------------------------------------------------
    def detect_conflicts(
        self,
        aircraft_list: list[Aircraft],
        octree: Octree,
        sim_time: float,
    ) -> list[ConflictDetectedEvent]:
        """Scan all aircraft for new separation violations.

        Builds a positions array from *aircraft_list*, rebuilds the *octree*,
        then performs pairwise neighbor checks.  Only **newly** detected
        conflicts produce events; existing active conflicts are silently
        maintained.

        Parameters
        ----------
        aircraft_list : list[Aircraft]
            All aircraft currently in the simulation.
        octree : Octree
            Spatial index instance (will be rebuilt in-place).
        sim_time : float
            Current simulation clock in seconds.

        Returns
        -------
        list[ConflictDetectedEvent]
            Events for conflicts detected for the first time this call.
        """
        n = len(aircraft_list)
        if n < 2:
            return []

        # Build positions array (N, 3) from aircraft
        positions = np.empty((n, 3), dtype=np.float64)
        for i, ac in enumerate(aircraft_list):
            positions[i] = ac.position

        # Rebuild the spatial index with current positions
        octree.rebuild(positions)

        # Search radius in km: 2x the horizontal separation converted to km
        search_radius_km: float = _SEARCH_RADIUS_MULTIPLIER * self.horizontal_separation_nm * NM_TO_KM

        # Build a quick id -> index lookup and status cache
        id_to_idx: dict[str, int] = {ac.id: i for i, ac in enumerate(aircraft_list)}

        new_events: list[ConflictDetectedEvent] = []
        checked_pairs: set[tuple[str, str]] = set()

        for i, ac_a in enumerate(aircraft_list):
            # Skip inactive aircraft entirely
            if ac_a.status in _INACTIVE_STATUSES:
                continue

            neighbor_indices = octree.query_neighbors(i, search_radius_km)

            for j in neighbor_indices:
                ac_b = aircraft_list[j]

                # Skip inactive neighbors
                if ac_b.status in _INACTIVE_STATUSES:
                    continue

                # Canonical pair key (sorted tuple) to avoid duplicates
                pair_key: tuple[str, str] = (ac_a.id, ac_b.id) if ac_a.id < ac_b.id else (ac_b.id, ac_a.id)
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                # --- Distance computation ---
                dx = positions[j, 0] - positions[i, 0]
                dy = positions[j, 1] - positions[i, 1]
                horizontal_km = math.sqrt(dx * dx + dy * dy)
                horizontal_nm = horizontal_km / NM_TO_KM

                vertical_ft = abs(ac_a.altitude_ft - ac_b.altitude_ft)

                # Check separation standards
                if horizontal_nm < self.horizontal_separation_nm and vertical_ft < self.vertical_separation_ft:
                    # It's a conflict — is it new?
                    if pair_key not in self._active_conflicts:
                        info = ConflictInfo(
                            aircraft_id_1=pair_key[0],
                            aircraft_id_2=pair_key[1],
                            horizontal_distance_nm=horizontal_nm,
                            vertical_distance_ft=vertical_ft,
                            detected_at=sim_time,
                        )
                        self._active_conflicts[pair_key] = info

                        event = ConflictDetectedEvent(
                            aircraft_id_1=pair_key[0],
                            aircraft_id_2=pair_key[1],
                            callsign_1=(ac_a.callsign if ac_a.id == pair_key[0] else ac_b.callsign),
                            callsign_2=(ac_b.callsign if ac_b.id == pair_key[1] else ac_a.callsign),
                            horizontal_distance_nm=horizontal_nm,
                            vertical_distance_ft=vertical_ft,
                            resolution_action="",
                            simulation_time=sim_time,
                        )
                        new_events.append(event)

        return new_events

    # ------------------------------------------------------------------
    # 2. Resolution advisories
    # ------------------------------------------------------------------
    def resolve_conflicts(
        self,
        aircraft_list: list[Aircraft],
    ) -> list[dict[str, str | float]]:
        """Generate resolution advisories for every active conflict.

        For each active conflict the resolver applies two strategies:

        * **Primary — altitude separation**: the aircraft with the lower
          :pyattr:`priority_score` climbs by ``_RESOLUTION_ALT_OFFSET_FT``
          and the other descends by the same amount.
        * **Secondary — heading divergence**: each aircraft receives a
          ``_RESOLUTION_HDG_OFFSET_DEG`` offset from its current heading
          (one turns left, the other right).

        Parameters
        ----------
        aircraft_list : list[Aircraft]
            All aircraft currently in the simulation.

        Returns
        -------
        list[dict]
            Each dict has keys ``"aircraft_id"`` (str), ``"action"``
            (``"altitude"`` | ``"heading"`` | ``"speed"``), and ``"value"``
            (float).
        """
        if not self._active_conflicts:
            return []

        # Build an id -> Aircraft lookup
        ac_lookup: dict[str, Aircraft] = {ac.id: ac for ac in aircraft_list}

        advisories: list[dict[str, str | float]] = []

        for pair_key, info in self._active_conflicts.items():
            if info.resolution_applied:
                continue

            ac_a = ac_lookup.get(info.aircraft_id_1)
            ac_b = ac_lookup.get(info.aircraft_id_2)
            if ac_a is None or ac_b is None:
                continue

            # Determine which aircraft climbs (lower priority_score climbs)
            if ac_a.priority_score <= ac_b.priority_score:
                climber, descender = ac_a, ac_b
            else:
                climber, descender = ac_b, ac_a

            # Primary: altitude separation
            advisories.append(
                {
                    "aircraft_id": climber.id,
                    "action": "altitude",
                    "value": climber.altitude_ft + _RESOLUTION_ALT_OFFSET_FT,
                }
            )
            advisories.append(
                {
                    "aircraft_id": descender.id,
                    "action": "altitude",
                    "value": descender.altitude_ft - _RESOLUTION_ALT_OFFSET_FT,
                }
            )

            # Secondary: heading divergence
            advisories.append(
                {
                    "aircraft_id": climber.id,
                    "action": "heading",
                    "value": (climber.heading + _RESOLUTION_HDG_OFFSET_DEG) % 360.0,
                }
            )
            advisories.append(
                {
                    "aircraft_id": descender.id,
                    "action": "heading",
                    "value": (descender.heading - _RESOLUTION_HDG_OFFSET_DEG) % 360.0,
                }
            )

            info.resolution_applied = True

        return advisories

    # ------------------------------------------------------------------
    # 3. Active conflict accessor
    # ------------------------------------------------------------------
    def get_active_conflicts(self) -> list[ConflictInfo]:
        """Return a snapshot of all currently tracked conflicts.

        Returns
        -------
        list[ConflictInfo]
            Shallow copy of the active conflict records.
        """
        return list(self._active_conflicts.values())

    # ------------------------------------------------------------------
    # 4. Cleanup resolved conflicts
    # ------------------------------------------------------------------
    def cleanup_resolved(
        self,
        aircraft_list: list[Aircraft],
        octree: Octree,
    ) -> list[tuple[str, str]]:
        """Remove conflicts where aircraft now satisfy separation standards.

        Iterates over all active conflicts, recomputes separation distances,
        and discards any pair that is no longer in violation.

        Parameters
        ----------
        aircraft_list : list[Aircraft]
            All aircraft currently in the simulation.
        octree : Octree
            The spatial index (not modified; only aircraft positions are read).

        Returns
        -------
        list[tuple[str, str]]
            Pair keys ``(id_1, id_2)`` for conflicts that were resolved and
            removed from the active set.
        """
        if not self._active_conflicts:
            return []

        ac_lookup: dict[str, Aircraft] = {ac.id: ac for ac in aircraft_list}
        resolved: list[tuple[str, str]] = []

        for pair_key in list(self._active_conflicts.keys()):
            ac_a = ac_lookup.get(pair_key[0])
            ac_b = ac_lookup.get(pair_key[1])

            # If either aircraft has left the simulation, clear the conflict
            if ac_a is None or ac_b is None:
                resolved.append(pair_key)
                continue

            # If either aircraft is now inactive, clear the conflict
            if ac_a.status in _INACTIVE_STATUSES or ac_b.status in _INACTIVE_STATUSES:
                resolved.append(pair_key)
                continue

            # Recompute separation
            dx = ac_b.position[0] - ac_a.position[0]
            dy = ac_b.position[1] - ac_a.position[1]
            horizontal_nm = math.sqrt(dx * dx + dy * dy) / NM_TO_KM
            vertical_ft = abs(ac_a.altitude_ft - ac_b.altitude_ft)

            # Resolved if EITHER separation standard is now met
            if horizontal_nm >= self.horizontal_separation_nm or vertical_ft >= self.vertical_separation_ft:
                resolved.append(pair_key)

        # Remove resolved pairs
        for pair_key in resolved:
            del self._active_conflicts[pair_key]

        return resolved
