"""Tests for the main simulation loop."""

import asyncio

import numpy as np
import pytest

from src.config import Settings, reset_settings
from src.engine.holding import HoldingFix
from src.engine.simulation import Simulation, SimulationStats
from src.models.runway import Runway
from src.models.sector import Sector


@pytest.fixture
def sector():
    return Sector(
        id="TEST",
        name="Test Sector",
        bounds_min=np.array([-100.0, -100.0, 0.0], dtype=np.float64),
        bounds_max=np.array([100.0, 100.0, 15.0], dtype=np.float64),
    )


@pytest.fixture
def runways():
    return [
        Runway(
            id="RWY_01",
            airport_icao="TEST",
            heading=10.0,
            length_m=3000.0,
            position=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        ),
    ]


@pytest.fixture
def holding_fixes():
    return [
        HoldingFix(
            id="FIX01",
            position=np.array([30.0, 30.0, 0.0], dtype=np.float64),
            inbound_heading=180.0,
        ),
    ]


@pytest.fixture
def settings():
    reset_settings()
    return Settings(
        simulation_tick_rate=20,
        max_aircraft=50,
        spawn_rate_per_minute=600.0,  # Very high rate so spawns happen quickly in tests
    )


@pytest.fixture
def simulation(sector, runways, holding_fixes, settings):
    return Simulation(
        sector=sector,
        runways=runways,
        holding_fixes=holding_fixes,
        settings=settings,
        spawn_seed=42,
    )


class TestSimulationInit:
    def test_creation(self, simulation):
        assert simulation is not None
        assert not simulation.running
        assert simulation.tick_count == 0
        assert simulation.sim_time == pytest.approx(0.0)

    def test_stats_initial(self, simulation):
        stats = simulation.stats
        assert isinstance(stats, SimulationStats)
        assert stats.tick == 0
        assert stats.aircraft_count == 0

    def test_empty_aircraft(self, simulation):
        assert len(simulation.aircraft) == 0
        assert simulation.get_aircraft_list() == []


class TestSimulationRun:
    @pytest.mark.asyncio
    async def test_start_stop(self, simulation):
        """Simulation should start and stop cleanly."""

        # Run for a short time
        async def run_briefly():
            task = asyncio.create_task(simulation.start())
            await asyncio.sleep(0.3)  # 6 ticks at 20Hz
            simulation.stop()
            await task

        await asyncio.wait_for(run_briefly(), timeout=5.0)
        assert not simulation.running
        assert simulation.tick_count > 0

    @pytest.mark.asyncio
    async def test_spawns_aircraft(self, simulation):
        """After running, aircraft should have been spawned."""
        task = asyncio.create_task(simulation.start())
        await asyncio.sleep(1.0)
        simulation.stop()
        await task

        assert simulation.stats.spawned_total > 0

    @pytest.mark.asyncio
    async def test_sim_time_advances(self, simulation):
        """Simulation time should advance."""
        task = asyncio.create_task(simulation.start())
        await asyncio.sleep(0.5)
        simulation.stop()
        await task

        assert simulation.sim_time > 0.0

    @pytest.mark.asyncio
    async def test_get_runway(self, simulation):
        rwy = simulation.get_runway("RWY_01")
        assert rwy is not None
        assert rwy.id == "RWY_01"

        none_rwy = simulation.get_runway("NOPE")
        assert none_rwy is None
