import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class EventBus:
    """In-process async pub/sub event bus.

    Topics are string identifiers. Subscribers get an asyncio.Queue
    that receives copies of published events. Bounded queues with
    drop-oldest backpressure.
    """

    # Known topics (for documentation; any string works)
    TOPICS = [
        "aircraft.spawned",
        "aircraft.landed",
        "aircraft.diverted",
        "aircraft.removed",
        "conflict.detected",
        "conflict.resolved",
        "sector.handoff",
        "holding.entered",
        "holding.exited",
        "approach.started",
        "approach.go_around",
        "simulation.started",
        "simulation.stopped",
        "simulation.tick_complete",
        "simulation.snapshot",
    ]

    def __init__(self, max_queue_size: int = 1000):
        self._max_queue_size = max_queue_size
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, event: Any) -> int:
        """Publish event to all subscribers of a topic.

        Non-blocking. If a subscriber's queue is full, drop the oldest event.
        Returns number of subscribers that received the event.
        """
        async with self._lock:
            subscribers = self._subscribers.get(topic, [])
            count = 0

            for queue in subscribers:
                try:
                    if queue.full():
                        # Drop oldest event (backpressure)
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    queue.put_nowait(event)
                    count += 1
                except asyncio.QueueFull:
                    # Shouldn't happen after get_nowait, but handle gracefully
                    logger.warning(f"Failed to publish to queue for topic {topic}")

            return count

    async def subscribe(self, topic: str) -> asyncio.Queue:
        """Subscribe to a topic. Returns a queue to consume events from.

        Usage:
            queue = await bus.subscribe("aircraft.landed")
            while True:
                event = await queue.get()
                process(event)
        """
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers[topic].append(queue)
        return queue

    async def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber's queue from a topic."""
        async with self._lock:
            if topic in self._subscribers:
                try:
                    self._subscribers[topic].remove(queue)
                except ValueError:
                    logger.warning(f"Queue not found in subscribers for topic {topic}")

    async def subscribe_iter(self, topic: str) -> AsyncIterator[Any]:
        """Subscribe and yield events as an async iterator.

        Usage:
            async for event in bus.subscribe_iter("aircraft.landed"):
                process(event)
        """
        queue = await self.subscribe(topic)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            await self.unsubscribe(topic, queue)

    async def publish_many(self, topic: str, events: list[Any]) -> None:
        """Publish multiple events to a topic."""
        for event in events:
            await self.publish(topic, event)

    @property
    def subscriber_count(self) -> dict[str, int]:
        """Return count of subscribers per topic."""
        return {topic: len(subs) for topic, subs in self._subscribers.items()}

    async def clear(self) -> None:
        """Remove all subscribers (for shutdown)."""
        async with self._lock:
            self._subscribers.clear()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus() -> None:
    """Reset event bus (for testing)."""
    global _bus
    _bus = None
