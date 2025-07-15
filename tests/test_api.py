"""Tests for FastAPI REST and WebSocket endpoints."""

import asyncio

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.routes import set_simulation
from src.config import Settings, reset_settings
from src.engine.holding import HoldingFix
from src.engine.simulation import Simulation
from src.main import create_app
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
    return Settings(simulation_tick_rate=20, max_aircraft=50)


@pytest.fixture
def simulation(sector, runways, holding_fixes, settings):
    sim = Simulation(
        sector=sector,
        runways=runways,
        holding_fixes=holding_fixes,
        settings=settings,
        spawn_seed=42,
    )
    set_simulation(sim)
    return sim


@pytest.fixture
def app(simulation):
    """Create app without lifespan (we manage simulation manually)."""
    from fastapi import FastAPI
    from src.api.routes import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "simulation_running" in data
        assert "timestamp" in data


class TestAircraftEndpoints:
    @pytest.mark.asyncio
    async def test_list_aircraft_empty(self, client, simulation):
        resp = await client.get("/api/aircraft")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["aircraft"] == []

    @pytest.mark.asyncio
    async def test_get_aircraft_not_found(self, client, simulation):
        resp = await client.get("/api/aircraft/nonexistent")
        assert resp.status_code == 404


class TestStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats(self, client, simulation):
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "tick" in data
        assert "sim_time" in data
        assert "aircraft_count" in data
        assert "running" in data


class TestRunwaysEndpoint:
    @pytest.mark.asyncio
    async def test_runways(self, client, simulation):
        resp = await client.get("/api/runways")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["runways"]) == 1
        assert data["runways"][0]["id"] == "RWY_01"


class TestSectorEndpoint:
    @pytest.mark.asyncio
    async def test_sector(self, client, simulation):
        resp = await client.get("/api/sector")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "TEST"
        assert data["name"] == "Test Sector"


class TestSimulationControl:
    @pytest.mark.asyncio
    async def test_start_simulation(self, client, simulation):
        resp = await client.post("/api/simulation/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"

        # Wait a moment then stop
        await asyncio.sleep(0.3)
        resp = await client.post("/api/simulation/stop")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stop_already_stopped(self, client, simulation):
        resp = await client.post("/api/simulation/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_stopped"
