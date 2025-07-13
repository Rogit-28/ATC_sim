"""Tests for the aircraft spawner."""

import numpy as np
import pytest

from src.engine.spawner import AircraftSpawner, SpawnConfig
from src.models.aircraft import Aircraft, AircraftIntent, AircraftStatus
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
def spawner(sector):
    config = SpawnConfig(
        spawn_rate_per_minute=10.0,
        max_aircraft=100,
        seed=42,
    )
    return AircraftSpawner(config=config, sector=sector)


class TestSpawnerInit:
    def test_creation(self, spawner):
        assert spawner is not None

    def test_deterministic_seed(self, sector):
        config = SpawnConfig(spawn_rate_per_minute=5.0, max_aircraft=50, seed=12345)
        s1 = AircraftSpawner(config=config, sector=sector)
        s2 = AircraftSpawner(config=config, sector=sector)

        # Both should produce same first aircraft
        ac1 = s1.spawn_aircraft(sim_time=0.0)
        ac2 = s2.spawn_aircraft(sim_time=0.0)
        assert ac1.callsign == ac2.callsign
        assert ac1.aircraft_type == ac2.aircraft_type


class TestSpawnAircraft:
    def test_spawns_valid_aircraft(self, spawner):
        ac = spawner.spawn_aircraft(sim_time=0.0)
        assert isinstance(ac, Aircraft)
        assert ac.id != ""
        assert ac.callsign != ""
        assert ac.aircraft_type in ["B737", "B747", "B777", "B787", "A320", "A330", "A350", "A380", "CRJ9", "E190"]

    def test_aircraft_in_sector_boundary(self, spawner, sector):
        """Spawned aircraft should be near the sector boundary."""
        for i in range(20):
            ac = spawner.spawn_aircraft(sim_time=float(i))
            # Position should be within or very near sector bounds
            pos = ac.position
            # At least one coordinate should be near a boundary
            near_boundary = (
                abs(pos[0] - sector.bounds_min[0]) < 5.0
                or abs(pos[0] - sector.bounds_max[0]) < 5.0
                or abs(pos[1] - sector.bounds_min[1]) < 5.0
                or abs(pos[1] - sector.bounds_max[1]) < 5.0
            )
            assert near_boundary, f"Aircraft at {pos} not near boundary"

    def test_has_valid_intent(self, spawner):
        intents_seen = set()
        for i in range(100):
            ac = spawner.spawn_aircraft(sim_time=float(i))
            intents_seen.add(ac.intent)
        # Should see at least LAND intent
        assert AircraftIntent.LAND in intents_seen

    def test_unique_ids(self, spawner):
        ids = set()
        for i in range(50):
            ac = spawner.spawn_aircraft(sim_time=float(i))
            assert ac.id not in ids
            ids.add(ac.id)

    def test_has_valid_fuel(self, spawner):
        for i in range(10):
            ac = spawner.spawn_aircraft(sim_time=float(i))
            assert ac.fuel_remaining_kg > 0
            assert ac.fuel_burn_rate_kg_s > 0
            assert ac.min_fuel_kg > 0


class TestShouldSpawn:
    def test_spawns_with_time(self, spawner):
        # Over enough time, should_spawn should return True at least once
        # With seed=42 and rate=10/min, first interval ~14.4s, so need >290 ticks
        spawned = False
        for _ in range(600):
            if spawner.should_spawn(dt=0.05, current_count=0):
                spawned = True
                break
        assert spawned

    def test_respects_max_aircraft(self, spawner):
        # At max capacity, should not spawn
        result = spawner.should_spawn(dt=0.05, current_count=100)
        assert result is False
