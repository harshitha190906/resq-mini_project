# app/services/dv_service.py
"""Distance‑Vector routing service.
Provides a simple wrapper around :class:`app.algorithms.distance_vector.DistanceVectorRouter`
so that the routing tables can be generated on demand and exposed via an API.
"""

from __future__ import annotations

from typing import Dict, Any

from app.algorithms.distance_vector import DistanceVectorRouter
from app.algorithms.network_topology import build_sample_network, EmergencyNetwork

class DistanceVectorService:
    """Singleton‑style service that holds the latest routing tables.

    The service lazily builds the tables the first time they are requested and
    recomputes them when the underlying network changes (e.g., after a link
    failure).  For this project the network is static, so we simply compute once.
    """

    def __init__(self):
        self._network: EmergencyNetwork = build_sample_network()
        self._router: DistanceVectorRouter | None = None
        self._tables: Dict[str, Dict[str, Any]] | None = None

    def _ensure_router(self) -> DistanceVectorRouter:
        if self._router is None:
            self._router = DistanceVectorRouter(self._network)
        return self._router

    def run(self) -> None:
        """Run the Distance‑Vector algorithm and cache the tables."""
        router = self._ensure_router()
        router.run()
        # Convert dataclass entries to simple dicts for JSON serialisation
        self._tables = {
            node_id: {dest: entry.to_dict() for dest, entry in tbl.items()}
            for node_id, tbl in router._tables.items()
        }

    @property
    def tables(self) -> Dict[str, Dict[str, Any]]:
        """Return the latest routing tables, computing them on first access."""
        if self._tables is None:
            self.run()
        return self._tables

# Create a module‑level singleton – the Flask app can import this directly.
service = DistanceVectorService()
