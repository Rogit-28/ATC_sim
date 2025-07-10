"""Tests for the holding pattern manager."""

import numpy as np
import pytest

from src.engine.holding import (
    EntryType,
    HoldingFix,
    HoldingPatternManager,
    HoldingPhase,
)
from src.engine.physics import NM_TO_KM
from src.models.aircraft import Aircraft, AircraftStatus


def make_aircraft(id: str, x: float = 0.0, y: float = 0.0, heading: float = 0.0) -> Aircraft:
    return Aircraft(
        id=id,
        callsign=f"TST{id}",
        aircraft_type="B737",
        position=np.array([x, y, 3.0], dtype=np.float64),
        heading=heading,
        target_heading=heading,
        altitude_ft=10000.0,
        speed_knots=230.0,
        status=AircraftStatus.CRUISING,
    )


@pytest.fixture
def fix():
    return HoldingFix(
        id="FIX01",
        position=np.array([20.0, 20.0, 0.0], dtype=np.float64),
        inbound_heading=180.0,
        altitude_ft=10000.0,
        max_aircraft=6,
    )


@pytest.fixture
def manager(fix):
    mgr = HoldingPatternManager()
    mgr.register_fix(fix)
    return mgr


class TestHoldingFixRegistration:
    def test_register_fix(self, manager, fix):
        assert manager.get_fix("FIX01") is not None

    def test_get_nonexistent_fix(self, manager):
        assert manager.get_fix("NOPE") is None


class TestHoldingAssignment:
    def test_assign_aircraft(self, manager, fix):
        ac = make_aircraft("A1", 18.0, 18.0, heading=0.0)
        manager.assign_holding(ac, "FIX01", sim_time=0.0)
        assert manager.is_holding("A1")
        assert ac.status == AircraftStatus.HOLDING
        assert ac.holding_fix == "FIX01"

    def test_holding_count(self, manager, fix):
        ac1 = make_aircraft("A1", 18.0, 18.0)
        ac2 = make_aircraft("A2", 22.0, 22.0)
        manager.assign_holding(ac1, "FIX01", sim_time=0.0)
        manager.assign_holding(ac2, "FIX01", sim_time=1.0)
        assert manager.get_holding_count("FIX01") == 2
        assert manager.total_holding == 2

    def test_max_aircraft_respected(self, manager, fix):
        # Fill up the fix
        for i in range(6):
            ac = make_aircraft(f"A{i}", float(i), float(i))
            manager.assign_holding(ac, "FIX01", sim_time=float(i))

        assert manager.get_holding_count("FIX01") == 6

    def test_release_from_holding(self, manager, fix):
        ac = make_aircraft("A1", 18.0, 18.0)
        manager.assign_holding(ac, "FIX01", sim_time=0.0)
        assert manager.is_holding("A1")

        manager.release_from_holding("A1")
        assert not manager.is_holding("A1")


class TestEntryType:
    def test_direct_entry(self, manager, fix):
        # Aircraft heading roughly opposite to inbound course
        ac = make_aircraft("A1", 20.0, 25.0, heading=180.0)
        entry = manager.determine_entry_type(ac, fix)
        assert isinstance(entry, EntryType)

    def test_entry_type_is_valid(self, manager, fix):
        for heading in range(0, 360, 30):
            ac = make_aircraft(f"A_{heading}", 20.0, 25.0, heading=float(heading))
            entry = manager.determine_entry_type(ac, fix)
            assert entry in (EntryType.DIRECT, EntryType.TEARDROP, EntryType.PARALLEL)


class TestHoldingUpdate:
    def test_update_does_not_crash(self, manager, fix):
        ac = make_aircraft("A1", 20.0, 20.0, heading=0.0)
        manager.assign_holding(ac, "FIX01", sim_time=0.0)

        # Run several updates
        for _ in range(100):
            manager.update_holding(ac, dt=0.05)

        # Aircraft should still be in holding
        assert manager.is_holding("A1")
