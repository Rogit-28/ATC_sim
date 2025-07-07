"""Simulation replay — recorder and player.

Records simulation snapshots to PostgreSQL and plays them back
at configurable speed. Uses msgpack for efficient serialization.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import msgpack

from src.events.event_bus import EventBus, get_event_bus
from src.models.events import EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot frame
# ---------------------------------------------------------------------------


@dataclass
class ReplayFrame:
    """Single snapshot of simulation state for replay."""

    tick: int
    sim_time: float
    timestamp: float  # Wall-clock time of capture
    aircraft_data: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        """Serialize to msgpack bytes."""
        return msgpack.packb(
            {
                "tick": self.tick,
                "sim_time": self.sim_time,
                "timestamp": self.timestamp,
                "aircraft": self.aircraft_data,
                "stats": self.stats,
            },
            use_bin_type=True,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "ReplayFrame":
        """Deserialize from msgpack bytes."""
        d = msgpack.unpackb(data, raw=False)
        return cls(
            tick=d["tick"],
            sim_time=d["sim_time"],
            timestamp=d["timestamp"],
            aircraft_data=d.get("aircraft", []),
            stats=d.get("stats", {}),
        )


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class ReplayRecorder:
    """Records simulation frames at a configurable interval.

    Stores frames in memory with optional flush to database.
    """

    def __init__(
        self,
        capture_interval: int = 20,  # Every N ticks (1 second at 20Hz)
        max_memory_frames: int = 3600,  # ~1 hour at 1 fps
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._interval = capture_interval
        self._max_frames = max_memory_frames
        self._bus = event_bus or get_event_bus()
        self._frames: list[ReplayFrame] = []
        self._recording = False
        self._tick_count = 0
        self._task: Optional[asyncio.Task] = None

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> list[ReplayFrame]:
        return self._frames

    def start_recording(self) -> None:
        """Begin recording frames."""
        self._recording = True
        self._tick_count = 0
        logger.info("Replay recording started (interval=%d ticks)", self._interval)

    def stop_recording(self) -> None:
        """Stop recording frames."""
        self._recording = False
        logger.info("Replay recording stopped (%d frames captured)", len(self._frames))

    def capture_frame(self, tick: int, sim_time: float, aircraft_list: list, stats: dict) -> None:
        """Capture a single frame if recording and interval reached."""
        if not self._recording:
            return

        self._tick_count += 1
        if self._tick_count % self._interval != 0:
            return

        frame = ReplayFrame(
            tick=tick,
            sim_time=sim_time,
            timestamp=time.time(),
            aircraft_data=[ac.to_msgpack() for ac in aircraft_list],
            stats=stats,
        )
        self._frames.append(frame)

        # Enforce memory limit
        if len(self._frames) > self._max_frames:
            self._frames.pop(0)

    def clear(self) -> None:
        """Clear all recorded frames."""
        self._frames.clear()
        self._tick_count = 0

    def export_bytes(self) -> bytes:
        """Export all frames as a single msgpack blob."""
        frames_data = [f.to_bytes() for f in self._frames]
        return msgpack.packb(
            {
                "version": 1,
                "frame_count": len(frames_data),
                "frames": frames_data,
            },
            use_bin_type=True,
        )

    @classmethod
    def import_bytes(cls, data: bytes) -> list[ReplayFrame]:
        """Import frames from a msgpack blob."""
        d = msgpack.unpackb(data, raw=False)
        return [ReplayFrame.from_bytes(fb) for fb in d.get("frames", [])]


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------


class ReplayPlayer:
    """Plays back recorded frames with speed control.

    Emits frames via callback at the original timing (adjustable).
    """

    def __init__(self) -> None:
        self._frames: list[ReplayFrame] = []
        self._playing = False
        self._paused = False
        self._speed: float = 1.0
        self._current_index: int = 0
        self._on_frame: Optional[Any] = None
        self._task: Optional[asyncio.Task] = None

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def total_frames(self) -> int:
        return len(self._frames)

    @property
    def progress(self) -> float:
        """Playback progress as 0.0 to 1.0."""
        if not self._frames:
            return 0.0
        return self._current_index / max(1, len(self._frames) - 1)

    def load_frames(self, frames: list[ReplayFrame]) -> None:
        """Load frames for playback."""
        self._frames = frames
        self._current_index = 0
        logger.info("Replay player loaded %d frames", len(frames))

    def on_frame(self, callback) -> None:
        """Register callback for each played frame."""
        self._on_frame = callback

    def set_speed(self, speed: float) -> None:
        """Set playback speed multiplier (0.25x to 10x)."""
        self._speed = max(0.25, min(10.0, speed))

    async def play(self) -> None:
        """Start playback from current position."""
        if not self._frames:
            logger.warning("No frames loaded for playback")
            return

        self._playing = True
        self._paused = False
        logger.info("Replay playback started at %.1fx speed", self._speed)

        try:
            while self._playing and self._current_index < len(self._frames):
                if self._paused:
                    await asyncio.sleep(0.1)
                    continue

                frame = self._frames[self._current_index]

                if self._on_frame:
                    self._on_frame(frame)

                # Calculate delay to next frame
                if self._current_index + 1 < len(self._frames):
                    next_frame = self._frames[self._current_index + 1]
                    dt = (next_frame.sim_time - frame.sim_time) / self._speed
                    if dt > 0:
                        await asyncio.sleep(dt)

                self._current_index += 1

        finally:
            self._playing = False
            logger.info("Replay playback finished at frame %d/%d", self._current_index, len(self._frames))

    def pause(self) -> None:
        """Pause playback."""
        self._paused = True

    def resume(self) -> None:
        """Resume playback."""
        self._paused = False

    def stop(self) -> None:
        """Stop playback."""
        self._playing = False

    def seek(self, index: int) -> None:
        """Seek to a specific frame index."""
        self._current_index = max(0, min(index, len(self._frames) - 1))

    def seek_percent(self, percent: float) -> None:
        """Seek to a percentage of total frames (0.0 to 1.0)."""
        index = int(percent * max(0, len(self._frames) - 1))
        self.seek(index)
