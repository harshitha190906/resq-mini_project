"""
ResQNet — app/services/congestion_service.py
============================================
Service managing Leaky Bucket congestion control simulations,
traffic burst shaping comparisons, and tick-by-tick state progression.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any, Union
from app.algorithms.leaky_bucket import LeakyBucket, LeakyBucketResult, LeakyBucketEvent
from app.services.history_service import history_service


def parse_arrivals_input(val: Union[str, List[int], Dict[str, int], Dict[int, int]]) -> Dict[int, int]:
    """Parse arrival sequence from string '12, 2, 14, 0, 8, 16, 2, 0', list, or dict."""
    if not val:
        return {0: 12, 1: 2, 2: 14, 3: 0, 4: 8, 5: 16, 6: 2, 7: 0}

    if isinstance(val, dict):
        return {int(k): int(v) for k, v in val.items()}

    if isinstance(val, list):
        return {i: int(v) for i, v in enumerate(val)}

    if isinstance(val, str):
        val = val.strip().strip("[]()")
        parts = [p.strip() for p in val.split(",") if p.strip()]
        res = {}
        for i, p in enumerate(parts):
            try:
                res[i] = max(0, int(p))
            except ValueError:
                pass
        return res if res else {0: 12, 1: 2, 2: 14, 3: 0, 4: 8, 5: 16, 6: 2, 7: 0}

    return {0: 12, 1: 2, 2: 14, 3: 0, 4: 8, 5: 16, 6: 2, 7: 0}


class CongestionService:
    def __init__(self) -> None:
        self.default_capacity = 15
        self.default_leak_rate = 4
        self.default_arrivals = [12, 2, 14, 0, 8, 16, 2, 0]
        self._last_result: Optional[LeakyBucketResult] = None
        self._last_params: Dict[str, Any] = {}

    def simulate(
        self,
        capacity: int = 15,
        leak_rate: int = 4,
        arrivals_input: Any = None,
        duration: Optional[int] = None,
        record_history: bool = True
    ) -> Dict[str, Any]:
        """Execute a Leaky Bucket congestion control run and compute analytical curves."""
        cap = max(1, int(capacity))
        rate = max(1, int(leak_rate))
        arrivals = parse_arrivals_input(arrivals_input if arrivals_input is not None else self.default_arrivals)

        max_tick = max(arrivals.keys()) if arrivals else 0
        dur = int(duration) if duration is not None and int(duration) > 0 else (max_tick + 1)
        # Ensure duration allows queue to drain if requested or covers arrivals
        dur = max(dur, max_tick + 1)

        bucket = LeakyBucket(capacity=cap, leak_rate=rate)
        result = bucket.run(arrivals=arrivals, duration=dur)
        self._last_result = result
        self._last_params = {
            "capacity": cap,
            "leak_rate": rate,
            "duration": dur,
            "arrivals": arrivals
        }

        # Calculate metrics
        loss_pct = round((result.total_dropped / result.total_arriving * 100.0), 1) if result.total_arriving > 0 else 0.0
        eff_pct = round((result.total_leaked / result.total_arriving * 100.0), 1) if result.total_arriving > 0 else 100.0

        # Construct time series for charts
        ticks = [e.tick for e in result.events]
        incoming_series = [e.arriving for e in result.events]
        transmitted_series = [e.leaked for e in result.events]
        dropped_series = [e.dropped for e in result.events]
        queue_series = [e.queue_after for e in result.events]

        response_data = {
            "status": "success",
            "capacity": cap,
            "leak_rate": rate,
            "duration": dur,
            "metrics": {
                "total_incoming": result.total_arriving,
                "total_transmitted": result.total_leaked,
                "total_dropped": result.total_dropped,
                "remaining_queue": result.final_queue,
                "loss_percentage": loss_pct,
                "efficiency_percentage": eff_pct,
            },
            "events": [e.to_dict() for e in result.events],
            "time_series": {
                "ticks": ticks,
                "incoming": incoming_series,
                "transmitted": transmitted_series,
                "dropped": dropped_series,
                "queue_level": queue_series,
            }
        }

        # Automatically record to persistent SQLite history
        if record_history and result.total_arriving > 0:
            sim_status = "SUCCESS" if result.total_dropped == 0 else "COMPLETED_WITH_LOSS"
            throughput_approx = round(result.total_leaked * 1024 * 8 / max(1, dur) / 1000.0, 2)
            history_service.record_simulation(
                algorithm="Leaky Bucket Congestion",
                packets_sent=result.total_arriving,
                packets_delivered=result.total_leaked,
                packets_lost=result.total_dropped,
                avg_delay_ms=round(dur * 2.5, 2),
                throughput_kbps=throughput_approx,
                status=sim_status,
                parameters={
                    "capacity": cap,
                    "leak_rate": rate,
                    "duration": dur,
                    "arrivals": arrivals
                },
                details={
                    "loss_pct": loss_pct,
                    "final_queue": result.final_queue,
                    "efficiency_pct": eff_pct
                }
            )

        return response_data

    def get_status(self) -> Dict[str, Any]:
        """Return the current or most recent simulation state."""
        if self._last_result is None:
            # Return fresh default simulation
            return self.simulate(
                capacity=self.default_capacity,
                leak_rate=self.default_leak_rate,
                arrivals_input=self.default_arrivals,
                record_history=False
            )
        return self.simulate(
            capacity=self._last_params.get("capacity", self.default_capacity),
            leak_rate=self._last_params.get("leak_rate", self.default_leak_rate),
            arrivals_input=self._last_params.get("arrivals", self.default_arrivals),
            duration=self._last_params.get("duration"),
            record_history=False
        )

    def reset(self) -> Dict[str, Any]:
        """Reset the congestion service state to defaults."""
        self._last_result = None
        self._last_params = {}
        return {"status": "reset_complete"}


# Singleton instance
congestion_service = CongestionService()

