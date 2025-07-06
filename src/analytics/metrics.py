"""Prometheus-compatible metrics for ATC simulation.

Exposes simulation metrics via prometheus_client for monitoring.
Integrates with the event bus to update counters and gauges in real-time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, Info

from src.events.event_bus import EventBus, get_event_bus
from src.models.events import EventType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metrics definitions
# ---------------------------------------------------------------------------

# Info
SIM_INFO = Info("atc_simulation", "ATC Simulator metadata")

# Gauges (current values)
AIRCRAFT_COUNT = Gauge("atc_aircraft_total", "Current number of active aircraft")
CONFLICT_COUNT = Gauge("atc_conflicts_active", "Number of active conflicts")
HOLDING_COUNT = Gauge("atc_holding_active", "Number of aircraft in holding patterns")
APPROACH_COUNT = Gauge("atc_approach_active", "Number of aircraft on approach")
SIM_TIME = Gauge("atc_simulation_time_seconds", "Simulation elapsed time in seconds")
SIM_TICK = Gauge("atc_simulation_tick", "Current simulation tick number")
WS_CLIENTS = Gauge("atc_websocket_clients", "Number of connected WebSocket clients")

# Counters (cumulative)
AIRCRAFT_SPAWNED = Counter("atc_aircraft_spawned_total", "Total aircraft spawned")
AIRCRAFT_LANDED = Counter("atc_aircraft_landed_total", "Total aircraft landed")
AIRCRAFT_DIVERTED = Counter("atc_aircraft_diverted_total", "Total aircraft diverted")
CONFLICTS_DETECTED = Counter("atc_conflicts_detected_total", "Total conflicts detected")
GO_AROUNDS = Counter("atc_go_arounds_total", "Total go-around events")

# Histograms
LANDING_HOLD_TIME = Histogram(
    "atc_landing_hold_time_seconds",
    "Time spent in holding before landing",
    buckets=[0, 30, 60, 120, 180, 300, 600, 900, 1800],
)
LANDING_FUEL_REMAINING = Histogram(
    "atc_landing_fuel_remaining_kg",
    "Fuel remaining at landing (kg)",
    buckets=[0, 1000, 2000, 5000, 10000, 20000, 50000],
)


class MetricsCollector:
    """Subscribes to event bus topics and updates Prometheus metrics."""

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self._bus = event_bus or get_event_bus()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Subscribe to all relevant event topics and start collecting."""
        SIM_INFO.info(
            {
                "version": "0.1.0",
                "environment": "development",
            }
        )

        topics = [
            (EventType.AIRCRAFT_SPAWNED.value, self._on_spawned),
            (EventType.AIRCRAFT_LANDED.value, self._on_landed),
            (EventType.AIRCRAFT_DIVERTED.value, self._on_diverted),
            (EventType.CONFLICT_DETECTED.value, self._on_conflict),
            (EventType.GO_AROUND.value, self._on_go_around),
        ]

        for topic, handler in topics:
            queue = await self._bus.subscribe(topic)
            task = asyncio.create_task(self._consume(queue, handler, topic))
            self._tasks.append(task)

        logger.info("Metrics collector started with %d topic subscriptions", len(topics))

    async def stop(self) -> None:
        """Cancel all consumer tasks."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("Metrics collector stopped")

    def update_gauges(
        self,
        aircraft_count: int,
        conflict_count: int,
        holding_count: int,
        approach_count: int,
        sim_time: float,
        tick: int,
    ) -> None:
        """Update gauge metrics from simulation stats (called per tick or periodically)."""
        AIRCRAFT_COUNT.set(aircraft_count)
        CONFLICT_COUNT.set(conflict_count)
        HOLDING_COUNT.set(holding_count)
        APPROACH_COUNT.set(approach_count)
        SIM_TIME.set(sim_time)
        SIM_TICK.set(tick)

    @staticmethod
    def set_ws_clients(count: int) -> None:
        """Update WebSocket client count."""
        WS_CLIENTS.set(count)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _consume(self, queue: asyncio.Queue, handler, topic: str) -> None:
        """Consume events from a queue and call handler."""
        try:
            while True:
                event = await queue.get()
                try:
                    handler(event)
                except Exception as e:
                    logger.error("Error in metrics handler for %s: %s", topic, e)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _on_spawned(event) -> None:
        AIRCRAFT_SPAWNED.inc()

    @staticmethod
    def _on_landed(event) -> None:
        AIRCRAFT_LANDED.inc()
        # Record holding time histogram
        if hasattr(event, "holding_time_sec"):
            LANDING_HOLD_TIME.observe(event.holding_time_sec)
        # Record fuel remaining histogram
        if hasattr(event, "fuel_remaining_kg"):
            LANDING_FUEL_REMAINING.observe(event.fuel_remaining_kg)

    @staticmethod
    def _on_diverted(event) -> None:
        AIRCRAFT_DIVERTED.inc()

    @staticmethod
    def _on_conflict(event) -> None:
        CONFLICTS_DETECTED.inc()

    @staticmethod
    def _on_go_around(event) -> None:
        GO_AROUNDS.inc()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
