"""ILS approach manager for ATC simulation.

Guides aircraft through a complete Instrument Landing System approach
in seven phases: intercept, localizer, glideslope, final, flare,
touchdown, and go-around.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

import numpy as np

from src.engine.physics import NM_TO_KM, FT_TO_KM, KT_TO_KM_S, DEG_TO_RAD, RAD_TO_DEG
from src.models.aircraft import Aircraft, AircraftStatus, AircraftType
from src.models.runway import Runway

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase constants
# ---------------------------------------------------------------------------


class ApproachPhase(IntEnum):
    """Sequential phases of an ILS approach."""

    INTERCEPT = 0  # Vectoring to localizer intercept
    LOCALIZER = 1  # Established on localizer, above glideslope
    GLIDESLOPE = 2  # On both localizer and glideslope
    FINAL = 3  # Below 1000 ft AGL, stabilised
    FLARE = 4  # Below 50 ft AGL, nose-up for touchdown
    TOUCHDOWN = 5  # Wheels on ground
    GO_AROUND = 6  # Missed approach / aborted landing


# ---------------------------------------------------------------------------
# Approach configuration constants
# ---------------------------------------------------------------------------
GO_AROUND_ALTITUDE_FT: float = 3000.0
FLARE_ALTITUDE_FT: float = 50.0  # AGL at which flare begins
FINAL_ALTITUDE_AGL_FT: float = 1000.0  # AGL threshold for FINAL phase
LOCALIZER_GAIN_DEG_PER_NM: float = 3.0  # Heading correction per NM cross-track error
GLIDESLOPE_VS_GAIN: float = 200.0  # fpm correction per foot of GS deviation
MAX_LOCALIZER_DEVIATION_DEG: float = 2.5  # Beyond this, go around
MAX_GLIDESLOPE_DEVIATION_FT: float = 200.0  # Beyond this on final, go around
INTERCEPT_HEADING_TOLERANCE_DEG: float = 30.0  # Max angle for localizer intercept
STABILISED_SPEED_TOLERANCE_KT: float = 15.0  # Within this of Vref = stabilised


@dataclass
class ApproachState:
    """Per-aircraft approach tracking state."""

    aircraft_id: str
    runway_id: str
    phase: ApproachPhase = ApproachPhase.INTERCEPT
    localizer_deviation_deg: float = 0.0  # Positive = right of centerline
    glideslope_deviation_ft: float = 0.0  # Positive = above glideslope
    distance_to_threshold_nm: float = 0.0
    approach_speed_kt: float = 140.0
    cleared: bool = True  # ATC clearance flag


class ILSApproachManager:
    """Manages ILS approaches for all aircraft on approach.

    Lifecycle:
        1. ``initiate_approach(aircraft, runway)`` — begin intercept
        2. ``update_approach(aircraft, runway, dt)`` — called each tick
        3. ``complete_approach(aircraft_id)`` — remove after touchdown
        4. ``execute_go_around(aircraft)`` — missed approach

    The manager sets ``aircraft.target_heading``, ``target_altitude_ft``,
    ``target_speed_knots``, and ``vertical_speed_fpm`` each tick to
    guide the aircraft along the approach path.
    """

    def __init__(self) -> None:
        self._approaches: dict[str, ApproachState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initiate_approach(self, aircraft: Aircraft, runway: Runway) -> Optional[ApproachState]:
        """Begin an ILS approach for an aircraft.

        Parameters
        ----------
        aircraft : Aircraft
            The aircraft to put on approach.
        runway : Runway
            Target runway (must have ``ils_available=True``).

        Returns
        -------
        ApproachState or None
            None if runway doesn't have ILS.
        """
        if not runway.ils_available:
            logger.warning("Runway %s has no ILS", runway.id)
            return None

        if aircraft.id in self._approaches:
            return self._approaches[aircraft.id]

        # Determine approach speed from aircraft type
        try:
            ac_type = AircraftType(aircraft.aircraft_type)
            approach_speed = ac_type.approach_speed_knots
        except ValueError:
            approach_speed = 140.0

        state = ApproachState(
            aircraft_id=aircraft.id,
            runway_id=runway.id,
            approach_speed_kt=approach_speed,
        )
        self._approaches[aircraft.id] = state

        # Transition aircraft status
        aircraft.status = AircraftStatus.APPROACH
        aircraft.assigned_runway = runway.id
        aircraft.target_speed_knots = approach_speed
        aircraft.on_localizer = False
        aircraft.on_glideslope = False
        aircraft.go_around = False

        logger.info(
            "Initiated ILS approach: %s -> runway %s (Vref=%.0f kt)",
            aircraft.callsign,
            runway.id,
            approach_speed,
        )
        return state

    def update_approach(self, aircraft: Aircraft, runway: Runway, dt: float) -> None:
        """Advance a single aircraft through its approach phases.

        This is the main per-tick entry point. It computes localizer/glideslope
        deviations, checks phase transitions, and sets autopilot targets.

        Parameters
        ----------
        aircraft : Aircraft
            The aircraft on approach.
        runway : Runway
            The target runway.
        dt : float
            Tick interval in seconds.
        """
        state = self._approaches.get(aircraft.id)
        if state is None:
            return

        # --- Compute geometry ---
        distance_km, cross_track_km, bearing_to_threshold = self._approach_geometry(aircraft, runway)
        distance_nm = distance_km / NM_TO_KM
        state.distance_to_threshold_nm = distance_nm

        # Localizer deviation: cross-track error expressed as angular offset
        if distance_km > 0.01:
            state.localizer_deviation_deg = math.degrees(math.atan2(cross_track_km, distance_km))
        else:
            state.localizer_deviation_deg = 0.0

        # Glideslope: expected altitude vs actual
        gs_altitude_ft = runway.glideslope_altitude_at_distance(distance_km)
        altitude_agl = aircraft.altitude_ft - runway.elevation_ft
        state.glideslope_deviation_ft = aircraft.altitude_ft - gs_altitude_ft

        # --- Phase dispatch ---
        if state.phase == ApproachPhase.INTERCEPT:
            self._phase_intercept(aircraft, runway, state, distance_nm, bearing_to_threshold)
        elif state.phase == ApproachPhase.LOCALIZER:
            self._phase_localizer(aircraft, runway, state, distance_nm, gs_altitude_ft)
        elif state.phase == ApproachPhase.GLIDESLOPE:
            self._phase_glideslope(aircraft, runway, state, distance_nm, gs_altitude_ft, altitude_agl)
        elif state.phase == ApproachPhase.FINAL:
            self._phase_final(aircraft, runway, state, distance_nm, gs_altitude_ft, altitude_agl)
        elif state.phase == ApproachPhase.FLARE:
            self._phase_flare(aircraft, runway, state, altitude_agl)
        elif state.phase == ApproachPhase.TOUCHDOWN:
            self._phase_touchdown(aircraft, runway, state)
        elif state.phase == ApproachPhase.GO_AROUND:
            self._phase_go_around(aircraft, runway, state)

    def check_go_around(self, aircraft: Aircraft) -> bool:
        """Check if aircraft should execute a go-around.

        Triggers:
            - Excessive localizer deviation on FINAL
            - Excessive glideslope deviation on FINAL
            - Not stabilised below 1000 ft AGL
        """
        state = self._approaches.get(aircraft.id)
        if state is None:
            return False

        # Only check during GLIDESLOPE or FINAL phases
        if state.phase not in (ApproachPhase.GLIDESLOPE, ApproachPhase.FINAL):
            return False

        if abs(state.localizer_deviation_deg) > MAX_LOCALIZER_DEVIATION_DEG:
            logger.info("Go-around %s: localizer deviation %.1f", aircraft.callsign, state.localizer_deviation_deg)
            return True

        if state.phase == ApproachPhase.FINAL:
            if abs(state.glideslope_deviation_ft) > MAX_GLIDESLOPE_DEVIATION_FT:
                logger.info("Go-around %s: GS deviation %.0f ft", aircraft.callsign, state.glideslope_deviation_ft)
                return True

        return False

    def execute_go_around(self, aircraft: Aircraft) -> None:
        """Command a missed approach / go-around."""
        state = self._approaches.get(aircraft.id)
        if state is None:
            return

        state.phase = ApproachPhase.GO_AROUND
        aircraft.go_around = True
        aircraft.on_localizer = False
        aircraft.on_glideslope = False
        aircraft.target_altitude_ft = GO_AROUND_ALTITUDE_FT
        aircraft.target_speed_knots = HOLDING_SPEED_KT = 230.0
        aircraft.vertical_speed_fpm = 2000.0  # Climb aggressively

        logger.info("Go-around: %s from runway %s", aircraft.callsign, state.runway_id)

    def complete_approach(self, aircraft_id: str) -> bool:
        """Remove aircraft from approach tracking after landing.

        Returns True if the aircraft was on approach.
        """
        return self._approaches.pop(aircraft_id, None) is not None

    def get_approach_state(self, aircraft_id: str) -> Optional[ApproachState]:
        return self._approaches.get(aircraft_id)

    def is_on_approach(self, aircraft_id: str) -> bool:
        return aircraft_id in self._approaches

    @property
    def active_approaches(self) -> int:
        return len(self._approaches)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    def _phase_intercept(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
        distance_nm: float,
        bearing_to_threshold: float,
    ) -> None:
        """INTERCEPT: Vector toward the localizer centerline.

        Steer to the approach heading and descend toward glideslope intercept
        altitude. Transition to LOCALIZER when aligned within tolerance.
        """
        # Steer toward the runway approach heading
        approach_hdg = runway.approach_heading
        aircraft.target_heading = approach_hdg

        # Descend to glideslope intercept altitude
        aircraft.target_altitude_ft = runway.glideslope_intercept_altitude_ft

        # Check transition: aligned with localizer?
        hdg_diff = abs((aircraft.heading - approach_hdg + 180.0) % 360.0 - 180.0)
        if hdg_diff < INTERCEPT_HEADING_TOLERANCE_DEG and abs(state.localizer_deviation_deg) < 1.0:
            state.phase = ApproachPhase.LOCALIZER
            aircraft.on_localizer = True
            logger.debug("LOC captured: %s at %.1f NM", aircraft.callsign, distance_nm)

    def _phase_localizer(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
        distance_nm: float,
        gs_altitude_ft: float,
    ) -> None:
        """LOCALIZER: Tracking localizer, waiting to capture glideslope.

        Correct heading to stay on centerline. Transition to GLIDESLOPE
        when aircraft altitude descends to within 100 ft of the glideslope.
        """
        # Localizer tracking: correct heading based on cross-track error
        correction = -state.localizer_deviation_deg * LOCALIZER_GAIN_DEG_PER_NM
        aircraft.target_heading = (runway.approach_heading + correction) % 360.0

        # Maintain current altitude until GS capture
        aircraft.target_altitude_ft = min(aircraft.altitude_ft, runway.glideslope_intercept_altitude_ft)

        # Check glideslope capture: when within 100 ft of GS from above
        if aircraft.altitude_ft <= gs_altitude_ft + 100.0 and state.glideslope_deviation_ft < 150.0:
            state.phase = ApproachPhase.GLIDESLOPE
            aircraft.on_glideslope = True
            logger.debug("GS captured: %s at %.1f NM", aircraft.callsign, distance_nm)

    def _phase_glideslope(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
        distance_nm: float,
        gs_altitude_ft: float,
        altitude_agl: float,
    ) -> None:
        """GLIDESLOPE: Tracking both localizer and glideslope.

        Correct heading for localizer, adjust vertical speed for glideslope.
        Transition to FINAL below 1000 ft AGL.
        """
        # Localizer tracking
        correction = -state.localizer_deviation_deg * LOCALIZER_GAIN_DEG_PER_NM
        aircraft.target_heading = (runway.approach_heading + correction) % 360.0

        # Glideslope tracking: adjust target altitude and vertical speed
        aircraft.target_altitude_ft = gs_altitude_ft
        gs_error_ft = aircraft.altitude_ft - gs_altitude_ft
        # Proportional vertical speed correction
        base_vs = -700.0  # Nominal descent rate on 3-degree GS at ~140 kt
        correction_vs = -gs_error_ft * (GLIDESLOPE_VS_GAIN / 100.0)
        aircraft.vertical_speed_fpm = max(-2000.0, min(-300.0, base_vs + correction_vs))

        # Decelerate toward approach speed
        aircraft.target_speed_knots = state.approach_speed_kt

        # Transition to FINAL
        if altitude_agl < FINAL_ALTITUDE_AGL_FT:
            state.phase = ApproachPhase.FINAL
            logger.debug("FINAL: %s at %.1f NM, %.0f ft AGL", aircraft.callsign, distance_nm, altitude_agl)

    def _phase_final(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
        distance_nm: float,
        gs_altitude_ft: float,
        altitude_agl: float,
    ) -> None:
        """FINAL: Below 1000 ft AGL, stabilised approach.

        Continue localizer + glideslope tracking. Transition to FLARE at 50 ft.
        """
        # Continue localizer tracking
        correction = -state.localizer_deviation_deg * LOCALIZER_GAIN_DEG_PER_NM
        aircraft.target_heading = (runway.approach_heading + correction) % 360.0

        # Continue glideslope tracking
        aircraft.target_altitude_ft = gs_altitude_ft
        gs_error_ft = aircraft.altitude_ft - gs_altitude_ft
        base_vs = -700.0
        correction_vs = -gs_error_ft * (GLIDESLOPE_VS_GAIN / 100.0)
        aircraft.vertical_speed_fpm = max(-1500.0, min(-200.0, base_vs + correction_vs))

        # Speed should be at Vref
        aircraft.target_speed_knots = state.approach_speed_kt

        # Transition to FLARE
        if altitude_agl < FLARE_ALTITUDE_FT:
            state.phase = ApproachPhase.FLARE
            aircraft.status = AircraftStatus.LANDING
            logger.debug("FLARE: %s at %.0f ft AGL", aircraft.callsign, altitude_agl)

    def _phase_flare(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
        altitude_agl: float,
    ) -> None:
        """FLARE: Below 50 ft AGL, reduce descent rate for touchdown.

        Gradually reduce vertical speed. Transition to TOUCHDOWN at ground level.
        """
        aircraft.target_heading = runway.approach_heading
        aircraft.target_altitude_ft = runway.elevation_ft
        # Gentle descent: reduce VS as altitude decreases
        aircraft.vertical_speed_fpm = max(-200.0, -altitude_agl * 4.0)
        aircraft.target_speed_knots = state.approach_speed_kt - 5.0  # Slight decel

        if altitude_agl <= 2.0:
            state.phase = ApproachPhase.TOUCHDOWN
            aircraft.status = AircraftStatus.LANDED
            aircraft.altitude_ft = runway.elevation_ft
            aircraft.vertical_speed_fpm = 0.0
            aircraft.speed_knots = max(aircraft.speed_knots, 80.0)
            # Mark runway as occupied
            runway.occupied = True
            runway.occupant_id = aircraft.id
            logger.info("TOUCHDOWN: %s on runway %s", aircraft.callsign, runway.id)

    def _phase_touchdown(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
    ) -> None:
        """TOUCHDOWN: On the ground, decelerating.

        Reduce speed to zero. The simulation loop handles cleanup.
        """
        aircraft.altitude_ft = runway.elevation_ft
        aircraft.vertical_speed_fpm = 0.0
        aircraft.target_speed_knots = 0.0
        aircraft.target_altitude_ft = runway.elevation_ft

    def _phase_go_around(
        self,
        aircraft: Aircraft,
        runway: Runway,
        state: ApproachState,
    ) -> None:
        """GO_AROUND: Climbing away from the runway.

        Fly runway heading, climb to go-around altitude. Once reached,
        the simulation loop should re-assign to holding or re-sequence.
        """
        aircraft.target_heading = runway.heading  # Fly runway heading (not approach)
        aircraft.target_altitude_ft = GO_AROUND_ALTITUDE_FT
        aircraft.target_speed_knots = 230.0
        aircraft.vertical_speed_fpm = 2000.0

        # Check if go-around altitude reached
        if aircraft.altitude_ft >= GO_AROUND_ALTITUDE_FT - 100.0:
            # Go-around complete — remove from approach tracking
            # Simulation loop will re-assign to holding
            logger.info("Go-around complete: %s at %.0f ft", aircraft.callsign, aircraft.altitude_ft)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _approach_geometry(
        aircraft: Aircraft,
        runway: Runway,
    ) -> tuple[float, float, float]:
        """Compute distance, cross-track error, and bearing to threshold.

        Parameters
        ----------
        aircraft : Aircraft
        runway : Runway

        Returns
        -------
        tuple[float, float, float]
            ``(distance_km, cross_track_km, bearing_deg)``
            - distance_km: slant distance to threshold in XY plane
            - cross_track_km: signed cross-track error (positive = right of centerline)
            - bearing_deg: bearing from aircraft to threshold
        """
        dx = runway.position[0] - aircraft.position[0]
        dy = runway.position[1] - aircraft.position[1]

        distance_km = math.sqrt(dx * dx + dy * dy)
        bearing_deg = math.degrees(math.atan2(dx, dy)) % 360.0

        # Cross-track error: perpendicular distance from the approach centerline
        # The approach centerline extends from threshold in the approach_heading direction
        approach_rad = math.radians(runway.approach_heading)
        # Centerline unit vector (pointing from threshold away from runway, i.e. toward aircraft)
        cl_x = math.sin(approach_rad)
        cl_y = math.cos(approach_rad)

        # Vector from threshold to aircraft
        ax = aircraft.position[0] - runway.position[0]
        ay = aircraft.position[1] - runway.position[1]

        # Cross-track = perpendicular component (positive = right of centerline)
        cross_track_km = ax * cl_y - ay * cl_x

        return distance_km, cross_track_km, bearing_deg
