# app/services/leaky_bucket_service.py
"""Leaky‑Bucket traffic‑shaping service.
Provides a thin wrapper around :class:`app.algorithms.leaky_bucket.LeakyBucket`
so that the bucket can be run on demand and its latest result exposed via API.
"""

from __future__ import annotations

from typing import Dict

from app.algorithms.leaky_bucket import LeakyBucket, LeakyBucketResult

class LeakyBucketService:
    """Singleton‑style service that holds the most recent bucket run.

    The bucket is configured at construction time (capacity and leak rate).
    The ``run`` method is called with an ``arrivals`` dict and a ``duration``
    (number of ticks). The result is cached for the UI.
    """

    def __init__(self, capacity: int = 10, leak_rate: int = 2):
        self.bucket = LeakyBucket(capacity, leak_rate)
        self._last_result: LeakyBucketResult | None = None

    def run(self, arrivals: Dict[int, int], duration: int) -> LeakyBucketResult:
        """Execute the leaky‑bucket simulation and store the result."""
        self._last_result = self.bucket.run(arrivals=arrivals, duration=duration)
        return self._last_result

    @property
    def last_result(self) -> LeakyBucketResult | None:
        """Return the most recent result (or ``None`` if not run yet)."""
        return self._last_result

# Module‑level singleton used by the Flask app.
service = LeakyBucketService()
