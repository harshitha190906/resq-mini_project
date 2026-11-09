"""
ResQNet — app/simulation/engine.py
=================================
Discrete‑event simulation engine for the emergency communication network.

The engine is **deterministic** – no real time sleeps are used – and therefore
suitable for unit testing.  It integrates the existing topology and routing
modules, and optionally the reliability algorithms (CRC, Go‑Back‑N, Leaky
Bucket).

Key concepts
------------
* **Packet** – logical unit of data with a unique id, size (bytes) and a
  payload string.  For the simulation only the size matters for bandwidth
  calculations.
* **Event record** – a plain ``dict`` describing what happened to a packet.
  The engine stores all records in ``self.events`` which can later be fed to
  :class:`app.simulation.metrics.SimulationMetrics`.
* **Traffic levels** – ``low``, ``medium`` and ``high`` map to a deterministic
  inter‑arrival interval (in seconds).  The engine does not spawn background
  threads; instead ``send_batch`` simply creates the appropriate number of
  packets and processes them sequentially.
* **Link state** – each :class:`app.algorithms.network_topology.Link`
  maintains a ``queue_capacity``.  The engine tracks a per‑link usage counter
  ``self._link_usage``.  When the counter would exceed the capacity the packet
  is dropped with loss reason ``queue_overflow``.
* **Go‑Back‑N** – when ``enable_gbn`` is ``True`` the engine uses the GBN
  implementation to decide whether a frame is lost.  Retransmissions are
  counted and the final delivery status reflects successful recovery.

Public API
----------
* :class:`SimulationEngine`
    * ``send_packet(src, dst, message, size_bytes=None, priority="NORMAL")`` –
      simulate a single packet.
    * ``send_batch(count, src, dst, message, size_bytes=None, priority="NORMAL")`` –
      generate *count* packets respecting the configured traffic level.
    * ``events`` – list of event dictionaries produced by the engine.

The design purposefully stays lightweight: all state lives in memory and the
engine can be instantiated directly in tests.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple, Optional

from app.algorithms.network_topology import EmergencyNetwork, build_sample_network
from app.algorithms.dijkstra import dijkstra
from app.algorithms.go_back_n import GoBackN
from app.services.leaky_bucket_service import service as leaky_bucket_service


class TrafficLevel(str, Enum):
    """Deterministic traffic generation intervals (seconds)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def inter_arrival(self) -> float:
        """Return the deterministic inter‑arrival interval for the level.

        The values are chosen to keep the simulation quick while still
        allowing multiple packets to occupy a link when the level is ``high``.
        """
        mapping = {"low": 5.0, "medium": 2.0, "high": 0.5}
        return mapping[self.value]


@dataclass
class PacketEvent:
    """Record of a single packet's journey through the simulated network."""

    packet_id: int
    src: str
    dst: str
    size_bytes: int
    route: List[str]
    timestamps: List[float] = field(default_factory=list)  # per‑hop arrival times
    delivered: bool = False
    loss_reason: Optional[str] = None
    retransmissions: int = 0
    priority: str = "NORMAL"

    @property
    def send_timestamp(self) -> float:
        return self.timestamps[0] if self.timestamps else 0.0

    @property
    def arrival_timestamp(self) -> Optional[float]:
        return self.timestamps[-1] if self.delivered else None


