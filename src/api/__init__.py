"""FastAPI API layer.

Provides REST endpoints and WebSocket for real-time aircraft state.
"""

from src.api.routes import get_simulation, router, set_simulation

__all__ = [
    "router",
    "set_simulation",
    "get_simulation",
]
