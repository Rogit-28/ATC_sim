"""Main simulation loop for ATC simulation.

Orchestrates all engine components at 20Hz (50ms ticks):
    1. Spawn new aircraft
    2. Rebuild octree
    3. Detect conflicts
    4. Resolve conflicts
    5. Update holding patterns
    6. Update ILS approaches
    7. Compute landing priorities
    8. Assign approaches / holdings
    9. Update physics (heading, altitude, speed, fuel)
    10. Integrate positions
    11. Check boundary exits / diversions
    12. Cleanup landed / removed aircraft
    13. Cleanup resolved conflicts
    14. Publish tick event
    15. Periodic snapshot
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.config import Settings, get_settings
from src.engine.approach import ApproachPhase, ILSApproachManager
from src.engine.conflict import ConflictDetector
from src.engine.holding import HoldingFix, HoldingPatternManager
from src.engine.physics import PhysicsEngine, FT_TO_KM, NM_TO_KM
from src.engine.priority import LandingPriorityCalculator
from src.engine.spawner import AircraftSpawner, SpawnConfig
from src.events.event_bus import EventBus, get_event_bus
from src.models.aircraft import Aircraft, AircraftIntent, AircraftStatus, AircraftType
from src.models.events import (
    AircraftDivertedEvent,
    AircraftLandedEvent,
    AircraftSpawnedEvent,
    Event,
    EventType,
)
from src.models.runway import Runway
from src.models.sector import Sector
from src.spatial.octree import Octree

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fuel burn phase multipliers
# ---------------------------------------------------------------------------
_FUEL_MULTIPLIER: dict[AircraftStatus, float] = {
    AircraftStatus.SPAWNED: 1.0,
    AircraftStatus.CRUISING: 1.0,
    AircraftStatus.DESCENDING: 0.6,
    AircraftStatus.HOLDING: 1.2,
    AircraftStatus.APPROACH: 0.4,
    AircraftStatus.LANDING: 0.1,
    AircraftStatus.LANDED: 0.0,
    AircraftStatus.DEPARTING: 1.5,
    AircraftStatus.DIVERTED: 1.0,
    AircraftStatus.EMERGENCY: 1.0,
    AircraftStatus.REMOVED: 0.0,
}

# Distance threshold for assigning approach
_APPROACH_TRIGGER_NM: float = 30.0
_HOLDING_TRIGGER_NM: float = 50.0


@dataclass
class SimulationStats:
    """Real-time simulation statistics."""

    tick: int = 0
    sim_time: float = 0.0
    aircraft_count: int = 0
    active_conflicts: int = 0
    holding_count: int = 0
    approach_count: int = 0
    landed_total: int = 0
    diverted_total: int = 0
    spawned_total: int = 0


class Simulation:
    """Main simulation engine.

    Wires together physics, conflict detection, holding, approach,
    spawning, and priority scoring into a coherent tick loop.
    """

    def __init__(
        self,
        sector: Sector,
        runways: list[Runway],
        holding_fixes: list[HoldingFix],
        settings: Optional[Settings] = None,
        spawn_seed: Optional[int] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._sector = sector
        self._runways = {r.id: r for r in runways}
        self._runway_list = runways

        # Simulation clock
        self._tick: int = 0
        self._sim_time: float = 0.0
        self._dt: float = self._settings.tick_interval_sec
        self._running: bool = False

        # Aircraft registry
        self._aircraft: dict[str, Aircraft] = {}
        self._aircraft_index: list[str] = []  # ordered ID list matching positions array

        # Engine components
        self._physics = PhysicsEngine(dt=self._dt)
        self._octree = Octree(
            max_depth=self._settings.octree_max_depth,
            leaf_threshold=16,
        )
        self._conflict_detector = ConflictDetector(
            horizontal_separation_nm=self._settings.separation_horizontal_nm,
            vertical_separation_ft=self._settings.separation_vertical_ft,
        )
        self._holding_mgr = HoldingPatternManager()
        self._approach_mgr = ILSApproachManager()
        self._priority_calc = LandingPriorityCalculator(
            weights=self._settings.priority_weights,
        )
        self._spawner = AircraftSpawner(
            config=SpawnConfig(
                spawn_rate_per_minute=self._settings.spawn_rate_per_minute,
                max_aircraft=self._settings.max_aircraft,
                seed=spawn_seed,
            ),
            sector=sector,
        )

        # Event bus
        self._event_bus: EventBus = get_event_bus()

        # Stats
        self._stats = SimulationStats()

        # Register holding fixes
        for fix in holding_fixes:
            self._holding_mgr.register_fix(fix)

        logger.info(
            "Simulation initialized: sector=%s, runways=%d, fixes=%d, dt=%.3fs",
            sector.name,
            len(runways),
            len(holding_fixes),
            self._dt,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the simulation loop. Runs until ``stop()`` is called."""
        self._running = True
        await self._event_bus.publish(
            EventType.SIMULATION_STARTED.value,
            Event(event_type=EventType.SIMULATION_STARTED, simulation_time=0.0),
        )
        logger.info("Simulation started at %d Hz", self._settings.simulation_tick_rate)

        try:
            while self._running:
                tick_start = time.perf_counter()
                await self._tick_step()
                elapsed = time.perf_counter() - tick_start

                # Sleep remaining time to maintain tick rate
                sleep_time = self._dt - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    if self._tick % 200 == 0:
                        logger.warning(
                            "Tick %d overran by %.1f ms",
                            self._tick,
                            (elapsed - self._dt) * 1000,
                        )
        finally:
            self._running = False
            await self._event_bus.publish(
                EventType.SIMULATION_STOPPED.value,
                Event(event_type=EventType.SIMULATION_STOPPED, simulation_time=self._sim_time),
            )
            logger.info("Simulation stopped at tick %d (%.1f s)", self._tick, self._sim_time)

    def stop(self) -> None:
        """Signal the simulation to stop after the current tick."""
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stats(self) -> SimulationStats:
        return self._stats

    @property
    def aircraft(self) -> dict[str, Aircraft]:
        """Read-only access to the aircraft registry."""
        return self._aircraft

    @property
    def sim_time(self) -> float:
        return self._sim_time

    @property
    def tick_count(self) -> int:
        return self._tick

    def get_aircraft_list(self) -> list[Aircraft]:
        """Return all aircraft as a list (for serialization)."""
        return list(self._aircraft.values())

    def get_runway(self, runway_id: str) -> Optional[Runway]:
        return self._runways.get(runway_id)

    # ------------------------------------------------------------------
    # Main tick sequence
    # ------------------------------------------------------------------

    async def _tick_step(self) -> None:
        """Execute one complete simulation tick (15 steps)."""

        # ── Step 1: Spawn new aircraft ─────────────────────
        if self._spawner.should_spawn(self._dt, len(self._aircraft)):
            ac = self._spawner.spawn_aircraft(self._sim_time)
            self._aircraft[ac.id] = ac
            ac.status = AircraftStatus.CRUISING
            self._stats.spawned_total += 1

            await self._event_bus.publish(
                EventType.AIRCRAFT_SPAWNED.value,
                AircraftSpawnedEvent(
                    aircraft_id=ac.id,
                    callsign=ac.callsign,
                    aircraft_type=ac.aircraft_type,
                    origin=ac.origin,
                    destination=ac.destination,
                    intent=ac.intent.name,
                    simulation_time=self._sim_time,
                ),
            )

        # Rebuild index for spatial operations
        self._rebuild_index()

        n = len(self._aircraft_index)
        if n == 0:
            self._advance_clock()
            return

        # ── Step 2: Rebuild octree (periodic) ──────────────
        if self._tick % self._settings.octree_rebuild_interval == 0 and n > 0:
            positions = self._build_positions_array()
            self._octree.rebuild(positions)

        # ── Step 3: Detect conflicts ───────────────────────
        if self._octree.root is not None:
            new_conflicts = self._conflict_detector.detect_conflicts(
                aircraft_list=list(self._aircraft.values()),
                octree=self._octree,
                sim_time=self._sim_time,
            )
            for event in new_conflicts:
                await self._event_bus.publish(EventType.CONFLICT_DETECTED.value, event)

        # ── Step 4: Resolve conflicts ──────────────────────
        self._conflict_detector.resolve_conflicts(list(self._aircraft.values()))

        # ── Step 5: Update holding patterns ────────────────
        for ac_id in list(self._aircraft.keys()):
            ac = self._aircraft.get(ac_id)
            if ac and ac.status == AircraftStatus.HOLDING:
                self._holding_mgr.update_holding(ac, self._dt)

        # ── Step 6: Update ILS approaches ──────────────────
        for ac_id in list(self._aircraft.keys()):
            ac = self._aircraft.get(ac_id)
            if ac and self._approach_mgr.is_on_approach(ac_id):
                runway = self._runways.get(ac.assigned_runway or "")
                if runway:
                    self._approach_mgr.update_approach(ac, runway, self._dt)

                    # Check go-around conditions
                    if self._approach_mgr.check_go_around(ac):
                        self._approach_mgr.execute_go_around(ac)
                        await self._event_bus.publish(
                            EventType.GO_AROUND.value,
                            Event(
                                event_type=EventType.GO_AROUND,
                                simulation_time=self._sim_time,
                                data={"aircraft_id": ac.id, "callsign": ac.callsign, "runway_id": runway.id},
                            ),
                        )

        # ── Step 7: Compute landing priorities ─────────────
        landing_candidates = [
            ac
            for ac in self._aircraft.values()
            if ac.intent == AircraftIntent.LAND
            and ac.status in (AircraftStatus.CRUISING, AircraftStatus.DESCENDING, AircraftStatus.HOLDING)
        ]
        if landing_candidates:
            # Find the best runway length for scoring
            best_rwy_len = max(r.length_m for r in self._runway_list) if self._runway_list else 3000.0
            self._priority_calc.rank_aircraft(landing_candidates, self._sim_time, best_rwy_len)

        # ── Step 8: Assign approaches / holdings ───────────
        self._assign_approaches_and_holdings()

        # ── Step 9: Update physics (vectorized) ────────────
        self._update_physics()

        # ── Step 10: Integrate positions ───────────────────
        self._integrate_positions()

        # ── Step 11: Check boundary exits / diversions ─────
        await self._check_boundary_exits()

        # ── Step 12: Cleanup landed / removed aircraft ─────
        await self._cleanup_aircraft()

        # ── Step 13: Cleanup resolved conflicts ────────────
        self._conflict_detector.cleanup_resolved(list(self._aircraft.values()), self._octree)

        # ── Step 14: Publish tick event ────────────────────
        self._update_stats()

        # ── Step 15: Periodic snapshot ─────────────────────
        if self._tick % self._settings.snapshot_interval == 0 and self._tick > 0:
            await self._event_bus.publish(
                EventType.SIMULATION_SNAPSHOT.value,
                Event(
                    event_type=EventType.SIMULATION_SNAPSHOT,
                    simulation_time=self._sim_time,
                    data={"tick": self._tick, "aircraft_count": len(self._aircraft)},
                ),
            )

        self._advance_clock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _advance_clock(self) -> None:
        self._tick += 1
        self._sim_time += self._dt

    def _rebuild_index(self) -> None:
        """Rebuild the ordered aircraft ID index, excluding REMOVED/LANDED."""
        self._aircraft_index = [
            ac_id
            for ac_id, ac in self._aircraft.items()
            if ac.status not in (AircraftStatus.REMOVED, AircraftStatus.LANDED)
        ]

    def _build_positions_array(self) -> np.ndarray:
        """Build (N,3) positions array matching self._aircraft_index order."""
        n = len(self._aircraft_index)
        if n == 0:
            return np.empty((0, 3), dtype=np.float64)
        positions = np.empty((n, 3), dtype=np.float64)
        for i, ac_id in enumerate(self._aircraft_index):
            positions[i] = self._aircraft[ac_id].position
        return positions

    def _update_physics(self) -> None:
        """Vectorized physics update for all active aircraft."""
        active = [
            self._aircraft[ac_id]
            for ac_id in self._aircraft_index
            if self._aircraft[ac_id].status not in (AircraftStatus.LANDED, AircraftStatus.REMOVED)
        ]
        if not active:
            return

        n = len(active)

        # Extract arrays
        headings = np.array([ac.heading for ac in active], dtype=np.float64)
        target_headings = np.array([ac.target_heading for ac in active], dtype=np.float64)
        bank_angles = np.array([ac.bank_angle for ac in active], dtype=np.float64)
        altitudes = np.array([ac.altitude_ft for ac in active], dtype=np.float64)
        target_altitudes = np.array([ac.target_altitude_ft for ac in active], dtype=np.float64)
        vspeeds = np.array([ac.vertical_speed_fpm for ac in active], dtype=np.float64)
        speeds = np.array([ac.speed_knots for ac in active], dtype=np.float64)
        target_speeds = np.array([ac.target_speed_knots for ac in active], dtype=np.float64)
        fuel = np.array([ac.fuel_remaining_kg for ac in active], dtype=np.float64)
        burn_rates = np.array([ac.fuel_burn_rate_kg_s for ac in active], dtype=np.float64)

        # Max climb/descent per aircraft type
        max_climb = np.array(
            [
                AircraftType(ac.aircraft_type).max_climb_rate_fpm
                if ac.aircraft_type in [t.value for t in AircraftType]
                else 3000.0
                for ac in active
            ],
            dtype=np.float64,
        )
        max_descent = np.array(
            [
                AircraftType(ac.aircraft_type).max_descent_rate_fpm
                if ac.aircraft_type in [t.value for t in AircraftType]
                else 4000.0
                for ac in active
            ],
            dtype=np.float64,
        )

        # Phase multipliers for fuel burn
        phase_mult = np.array([_FUEL_MULTIPLIER.get(ac.status, 1.0) for ac in active], dtype=np.float64)

        # Physics updates
        new_headings, new_bank = self._physics.update_headings(headings, target_headings, bank_angles)
        new_altitudes, new_vspeeds = self._physics.update_altitudes(
            altitudes, target_altitudes, vspeeds, max_climb, max_descent
        )
        new_speeds = self._physics.update_speeds(speeds, target_speeds)
        new_fuel = self._physics.update_fuel(fuel, burn_rates, phase_mult)

        # Write back
        for i, ac in enumerate(active):
            ac.heading = float(new_headings[i])
            ac.bank_angle = float(new_bank[i])
            ac.altitude_ft = float(new_altitudes[i])
            ac.vertical_speed_fpm = float(new_vspeeds[i])
            ac.speed_knots = float(new_speeds[i])
            ac.fuel_remaining_kg = float(new_fuel[i])

            # Update z-position from altitude
            ac.position[2] = ac.altitude_ft * FT_TO_KM

    def _integrate_positions(self) -> None:
        """Integrate positions for all active aircraft."""
        active = [
            self._aircraft[ac_id]
            for ac_id in self._aircraft_index
            if self._aircraft[ac_id].status not in (AircraftStatus.LANDED, AircraftStatus.REMOVED)
        ]
        if not active:
            return

        n = len(active)
        headings = np.array([ac.heading for ac in active], dtype=np.float64)
        speeds = np.array([ac.speed_knots for ac in active], dtype=np.float64)
        vspeeds = np.array([ac.vertical_speed_fpm for ac in active], dtype=np.float64)
        positions = np.array([ac.position for ac in active], dtype=np.float64)

        velocities = self._physics.compute_velocity_vectors(headings, speeds, vspeeds)
        new_positions = self._physics.integrate_positions(positions, velocities)

        for i, ac in enumerate(active):
            ac.position = new_positions[i]
            ac.velocity = velocities[i]

    def _assign_approaches_and_holdings(self) -> None:
        """Assign aircraft to approaches or holding based on distance to runway."""
        for ac in self._aircraft.values():
            if ac.intent != AircraftIntent.LAND:
                continue
            if ac.status not in (AircraftStatus.CRUISING, AircraftStatus.DESCENDING):
                continue
            if self._approach_mgr.is_on_approach(ac.id):
                continue
            if self._holding_mgr.is_holding(ac.id):
                continue

            # Find nearest runway
            nearest_rwy, dist_nm = self._nearest_runway(ac)
            if nearest_rwy is None:
                continue

            if dist_nm < _APPROACH_TRIGGER_NM:
                # Check if runway is free
                if not nearest_rwy.occupied and nearest_rwy.ils_available:
                    # Check no other aircraft on approach to this runway
                    already_approaching = any(
                        s.runway_id == nearest_rwy.id
                        for s in [
                            self._approach_mgr.get_approach_state(a_id)
                            for a_id in self._aircraft
                            if self._approach_mgr.is_on_approach(a_id)
                        ]
                        if s is not None
                    )
                    if not already_approaching:
                        self._approach_mgr.initiate_approach(ac, nearest_rwy)
                        ac.target_altitude_ft = nearest_rwy.glideslope_intercept_altitude_ft
                        ac.status = AircraftStatus.APPROACH
                        continue

                # Runway busy — assign to holding if a fix is available
                if dist_nm < _HOLDING_TRIGGER_NM:
                    # Find nearest holding fix
                    best_fix = self._nearest_holding_fix(ac)
                    if best_fix:
                        self._holding_mgr.assign_holding(ac, best_fix.id, self._sim_time)
            elif dist_nm < _HOLDING_TRIGGER_NM:
                # Start descending toward approach
                ac.status = AircraftStatus.DESCENDING
                ac.target_altitude_ft = 15000.0  # Step-down

    async def _check_boundary_exits(self) -> None:
        """Check for aircraft exiting sector or low fuel diversions."""
        to_divert: list[str] = []

        for ac_id in self._aircraft_index:
            ac = self._aircraft.get(ac_id)
            if ac is None:
                continue
            if ac.status in (AircraftStatus.LANDED, AircraftStatus.REMOVED):
                continue

            # Boundary exit check (overflights or diverted)
            if not self._sector.contains(ac.position):
                if ac.intent == AircraftIntent.OVERFLY or ac.intent == AircraftIntent.DIVERT:
                    ac.status = AircraftStatus.REMOVED
                    logger.info("Aircraft %s exited sector", ac.callsign)
                else:
                    # Landing aircraft left sector = divert
                    ac.status = AircraftStatus.DIVERTED
                    ac.intent = AircraftIntent.DIVERT
                    to_divert.append(ac_id)

            # Low fuel diversion
            if ac.fuel_remaining_kg < ac.min_fuel_kg and ac.status not in (
                AircraftStatus.APPROACH,
                AircraftStatus.LANDING,
                AircraftStatus.LANDED,
            ):
                ac.status = AircraftStatus.DIVERTED
                ac.intent = AircraftIntent.DIVERT
                to_divert.append(ac_id)

        for ac_id in to_divert:
            ac = self._aircraft.get(ac_id)
            if ac:
                # Release from holding/approach
                self._holding_mgr.release_from_holding(ac_id)
                self._approach_mgr.complete_approach(ac_id)

                self._stats.diverted_total += 1
                await self._event_bus.publish(
                    EventType.AIRCRAFT_DIVERTED.value,
                    AircraftDivertedEvent(
                        aircraft_id=ac.id,
                        callsign=ac.callsign,
                        original_destination=ac.destination,
                        divert_destination="ALTERNATE",
                        reason="FUEL" if ac.fuel_remaining_kg < ac.min_fuel_kg else "BOUNDARY",
                        fuel_remaining_kg=ac.fuel_remaining_kg,
                        simulation_time=self._sim_time,
                    ),
                )

    async def _cleanup_aircraft(self) -> None:
        """Remove landed and exited aircraft from the simulation."""
        to_remove: list[str] = []

        for ac_id, ac in self._aircraft.items():
            if ac.status == AircraftStatus.LANDED:
                # Check if approach is in TOUCHDOWN phase
                state = self._approach_mgr.get_approach_state(ac_id)
                if state and state.phase == ApproachPhase.TOUCHDOWN:
                    self._approach_mgr.complete_approach(ac_id)

                    # Free the runway
                    runway = self._runways.get(ac.assigned_runway or "")
                    if runway and runway.occupant_id == ac_id:
                        runway.occupied = False
                        runway.occupant_id = None

                    self._stats.landed_total += 1
                    await self._event_bus.publish(
                        EventType.AIRCRAFT_LANDED.value,
                        AircraftLandedEvent(
                            aircraft_id=ac.id,
                            callsign=ac.callsign,
                            runway_id=ac.assigned_runway or "",
                            holding_time_sec=(self._sim_time - ac.holding_start_time if ac.holding_start_time else 0.0),
                            fuel_remaining_kg=ac.fuel_remaining_kg,
                            priority_score=ac.priority_score,
                            simulation_time=self._sim_time,
                        ),
                    )
                    to_remove.append(ac_id)

            elif ac.status == AircraftStatus.REMOVED:
                to_remove.append(ac_id)

            elif ac.status == AircraftStatus.DIVERTED:
                to_remove.append(ac_id)

        for ac_id in to_remove:
            self._aircraft.pop(ac_id, None)

    def _update_stats(self) -> None:
        """Refresh simulation statistics."""
        self._stats.tick = self._tick
        self._stats.sim_time = self._sim_time
        self._stats.aircraft_count = len(self._aircraft)
        self._stats.active_conflicts = len(self._conflict_detector.get_active_conflicts())
        self._stats.holding_count = self._holding_mgr.total_holding
        self._stats.approach_count = self._approach_mgr.active_approaches

    def _nearest_runway(self, ac: Aircraft) -> tuple[Optional[Runway], float]:
        """Find the nearest runway to an aircraft. Returns (runway, distance_nm)."""
        best_rwy: Optional[Runway] = None
        best_dist = float("inf")

        for rwy in self._runway_list:
            dx = rwy.position[0] - ac.position[0]
            dy = rwy.position[1] - ac.position[1]
            dist_km = np.sqrt(dx * dx + dy * dy)
            dist_nm = float(dist_km / NM_TO_KM)
            if dist_nm < best_dist:
                best_dist = dist_nm
                best_rwy = rwy

        return best_rwy, best_dist

    def _nearest_holding_fix(self, ac: Aircraft) -> Optional[HoldingFix]:
        """Find nearest holding fix that isn't full."""
        best_fix: Optional[HoldingFix] = None
        best_dist = float("inf")

        for fix_id in self._holding_mgr._fixes:
            fix = self._holding_mgr.get_fix(fix_id)
            if fix is None:
                continue
            if self._holding_mgr.get_holding_count(fix_id) >= fix.max_aircraft:
                continue

            dx = fix.position[0] - ac.position[0]
            dy = fix.position[1] - ac.position[1]
            dist = float(np.sqrt(dx * dx + dy * dy))
            if dist < best_dist:
                best_dist = dist
                best_fix = fix

        return best_fix
