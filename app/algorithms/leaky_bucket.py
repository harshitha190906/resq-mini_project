"""
ResQNet — app/algorithms/leaky_bucket.py
=========================================
**Leaky Bucket** traffic-shaping / congestion-control algorithm.

Background
----------
The leaky bucket models a FIFO buffer (the "bucket") that:

1. **Accepts** incoming packets up to its capacity.
2. **Drops** packets that arrive when the bucket is full (overflow).
3. **Leaks** (outputs) packets at a fixed rate regardless of the arrival
   pattern, producing a smooth, constant output stream.

This is one of the primary mechanisms used in emergency networks to prevent
bursty traffic from overwhelming shared links.

Tick-based simulation
---------------------
Time is divided into discrete **ticks**.  At each tick the simulation:

1. Applies the **arrival schedule** — adds ``arrivals[tick]`` packets to the
   bucket (dropping overflows).
2. **Leaks** ``leak_rate`` packets from the front of the bucket (outputs them).

The arrival schedule is a plain dictionary ``{tick: count}``; ticks not in
the dictionary have zero arrivals.  This makes the simulation fully
deterministic and easy to test.

Usage
-----
::

    from app.algorithms.leaky_bucket import LeakyBucket

    lb = LeakyBucket(capacity=5, leak_rate=1)
    arrivals = {0: 3, 1: 4, 2: 2, 5: 10}
    result = lb.run(arrivals=arrivals, duration=8)

    print(result.total_admitted)    # packets admitted to the bucket
    print(result.total_dropped)     # packets dropped (overflow)
    print(result.total_leaked)      # packets output (leaked)
    for event in result.events:
        print(event)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Event dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LeakyBucketEvent:
    """
    State snapshot for one simulation tick.

    Attributes
    ----------
    tick : int
        Zero-based time step index.
    arriving : int
        Number of packets that arrived this tick.
    admitted : int
        Number of arriving packets that were successfully added to the bucket.
    dropped : int
        Number of arriving packets dropped (bucket was full).
    leaked : int
        Number of packets output (leaked) from the bucket this tick.
    queue_before : int
        Bucket occupancy **before** arrivals this tick.
    queue_after : int
        Bucket occupancy **after** arrivals and leaking this tick.
    description : str
        Human-readable summary.
    """
    tick:         int
    arriving:     int
    admitted:     int
    dropped:      int
    leaked:       int
    queue_before: int
    queue_after:  int
    description:  str

    def to_dict(self) -> dict:
        return {
            "tick":         self.tick,
            "arriving":     self.arriving,
            "admitted":     self.admitted,
            "dropped":      self.dropped,
            "leaked":       self.leaked,
            "queue_before": self.queue_before,
            "queue_after":  self.queue_after,
            "description":  self.description,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LeakyBucketResult:
    """
    Full output of a :class:`LeakyBucket` simulation run.

    Attributes
    ----------
    capacity : int
        Maximum bucket occupancy.
    leak_rate : int
        Packets leaked per tick.
    duration : int
        Number of ticks simulated.
    total_arriving : int
        Sum of all packet arrivals across all ticks.
    total_admitted : int
        Packets successfully enqueued (arriving and not dropped).
    total_dropped : int
        Packets discarded because the bucket was full.
    total_leaked : int
        Packets output from the bucket over the simulation.
    final_queue : int
        Bucket occupancy at the end of the last tick.
    events : list[LeakyBucketEvent]
        Per-tick event log.
    """
    capacity:       int
    leak_rate:      int
    duration:       int
    total_arriving: int
    total_admitted: int
    total_dropped:  int
    total_leaked:   int
    final_queue:    int
    events:         List[LeakyBucketEvent] = field(default_factory=list)

    @property
    def drop_rate(self) -> float:
        """Fraction of arriving packets that were dropped (0.0–1.0)."""
        return self.total_dropped / self.total_arriving if self.total_arriving > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "capacity":       self.capacity,
            "leak_rate":      self.leak_rate,
            "duration":       self.duration,
            "total_arriving": self.total_arriving,
            "total_admitted": self.total_admitted,
            "total_dropped":  self.total_dropped,
            "total_leaked":   self.total_leaked,
            "final_queue":    self.final_queue,
            "drop_rate":      self.drop_rate,
            "events":         [e.to_dict() for e in self.events],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Leaky Bucket
# ─────────────────────────────────────────────────────────────────────────────

class LeakyBucket:
    """
    Leaky-bucket traffic shaper.

    Parameters
    ----------
    capacity : int
        Maximum number of packets the bucket can hold at once (>= 1).
    leak_rate : int
        Number of packets leaked (output) per tick (>= 1).
    """

    def __init__(self, capacity: int, leak_rate: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}.")
        if leak_rate < 1:
            raise ValueError(f"leak_rate must be >= 1, got {leak_rate}.")
        self.capacity  = capacity
        self.leak_rate = leak_rate

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        arrivals: Dict[int, int],
        duration: int,
    ) -> LeakyBucketResult:
        """
        Simulate the leaky bucket for *duration* ticks.

        Parameters
        ----------
        arrivals : dict[int, int]
            Mapping ``tick → number_of_packets`` arriving at that tick.
            Ticks absent from the dict have zero arrivals.
            Negative packet counts are treated as zero.
        duration : int
            Number of ticks to simulate (>= 1).

        Returns
        -------
        LeakyBucketResult
        """
        if duration < 1:
            raise ValueError(f"duration must be >= 1, got {duration}.")

        queue           = 0
        total_arriving  = 0
        total_admitted  = 0
        total_dropped   = 0
        total_leaked    = 0
        events: List[LeakyBucketEvent] = []

        for tick in range(duration):
            arriving     = max(0, arrivals.get(tick, 0))
            queue_before = queue

            # ── Step 1: arrivals ──────────────────────────────────────────────
            space     = self.capacity - queue
            admitted  = min(arriving, space)
            dropped   = arriving - admitted
            queue    += admitted

            total_arriving += arriving
            total_admitted += admitted
            total_dropped  += dropped

            # ── Step 2: leak ──────────────────────────────────────────────────
            leaked = min(self.leak_rate, queue)
            queue -= leaked
            total_leaked += leaked

            # ── Build description ─────────────────────────────────────────────
            parts = []
            if arriving > 0:
                parts.append(
                    f"{arriving} arrived; {admitted} admitted"
                    + (f", {dropped} DROPPED" if dropped else "")
                )
            else:
                parts.append("no arrivals")
            parts.append(f"leaked {leaked}")
            parts.append(f"queue {queue_before}→{queue}")
            description = "; ".join(parts) + "."

            events.append(LeakyBucketEvent(
                tick=tick,
                arriving=arriving,
                admitted=admitted,
                dropped=dropped,
                leaked=leaked,
                queue_before=queue_before,
                queue_after=queue,
                description=description,
            ))

        return LeakyBucketResult(
            capacity=self.capacity,
            leak_rate=self.leak_rate,
            duration=duration,
            total_arriving=total_arriving,
            total_admitted=total_admitted,
            total_dropped=total_dropped,
            total_leaked=total_leaked,
            final_queue=queue,
            events=events,
        )

    def tick(
        self,
        current_queue: int,
        arriving: int,
    ) -> LeakyBucketEvent:
        """
        Process **one tick** given an externally tracked queue size.

        This is a stateless helper useful for integrating the leaky bucket
        into a larger simulation loop where queue state is managed externally.

        Parameters
        ----------
        current_queue : int
            Bucket occupancy at the start of this tick (0 ≤ value ≤ capacity).
        arriving : int
            Number of packets arriving this tick (>= 0).

        Returns
        -------
        LeakyBucketEvent
            The event for this tick (caller must update their queue with
            ``event.queue_after``).
        """
        if current_queue < 0 or current_queue > self.capacity:
            raise ValueError(
                f"current_queue {current_queue} is out of range "
                f"[0, {self.capacity}]."
            )
        arriving = max(0, arriving)
        space    = self.capacity - current_queue
        admitted = min(arriving, space)
        dropped  = arriving - admitted
        queue    = current_queue + admitted
        leaked   = min(self.leak_rate, queue)
        queue   -= leaked

        return LeakyBucketEvent(
            tick=-1,   # caller sets the real tick number
            arriving=arriving,
            admitted=admitted,
            dropped=dropped,
            leaked=leaked,
            queue_before=current_queue,
            queue_after=queue,
            description=(
                f"tick: {arriving} arrived, {admitted} admitted"
                + (f", {dropped} dropped" if dropped else "")
                + f"; leaked {leaked}; queue {current_queue}→{queue}."
            ),
        )
