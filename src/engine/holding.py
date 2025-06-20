"""Holding pattern manager for ATC simulation.

Manages racetrack holding patterns: assigns aircraft to holding fixes,
updates positions through the four-leg racetrack, determines entry types,
and manages altitude-separated stacks.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

from src.engine.physics import NM_TO_KM, KT_TO_KM_S, DEG_TO_RAD, RAD_TO_DEG, FT_TO_KM
from src.models.aircraft import Aircraft, AircraftStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOLDING_SPEED_KT: float = 230.0  # Reduced speed while holding
FIX_PROXIMITY_NM: float = 0.5  # Distance to consider "at the fix"
FIX_PROXIMITY_KM: float = FIX_PROXIMITY_NM * NM_TO_KM
LEG_LENGTH_NM: float = 4.0  # Standard inbound/outbound leg length
LEG_LENGTH_KM: float = LEG_LENGTH_NM * NM_TO_KM
ALTITUDE_SEPARATION_FT: float = 1000.0  # Vertical separation between stack levels
TURN_RATE_DEG_S: float = 3.0  # Standard rate turn


class HoldingPhase(Enum):
    """Phases within a single racetrack orbit."""

    INBOUND = auto()  # Flying toward the holding fix
    OVER_FIX = auto()  # At the fix, beginning outbound turn
    OUTBOUND = auto()  # Flying away from the fix
    OUTBOUND_END = auto()  # At the end of outbound leg, beginning inbound turn


class EntryType(Enum):
    """Standard ICAO holding pattern entry procedures."""

    DIRECT = auto()  # Heading within 110 of inbound course — turn and enter
    TEARDROP = auto()  # Heading in the teardrop sector — 30 offset entry
    PARALLEL = auto()  # Heading in the parallel sector — fly parallel, then turn


@dataclass
class HoldingFix:
    """Definition of a holding fix (geographical point with pattern rules).

    Attributes
    ----------
    id : str
        Unique fix identifier (e.g. ``"WOBUN"``).
    position : np.ndarray
        3-D position in km ``[x, y, z]``.
    inbound_heading : float
        Inbound course to the fix in degrees (0=N, 90=E).
    altitude_ft : float
        Base altitude of the lowest stack level.
    leg_length_nm : float
        Distance of each straight leg.
    turn_direction : str
        ``"right"`` (standard) or ``"left"``.
    max_aircraft : int
        Maximum aircraft in this pattern.
    altitude_separation_ft : float
        Vertical separation between stack levels.
    """

    id: str
    position: np.ndarray
    inbound_heading: float
    altitude_ft: float = 10000.0
    leg_length_nm: float = LEG_LENGTH_NM
    turn_direction: str = "right"
    max_aircraft: int = 6
    altitude_separation_ft: float = ALTITUDE_SEPARATION_FT

    def __post_init__(self) -> None:
        if not isinstance(self.position, np.ndarray):
            self.position = np.array(self.position, dtype=np.float64)

    @property
    def outbound_heading(self) -> float:
        """Reciprocal of the inbound course."""
        return (self.inbound_heading + 180.0) % 360.0

    @property
    def leg_length_km(self) -> float:
        return self.leg_length_nm * NM_TO_KM


@dataclass
class HoldingAssignment:
    """Per-aircraft state while inside a holding pattern."""

    aircraft_id: str
    fix_id: str
    stack_level: int  # 0 = lowest, 1 = next up, ...
    phase: HoldingPhase = HoldingPhase.INBOUND
    orbits_completed: int = 0
    entry_type: EntryType = EntryType.DIRECT
    entry_complete: bool = False


class HoldingPatternManager:
    """Manages all holding patterns in the simulation.

    Lifecycle per aircraft:
        1. ``assign_holding(aircraft, fix_id)`` — put aircraft into a fix's stack
        2. ``update_holding(aircraft, dt)`` — called each tick to steer through racetrack
        3. ``release_from_holding(aircraft_id)`` — remove from pattern
    """

    def __init__(self) -> None:
        self._fixes: dict[str, HoldingFix] = {}
        # fix_id -> [assignment, ...] ordered by stack_level
        self._stacks: dict[str, list[HoldingAssignment]] = {}
        # aircraft_id -> assignment (fast lookup)
        self._assignments: dict[str, HoldingAssignment] = {}

    # ------------------------------------------------------------------
    # Fix management
    # ------------------------------------------------------------------

    def register_fix(self, fix: HoldingFix) -> None:
        """Register a holding fix. Overwrites if id already exists."""
        self._fixes[fix.id] = fix
        if fix.id not in self._stacks:
            self._stacks[fix.id] = []

    def get_fix(self, fix_id: str) -> Optional[HoldingFix]:
        return self._fixes.get(fix_id)

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def assign_holding(
        self,
        aircraft: Aircraft,
        fix_id: str,
        sim_time: float,
    ) -> Optional[HoldingAssignment]:
        """Assign an aircraft to a holding pattern.

        Returns None if the fix doesn't exist or the stack is full.
        """
        fix = self._fixes.get(fix_id)
        if fix is None:
            logger.warning("Holding fix %s not found", fix_id)
            return None

        stack = self._stacks[fix_id]
        if len(stack) >= fix.max_aircraft:
            logger.warning("Holding fix %s full (%d/%d)", fix_id, len(stack), fix.max_aircraft)
            return None

        if aircraft.id in self._assignments:
            logger.warning("Aircraft %s already in holding", aircraft.callsign)
            return self._assignments[aircraft.id]

        stack_level = len(stack)
        entry_type = self._determine_entry(aircraft.heading, fix.inbound_heading, fix.turn_direction)

        assignment = HoldingAssignment(
            aircraft_id=aircraft.id,
            fix_id=fix_id,
            stack_level=stack_level,
            entry_type=entry_type,
        )

        stack.append(assignment)
        self._assignments[aircraft.id] = assignment

        # Update aircraft state
        aircraft.status = AircraftStatus.HOLDING
        aircraft.holding_fix = fix_id
        aircraft.holding_start_time = sim_time
        aircraft.target_speed_knots = HOLDING_SPEED_KT

        # Set target altitude based on stack level
        aircraft.target_altitude_ft = fix.altitude_ft + (stack_level * fix.altitude_separation_ft)

        logger.info(
            "Assigned %s to hold at %s, level %d, entry=%s",
            aircraft.callsign,
            fix_id,
            stack_level,
            entry_type.name,
        )
        return assignment

    def release_from_holding(self, aircraft_id: str) -> bool:
        """Remove aircraft from its holding pattern.

        Returns True if the aircraft was in holding and removed.
        """
        assignment = self._assignments.pop(aircraft_id, None)
        if assignment is None:
            return False

        stack = self._stacks.get(assignment.fix_id, [])
        self._stacks[assignment.fix_id] = [a for a in stack if a.aircraft_id != aircraft_id]

        # Re-index stack levels
        for i, a in enumerate(self._stacks[assignment.fix_id]):
            a.stack_level = i

        logger.info("Released %s from holding at %s", aircraft_id, assignment.fix_id)
        return True

    # ------------------------------------------------------------------
    # Tick update
    # ------------------------------------------------------------------

    def update_holding(self, aircraft: Aircraft, dt: float) -> None:
        """Update a single aircraft's position within its holding pattern.

        Implements a four-phase racetrack:
            INBOUND  -> fly toward fix on inbound heading
            OVER_FIX -> at fix, begin turn to outbound
            OUTBOUND -> fly outbound leg
            OUTBOUND_END -> at end, begin turn to inbound

        Parameters
        ----------
        aircraft : Aircraft
            The aircraft to update. Must be in holding.
        dt : float
            Tick interval in seconds.
        """
        assignment = self._assignments.get(aircraft.id)
        if assignment is None:
            return

        fix = self._fixes.get(assignment.fix_id)
        if fix is None:
            return

        # Distance from aircraft to fix (2-D, XY plane)
        delta = fix.position[:2] - aircraft.position[:2]
        dist_to_fix_km = float(np.sqrt(delta[0] ** 2 + delta[1] ** 2))

        turn_sign = 1.0 if fix.turn_direction == "right" else -1.0

        if assignment.phase == HoldingPhase.INBOUND:
            # Steer toward the fix
            aircraft.target_heading = fix.inbound_heading

            if dist_to_fix_km < FIX_PROXIMITY_KM:
                assignment.phase = HoldingPhase.OVER_FIX
                assignment.orbits_completed += 1
                aircraft.holding_outbound = False

        elif assignment.phase == HoldingPhase.OVER_FIX:
            # Begin turn to outbound heading
            outbound_hdg = fix.outbound_heading
            aircraft.target_heading = outbound_hdg

            # Check if we've roughly achieved the outbound heading
            hdg_diff = abs((aircraft.heading - outbound_hdg + 180.0) % 360.0 - 180.0)
            if hdg_diff < 5.0:
                assignment.phase = HoldingPhase.OUTBOUND
                aircraft.holding_outbound = True
                aircraft.holding_leg_heading = outbound_hdg

        elif assignment.phase == HoldingPhase.OUTBOUND:
            # Fly outbound leg
            aircraft.target_heading = fix.outbound_heading

            if dist_to_fix_km >= fix.leg_length_km:
                assignment.phase = HoldingPhase.OUTBOUND_END

        elif assignment.phase == HoldingPhase.OUTBOUND_END:
            # Turn back to inbound heading
            aircraft.target_heading = fix.inbound_heading

            hdg_diff = abs((aircraft.heading - fix.inbound_heading + 180.0) % 360.0 - 180.0)
            if hdg_diff < 5.0:
                assignment.phase = HoldingPhase.INBOUND
                aircraft.holding_outbound = False

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_holding_count(self, fix_id: str) -> int:
        """Number of aircraft currently holding at a fix."""
        return len(self._stacks.get(fix_id, []))

    def get_stack_order(self, fix_id: str) -> list[str]:
        """Aircraft IDs in stack order (lowest first)."""
        stack = self._stacks.get(fix_id, [])
        return [a.aircraft_id for a in sorted(stack, key=lambda a: a.stack_level)]

    def get_assignment(self, aircraft_id: str) -> Optional[HoldingAssignment]:
        return self._assignments.get(aircraft_id)

    def is_holding(self, aircraft_id: str) -> bool:
        return aircraft_id in self._assignments

    @property
    def total_holding(self) -> int:
        """Total aircraft in holding across all fixes."""
        return len(self._assignments)

    # ------------------------------------------------------------------
    # Entry type determination
    # ------------------------------------------------------------------

    def determine_entry_type(self, aircraft: Aircraft, fix: HoldingFix) -> EntryType:
        """Public API: determine holding entry type for an aircraft and fix.

        Parameters
        ----------
        aircraft : Aircraft
            The aircraft approaching the fix.
        fix : HoldingFix
            The holding fix to enter.

        Returns
        -------
        EntryType
        """
        return self._determine_entry(aircraft.heading, fix.inbound_heading, fix.turn_direction)

    @staticmethod
    def _determine_entry(
        aircraft_heading: float,
        inbound_heading: float,
        turn_direction: str,
    ) -> EntryType:
        """Determine holding entry type based on aircraft heading relative to the fix.

        Uses the standard 70/110 sector rule:
            - DIRECT:   heading within 110 of the inbound course (from outbound side)
            - TEARDROP: heading in the 70 sector on the holding side
            - PARALLEL: heading in the 110 sector on the non-holding side

        Parameters
        ----------
        aircraft_heading : float
            Current aircraft heading in degrees.
        inbound_heading : float
            Inbound course to the fix in degrees.
        turn_direction : str
            ``"right"`` or ``"left"``.
        """
        # Relative bearing: difference from the reciprocal of inbound heading
        outbound_heading = (inbound_heading + 180.0) % 360.0

        # Angle from outbound heading to aircraft heading, normalized to [-180, 180)
        diff = (aircraft_heading - outbound_heading + 180.0) % 360.0 - 180.0

        if turn_direction == "right":
            # Standard right-hand pattern
            if -70.0 <= diff <= 110.0:
                return EntryType.DIRECT
            elif diff < -70.0:
                return EntryType.TEARDROP
            else:
                return EntryType.PARALLEL
        else:
            # Left-hand pattern (mirror)
            if -110.0 <= diff <= 70.0:
                return EntryType.DIRECT
            elif diff > 70.0:
                return EntryType.TEARDROP
            else:
                return EntryType.PARALLEL
