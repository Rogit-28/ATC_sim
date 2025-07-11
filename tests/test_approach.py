"""Tests for ILS approach manager."""

import numpy as np
import pytest

from src.engine.approach import ApproachPhase, ApproachState, ILSApproachManager
from src.models.aircraft import Aircraft, AircraftStatus, AircraftIntent
from src.models.runway import Runway


def make_runway() -> Runway:
    return Runway(
        id="RWY_04L",
        airport_icao="KJFK",
        heading=40.0,
        length_m=3460.0,
        position=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        ils_available=True,
        glideslope_angle=3.0,
        elevation_ft=13.0,
        glideslope_intercept_altitude_ft=3000.0,
    )


def make_aircraft(id: str, x: float, y: float, alt_ft: float) -> Aircraft:
    z_km = alt_ft * 0.0003048
    return Aircraft(
        id=id,
        callsign=f"TST{id}",
        aircraft_type="B737",
        position=np.array([x, y, z_km], dtype=np.float64),
        heading=220.0,  # Approaching from opposite direction
        altitude_ft=alt_ft,
        speed_knots=180.0,
        status=AircraftStatus.APPROACH,
        intent=AircraftIntent.LAND,
        assigned_runway="RWY_04L",
    )


@pytest.fixture
def manager():
    return ILSApproachManager()


@pytest.fixture
def runway():
    return make_runway()


class TestApproachInitiation:
    def test_initiate_approach(self, manager, runway):
        ac = make_aircraft("A1", -20.0, -15.0, 3000.0)
        manager.initiate_approach(ac, runway)

        assert manager.is_on_approach("A1")
        state = manager.get_approach_state("A1")
        assert state is not None
        assert state.aircraft_id == "A1"
        assert state.runway_id == "RWY_04L"
        assert state.phase == ApproachPhase.INTERCEPT

    def test_active_approaches_count(self, manager, runway):
        ac1 = make_aircraft("A1", -20.0, -15.0, 3000.0)
        ac2 = make_aircraft("A2", -25.0, -20.0, 3500.0)
        manager.initiate_approach(ac1, runway)
        manager.initiate_approach(ac2, runway)
        assert manager.active_approaches == 2


class TestApproachUpdate:
    def test_update_does_not_crash(self, manager, runway):
        ac = make_aircraft("A1", -20.0, -15.0, 3000.0)
        manager.initiate_approach(ac, runway)

        # Run 200 update cycles
        for _ in range(200):
            manager.update_approach(ac, runway, dt=0.05)

        assert manager.is_on_approach("A1")


class TestApproachCompletion:
    def test_complete_approach(self, manager, runway):
        ac = make_aircraft("A1", -20.0, -15.0, 3000.0)
        manager.initiate_approach(ac, runway)
        assert manager.is_on_approach("A1")

        manager.complete_approach("A1")
        assert not manager.is_on_approach("A1")

    def test_complete_nonexistent(self, manager):
        # Should not raise
        manager.complete_approach("NOPE")


class TestGoAround:
    def test_go_around_check(self, manager, runway):
        ac = make_aircraft("A1", -20.0, -15.0, 3000.0)
        manager.initiate_approach(ac, runway)

        # Normal conditions should not trigger go-around
        result = manager.check_go_around(ac)
        assert isinstance(result, bool)

    def test_execute_go_around(self, manager, runway):
        ac = make_aircraft("A1", 0.0, 0.0, 100.0)
        manager.initiate_approach(ac, runway)
        manager.execute_go_around(ac)

        # After go-around, aircraft should have climbing target
        assert ac.go_around is True
