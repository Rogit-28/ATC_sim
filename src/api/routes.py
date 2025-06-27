"""FastAPI REST and WebSocket endpoints for ATC simulation.

REST endpoints:
    GET  /api/health          - Health check
    GET  /api/aircraft        - List all aircraft
    GET  /api/aircraft/{id}   - Single aircraft detail
    GET  /api/stats           - Simulation statistics
    GET  /api/runways         - Runway status
    GET  /api/conflicts       - Active conflicts
    GET  /api/sector          - Sector info
    POST /api/simulation/start - Start simulation
    POST /api/simulation/stop  - Stop simulation

WebSocket:
    WS   /ws                  - Real-time aircraft state (msgpack binary)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import msgpack
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Simulation reference — set by main.py during lifespan
# ---------------------------------------------------------------------------

_simulation: Any = None
_sim_task: Optional[asyncio.Task] = None


def set_simulation(sim: Any) -> None:
    """Register the simulation instance for API access."""
    global _simulation
    _simulation = sim


def get_simulation() -> Any:
    """Get the current simulation instance."""
    return _simulation


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    sim = get_simulation()
    return {
        "status": "ok",
        "simulation_running": sim.running if sim else False,
        "timestamp": time.time(),
    }


@router.get("/api/aircraft")
async def list_aircraft() -> JSONResponse:
    """List all active aircraft."""
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    aircraft_list = [ac.to_dict() for ac in sim.get_aircraft_list()]
    return JSONResponse(
        {
            "count": len(aircraft_list),
            "aircraft": aircraft_list,
            "sim_time": round(sim.sim_time, 3),
        }
    )


@router.get("/api/aircraft/{aircraft_id}")
async def get_aircraft(aircraft_id: str) -> JSONResponse:
    """Get single aircraft detail."""
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    ac = sim.aircraft.get(aircraft_id)
    if ac is None:
        return JSONResponse({"error": f"Aircraft {aircraft_id} not found"}, status_code=404)

    return JSONResponse(ac.to_dict())


@router.get("/api/stats")
async def get_stats() -> JSONResponse:
    """Get simulation statistics."""
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    stats = sim.stats
    return JSONResponse(
        {
            "tick": stats.tick,
            "sim_time": round(stats.sim_time, 3),
            "aircraft_count": stats.aircraft_count,
            "active_conflicts": stats.active_conflicts,
            "holding_count": stats.holding_count,
            "approach_count": stats.approach_count,
            "landed_total": stats.landed_total,
            "diverted_total": stats.diverted_total,
            "spawned_total": stats.spawned_total,
            "running": sim.running,
        }
    )


@router.get("/api/runways")
async def list_runways() -> JSONResponse:
    """List all runways and their status."""
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    runways = [rwy.to_dict() for rwy in sim._runways.values()]
    return JSONResponse(
        {
            "count": len(runways),
            "runways": runways,
        }
    )


@router.get("/api/conflicts")
async def list_conflicts() -> JSONResponse:
    """List active conflicts."""
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    conflicts = sim._conflict_detector.get_active_conflicts()
    conflict_list = []
    for c in conflicts:
        conflict_list.append(
            {
                "aircraft_1": c.aircraft_1_id,
                "aircraft_2": c.aircraft_2_id,
                "horizontal_distance_nm": round(c.horizontal_distance_nm, 2),
                "vertical_distance_ft": round(c.vertical_distance_ft, 1),
                "detected_at": round(c.detected_at, 3),
            }
        )

    return JSONResponse(
        {
            "count": len(conflict_list),
            "conflicts": conflict_list,
        }
    )


@router.get("/api/sector")
async def get_sector() -> JSONResponse:
    """Get sector information."""
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    return JSONResponse(sim._sector.to_dict())


@router.post("/api/simulation/start")
async def start_simulation() -> JSONResponse:
    """Start the simulation loop."""
    global _sim_task
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    if sim.running:
        return JSONResponse({"status": "already_running"})

    _sim_task = asyncio.create_task(sim.start())
    logger.info("Simulation started via API")
    return JSONResponse({"status": "started"})


@router.post("/api/simulation/stop")
async def stop_simulation() -> JSONResponse:
    """Stop the simulation loop."""
    global _sim_task
    sim = get_simulation()
    if sim is None:
        return JSONResponse({"error": "Simulation not initialized"}, status_code=503)

    if not sim.running:
        return JSONResponse({"status": "already_stopped"})

    sim.stop()

    # Wait for the sim task to finish gracefully
    if _sim_task is not None:
        try:
            await asyncio.wait_for(_sim_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Simulation task did not stop within 5s")
        except Exception:
            pass
        _sim_task = None

    logger.info("Simulation stopped via API")
    return JSONResponse({"status": "stopped"})


# ---------------------------------------------------------------------------
# WebSocket — real-time aircraft state
# ---------------------------------------------------------------------------

# Track connected clients for stats
_ws_clients: set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time aircraft positions.

    Sends msgpack-encoded binary frames at ~10 Hz (every 100ms).
    Frame format:
        {
            "t": simulation_time,
            "k": tick_count,
            "n": aircraft_count,
            "a": [
                {"id": ..., "cs": ..., "p": [x,y,z], "h": heading,
                 "a": altitude_ft, "s": speed_knots, "st": status, "em": is_emergency},
                ...
            ],
            "s": {  # stats
                "conflicts": N,
                "holding": N,
                "approach": N,
                "landed": N,
                "diverted": N,
            }
        }
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info("WebSocket client connected (%d total)", len(_ws_clients))

    try:
        while True:
            sim = get_simulation()
            if sim is None or not sim.running:
                # Wait until simulation starts
                await asyncio.sleep(0.5)
                continue

            # Build frame
            aircraft_data = [ac.to_msgpack() for ac in sim.get_aircraft_list()]
            stats = sim.stats

            frame = {
                "t": round(sim.sim_time, 3),
                "k": sim.tick_count,
                "n": len(aircraft_data),
                "a": aircraft_data,
                "s": {
                    "conflicts": stats.active_conflicts,
                    "holding": stats.holding_count,
                    "approach": stats.approach_count,
                    "landed": stats.landed_total,
                    "diverted": stats.diverted_total,
                },
            }

            # Send as msgpack binary
            packed = msgpack.packb(frame, use_bin_type=True)
            await websocket.send_bytes(packed)

            # 10 Hz update rate for WebSocket
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        _ws_clients.discard(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(_ws_clients))


@router.get("/api/ws/clients")
async def ws_client_count() -> dict:
    """Get WebSocket client count."""
    return {"connected_clients": len(_ws_clients)}
