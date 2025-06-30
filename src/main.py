"""ATC Simulator — Application entrypoint.

Usage:
    python -m src.main          # Start the server
    python -m src.main --help   # Show options

Starts FastAPI with uvicorn, initializes the simulation engine,
and serves the 3D visualization client from ./client/.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router, set_simulation
from src.config import get_settings
from src.engine.holding import HoldingFix
from src.engine.simulation import Simulation
from src.models.runway import Runway
from src.models.sector import Sector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default scenario — KJFK-inspired sector
# ---------------------------------------------------------------------------

_DEFAULT_SECTOR = Sector(
    id="KJFK_APP",
    name="JFK Approach",
    bounds_min=np.array([-100.0, -100.0, 0.0], dtype=np.float64),
    bounds_max=np.array([100.0, 100.0, 15.0], dtype=np.float64),
    capacity=200,
)

_DEFAULT_RUNWAYS = [
    Runway(
        id="RWY_04L",
        airport_icao="KJFK",
        heading=40.0,
        length_m=3460.0,
        position=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        ils_available=True,
        glideslope_angle=3.0,
        localizer_width_deg=2.5,
        elevation_ft=13.0,
        glideslope_intercept_altitude_ft=3000.0,
        decision_altitude_ft=200.0,
    ),
    Runway(
        id="RWY_13R",
        airport_icao="KJFK",
        heading=130.0,
        length_m=3048.0,
        position=np.array([1.5, -0.5, 0.0], dtype=np.float64),
        ils_available=True,
        glideslope_angle=3.0,
        localizer_width_deg=2.5,
        elevation_ft=13.0,
        glideslope_intercept_altitude_ft=3000.0,
        decision_altitude_ft=200.0,
    ),
    Runway(
        id="RWY_22R",
        airport_icao="KJFK",
        heading=220.0,
        length_m=2560.0,
        position=np.array([-0.5, 1.0, 0.0], dtype=np.float64),
        ils_available=True,
        glideslope_angle=3.0,
        localizer_width_deg=2.5,
        elevation_ft=13.0,
        glideslope_intercept_altitude_ft=3000.0,
        decision_altitude_ft=200.0,
    ),
    Runway(
        id="RWY_31L",
        airport_icao="KJFK",
        heading=310.0,
        length_m=4423.0,
        position=np.array([-1.0, 0.5, 0.0], dtype=np.float64),
        ils_available=True,
        glideslope_angle=3.0,
        localizer_width_deg=2.5,
        elevation_ft=13.0,
        glideslope_intercept_altitude_ft=3000.0,
        decision_altitude_ft=200.0,
    ),
]

_DEFAULT_HOLDING_FIXES = [
    HoldingFix(
        id="CAMRN",
        position=np.array([40.0, 30.0, 0.0], dtype=np.float64),
        inbound_heading=220.0,
        altitude_ft=10000.0,
        max_aircraft=8,
    ),
    HoldingFix(
        id="LENDY",
        position=np.array([-35.0, 25.0, 0.0], dtype=np.float64),
        inbound_heading=130.0,
        altitude_ft=11000.0,
        max_aircraft=8,
    ),
    HoldingFix(
        id="PARCH",
        position=np.array([20.0, -40.0, 0.0], dtype=np.float64),
        inbound_heading=310.0,
        altitude_ft=9000.0,
        max_aircraft=6,
    ),
    HoldingFix(
        id="ROBER",
        position=np.array([-30.0, -35.0, 0.0], dtype=np.float64),
        inbound_heading=40.0,
        altitude_ft=12000.0,
        max_aircraft=6,
    ),
]


# ---------------------------------------------------------------------------
# Lifespan — start/stop simulation with the server
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize and start simulation on startup."""
    settings = get_settings()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("ATC Simulator starting up...")
    logger.info("Environment: %s", settings.environment)
    logger.info("Tick rate: %d Hz", settings.simulation_tick_rate)
    logger.info("Max aircraft: %d", settings.max_aircraft)

    # Create simulation
    sim = Simulation(
        sector=_DEFAULT_SECTOR,
        runways=_DEFAULT_RUNWAYS,
        holding_fixes=_DEFAULT_HOLDING_FIXES,
        settings=settings,
        spawn_seed=42,
    )

    # Register with API routes
    set_simulation(sim)

    # Auto-start simulation
    sim_task = asyncio.create_task(sim.start())
    logger.info("Simulation auto-started")

    yield

    # Shutdown
    logger.info("ATC Simulator shutting down...")
    sim.stop()
    try:
        await asyncio.wait_for(sim_task, timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("Simulation task did not stop within 5s, cancelling")
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass

    logger.info("ATC Simulator stopped")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="ATC Simulator",
        description="Air Traffic Control simulation with 3D visualization",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(router)

    # Serve static client files
    client_dir = Path(__file__).parent.parent / "client"
    if client_dir.exists():
        app.mount("/", StaticFiles(directory=str(client_dir), html=True), name="client")
        logger.info("Serving static files from %s", client_dir)
    else:
        logger.warning("Client directory not found at %s", client_dir)

    return app


# Create the app instance (used by uvicorn)
app = create_app()

# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug_mode,
        log_level=settings.log_level.lower(),
    )
