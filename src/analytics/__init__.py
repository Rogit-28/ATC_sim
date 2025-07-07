"""Analytics and metrics.

Provides Prometheus-compatible metrics collection for the ATC simulation.
"""

from src.analytics.metrics import (
    MetricsCollector,
    get_metrics_collector,
)

__all__ = [
    "MetricsCollector",
    "get_metrics_collector",
]