class SimulationEngine:
    """Deterministic discrete‑event simulation engine.

    The engine works entirely in memory – there is no real‑time waiting.  Time
    advances only when an event is processed.  All timestamps are measured in
    **seconds**.
    """

    def __init__(
        self,
        network: Optional[EmergencyNetwork] = None,
        traffic_level: TrafficLevel = TrafficLevel.LOW,
        packet_size_bytes: int = 1024,
        enable_gbn: bool = False,
        gbn_lost_frames: Optional[set[Tuple[int, int]]] = None,
    ) -> None:
        self.network: EmergencyNetwork = network or build_sample_network()
        self.traffic_level = traffic_level
        self.default_packet_size = packet_size_bytes
        self.enable_gbn = enable_gbn
        # Leaky bucket state – current queue length
        self._bucket_queue: int = 0
        self.gbn = GoBackN(lost_frames=gbn_lost_frames) if enable_gbn else None
        self.current_time: float = 0.0
        self.events: List[PacketEvent] = []
        # usage counter for each directed link (src, tgt) → number of in‑flight packets
        self._link_usage: Dict[Tuple[str, str], int] = {}
        self._packet_counter = itertools.count(1)

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------
    def _reset_link_usage(self) -> None:
        """Clear per‑link usage counters.

        The engine processes packets sequentially, so after a packet finishes we
        can reset the counters.  This mimics a *stop‑and‑wait* style processing
        which is sufficient for the unit‑test scenarios.
        """
        self._link_usage.clear()

    def _increment_usage(self, src: str, tgt: str) -> None:
        self._link_usage[(src, tgt)] = self._link_usage.get((src, tgt), 0) + 1

    def _decrement_usage(self, src: str, tgt: str) -> None:
        key = (src, tgt)
        if key in self._link_usage:
            self._link_usage[key] -= 1
            if self._link_usage[key] <= 0:
                del self._link_usage[key]

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def send_packet(
        self,
        src: str,
        dst: str,
        message: str,
        size_bytes: Optional[int] = None,
        priority: str = "NORMAL",
    ) -> PacketEvent:
        """Simulate a single packet from *src* to *dst*.

        The method returns a :class:`PacketEvent` containing the full trace.
        """
        size = size_bytes or self.default_packet_size
        packet_id = next(self._packet_counter)
        event = PacketEvent(
            packet_id=packet_id,
            src=src,
            dst=dst,
            size_bytes=size,
            route=[],
            priority=priority,
        )

        # Determine the route – we deliberately use Dijkstra which respects
        # link costs and skips disabled links.
        try:
            route_result = dijkstra(self.network, src, dst)
            route = route_result.path
        except Exception:
            # No path at all – treat as immediate loss.
            event.delivered = False
            event.loss_reason = "no_path"
            self.events.append(event)
            return event

        # Dijkstra returns an empty path when destination is unreachable.
        if not route or not route_result.reachable:
            event.delivered = False
            event.loss_reason = "no_path"
            self.events.append(event)
            return event

        event.route = route
        # Record the moment the packet is injected into the network.
        event.timestamps.append(self.current_time)

        # Walk the hops.
        for i in range(len(route) - 1):
            hop_src = route[i]
            hop_tgt = route[i + 1]
            link = self.network.get_link(hop_src, hop_tgt)

            # -----------------------------------------------------------------
            # Link operational check
            # -----------------------------------------------------------------
            if not link.is_operational:
                event.delivered = False
                event.loss_reason = "link_failed"
                break

            # -----------------------------------------------------------------
            # Queue capacity check (simple deterministic model)
            # -----------------------------------------------------------------
            usage = self._link_usage.get((hop_src, hop_tgt), 0)
            if usage >= link.queue_capacity:
                event.delivered = False
                event.loss_reason = "queue_overflow"
                break

            # Reserve capacity for this packet on the link.
            self._increment_usage(hop_src, hop_tgt)

            # -----------------------------------------------------------------
            # Simulate transmission latency (seconds)
            # -----------------------------------------------------------------
            self.current_time += link.latency_ms / 1000.0
            event.timestamps.append(self.current_time)

            # -----------------------------------------------------------------
            # Optional Go‑Back‑N loss simulation
            # -----------------------------------------------------------------
            if self.enable_gbn:
                seq = i  # use hop index as a deterministic sequence number
                lost = self.gbn.is_lost(seq, event.retransmissions + 1)
                if lost:
                    # Record a timeout warning – the caller (OSI model) would
                    # interpret this as a need for retransmission.
                    event.retransmissions += 1
                    # For the deterministic simulation we immediately retry the
                    # same hop (no additional latency) – this keeps the test
                    # environment simple.
                    continue

            # Release the link after the hop completed.
            self._decrement_usage(hop_src, hop_tgt)

        else:
            # The loop completed without ``break`` – delivery succeeded.
            event.delivered = True
            event.loss_reason = None

        # Record final timestamp for successful delivery.
        if event.delivered:
            event.timestamps.append(self.current_time)

        self.events.append(event)
        # Reset usage counters to keep the model simple for the next packet.
        self._reset_link_usage()
        return event

    def send_batch(
        self,
        count: int,
        src: str,
        dst: str,
        message: str,
        size_bytes: Optional[int] = None,
        priority: str = "NORMAL",
    ) -> List[PacketEvent]:
        """Send *count* packets respecting the configured traffic level.

        The inter‑arrival interval is deterministic based on
        :class:`TrafficLevel.inter_arrival`. This version also applies the
        Leaky‑Bucket traffic‑shaping model. Packets that cannot be admitted are
        recorded as lost with ``loss_reason = "bucket_overflow"``.
        """
        events: List[PacketEvent] = []
        for _ in range(count):
            # ---- Leaky‑Bucket admission check ----
            capacity = leaky_bucket_service.bucket.capacity
            if self._bucket_queue >= capacity:
                # Drop packet due to overflow
                ev = PacketEvent(
                    packet_id=next(self._packet_counter),
                    src=src,
                    dst=dst,
                    size_bytes=size_bytes or self.default_packet_size,
                    route=[],
                    timestamps=[],
                    delivered=False,
                    loss_reason="bucket_overflow",
                    retransmissions=0,
                    priority=priority,
                )
                self.events.append(ev)
                events.append(ev)
                # Leak after this tick
                self._bucket_queue = max(0, self._bucket_queue - leaky_bucket_service.bucket.leak_rate)
                self.current_time += self.traffic_level.inter_arrival
                continue
            # Admit packet to bucket
            self._bucket_queue += 1
            ev = self.send_packet(src, dst, message, size_bytes, priority)
            events.append(ev)
            # Leak after processing this packet
            self._bucket_queue = max(0, self._bucket_queue - leaky_bucket_service.bucket.leak_rate)
            # Advance time for next packet arrival
            self.current_time += self.traffic_level.inter_arrival
        return events

"""End of engine module."""
