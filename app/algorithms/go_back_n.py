"""
ResQNet — app/algorithms/go_back_n.py
======================================
Deterministic simulation of the **Go-Back-N (GBN)** sliding-window ARQ
(Automatic Repeat reQuest) protocol.

Protocol summary
----------------
* The sender maintains a window of up to ``window_size`` unacknowledged
  frames in flight simultaneously.
* Sequence numbers wrap modulo ``(window_size + 1)`` — the minimum modulus
  that prevents ambiguity (just like the real protocol).
* When a frame is **lost** (controlled by ``lost_frames`` — a set of
  sequence numbers whose transmission event is silently dropped) or when the
  sender's **timer** fires, the sender **goes back** to the first
  unacknowledged frame and retransmits it **and every subsequent frame** in
  the window.
* The receiver only accepts frames arriving **in order**; out-of-order
  frames are silently discarded (no buffering — standard GBN behaviour).
* Simulation is **tick-based**: each call to :meth:`GBNSimulator.step`
  advances time by one tick, processes one send/receive/ACK/timeout event,
  and appends one :class:`GBNEvent` to the log.

Determinism
-----------
All randomness is eliminated by expressing losses as an explicit set of
``(sequence_number, attempt_number)`` pairs supplied by the caller.  Tests
can therefore be exact and reproducible.

Usage
-----
::

    from app.algorithms.go_back_n import GBNSimulator

    sim = GBNSimulator(
        total_frames=8,
        window_size=4,
        timeout_ticks=3,
        lost_frames={(2, 1)},   # seq 2 lost on first attempt
    )
    result = sim.run()
    print(result.delivered_in_order)   # [0, 1, 2, 3, 4, 5, 6, 7]
    print(result.total_transmissions)  # > 8 due to retransmission
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class GBNEventType(str, Enum):
    SEND      = "SEND"       # sender transmits a frame
    ACK       = "ACK"        # receiver sends ACK; sender advances window
    LOSS      = "LOSS"       # frame marked as lost (dropped in channel)
    TIMEOUT   = "TIMEOUT"    # timer fires; sender retransmits window
    DISCARD   = "DISCARD"    # receiver discards out-of-order frame
    DELIVERED = "DELIVERED"  # frame accepted in order by receiver
    DONE      = "DONE"       # all frames successfully delivered


# ─────────────────────────────────────────────────────────────────────────────
# Event dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GBNEvent:
    """
    One event in the Go-Back-N simulation timeline.

    Attributes
    ----------
    tick : int
        Simulation time-step (0-based).
    event_type : GBNEventType
        Category of this event.
    seq_num : int or None
        Sequence number of the frame involved (None for DONE).
    frame_id : int or None
        0-based original frame index (data identity, distinct from seq_num).
    attempt : int
        How many times this frame_id has been transmitted so far (1 = first).
    window_state : list[int]
        Sequence numbers currently in the sender's window at this tick.
    description : str
        Human-readable summary of the event.
    base : int
        Current sender window base frame index.
    next_seq : int
        Next sequence number or frame index to be sent.
    expected_seq : int
        Current expected sequence number at the receiver.
    action : str
        Action code for visualization and ladder diagrams.
    """
    tick:         int
    event_type:   GBNEventType
    seq_num:      Optional[int]
    frame_id:     Optional[int]
    attempt:      int
    window_state: List[int]
    description:  str
    base:         int = 0
    next_seq:     int = 0
    expected_seq: int = 0
    action:       str = ""

    def to_dict(self) -> dict:
        return {
            "tick":         self.tick,
            "event_type":   self.event_type.value,
            "seq_num":      self.seq_num,
            "frame_id":     self.frame_id,
            "attempt":      self.attempt,
            "window_state": self.window_state,
            "description":  self.description,
            "base":         self.base,
            "next_seq":     self.next_seq,
            "expected_seq": self.expected_seq,
            "action":       self.action or self.event_type.value,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helper: flexible loss input parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_lost_frames_input(val) -> Set[Tuple[int, int]]:
    """Parse lost frames specification from multiple user formats into a set of (seq, attempt) tuples."""
    if not val:
        return set()
    if isinstance(val, (int, float)):
        return {(int(val), 1)}
    if isinstance(val, (set, frozenset)):
        return set(val)
    if isinstance(val, list):
        res = set()
        for item in val:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                res.add((int(item[0]), int(item[1])))
            elif isinstance(item, (int, str)):
                try:
                    res.add((int(item), 1))
                except ValueError:
                    pass
        return res
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return set()
        # Check for colon pairs: '2:1, 4:2'
        if ":" in val:
            import re
            return {(int(x), int(y)) for x, y in re.findall(r"(\d+)\s*:\s*(\d+)", val)}
        # Check for semicolon syntax: '1,1; 3,2'
        if ";" in val:
            res = set()
            for part in val.split(";"):
                part = part.strip().strip("()[]")
                if not part:
                    continue
                sub = [s.strip() for s in part.split(",") if s.strip()]
                if len(sub) == 2:
                    res.add((int(sub[0]), int(sub[1])))
                elif len(sub) == 1:
                    res.add((int(sub[0]), 1))
            return res
        # Comma syntax: '1, 3' (two frames) or '1,1' (one pair)
        parts = [p.strip() for p in val.split(",") if p.strip()]
        if len(parts) == 2 and " " not in val:
            try:
                return {(int(parts[0]), int(parts[1]))}
            except ValueError:
                pass
        return {(int(p), 1) for p in parts if p.isdigit()}
    return set()


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GBNResult:
    """
    Complete output of a Go-Back-N simulation run.

    Attributes
    ----------
    total_frames : int
        Number of frames the sender needed to deliver.
    window_size : int
        Sender window size used.
    timeout_ticks : int
        Number of ticks before a timeout fires.
    modulus : int
        Sequence number space size (``window_size + 1``).
    delivered_in_order : list[int]
        Frame IDs delivered to the receiver, in arrival order.
    total_transmissions : int
        Total send events (first attempts + retransmissions).
    total_timeouts : int
        Number of timeout events that fired.
    total_ticks : int
        Total simulation time steps elapsed.
    events : list[GBNEvent]
        Full chronological event log.
    """
    total_frames:        int
    window_size:         int
    timeout_ticks:       int
    modulus:             int
    delivered_in_order:  List[int]
    total_transmissions: int
    total_timeouts:      int
    total_ticks:         int
    events:              List[GBNEvent] = field(default_factory=list)

    def compute_analytics(self) -> dict:
        """Calculate complete analytical KPIs, distributions, and chart curves."""
        lost_count = sum(1 for e in self.events if e.event_type == GBNEventType.LOSS)
        retrans_count = sum(1 for e in self.events if e.event_type == GBNEventType.SEND and e.attempt > 1)
        ack_count = sum(1 for e in self.events if e.event_type == GBNEventType.ACK)
        del_count = len(self.delivered_in_order)

        # Track attempts and delays per frame ID
        first_send_tick: Dict[int, int] = {}
        delivery_tick: Dict[int, int] = {}
        attempts_map: Dict[int, int] = {i: 1 for i in range(self.total_frames)}

        for e in self.events:
            if e.frame_id is not None:
                fid = e.frame_id
                if fid not in first_send_tick and e.event_type in (GBNEventType.SEND, GBNEventType.LOSS):
                    first_send_tick[fid] = e.tick
                if e.attempt > attempts_map.get(fid, 1):
                    attempts_map[fid] = e.attempt
                if e.event_type == GBNEventType.DELIVERED:
                    delivery_tick[fid] = e.tick

        delay_per_frame = []
        for i in range(self.total_frames):
            if i in delivery_tick and i in first_send_tick:
                delay_per_frame.append(max(1, delivery_tick[i] - first_send_tick[i] + 1))
            else:
                delay_per_frame.append(0)

        attempts_list = [attempts_map.get(i, 1) for i in range(self.total_frames)]
        delivered_delays = [d for d in delay_per_frame if d > 0]
        avg_delay = float(sum(delivered_delays) / len(delivered_delays)) if delivered_delays else 0.0

        eff_pct = round((self.total_frames / self.total_transmissions * 100.0), 1) if self.total_transmissions > 0 else 0.0
        del_pct = round((del_count / self.total_frames * 100.0), 1) if self.total_frames > 0 else 0.0

        # Timeline cumulative data
        timeline_ticks = []
        cum_acks = []
        cum_trans = []
        cum_losses = []
        c_a = 0
        c_t = 0
        c_l = 0

        for e in self.events:
            timeline_ticks.append(e.tick)
            if e.event_type == GBNEventType.ACK:
                c_a += 1
            elif e.event_type == GBNEventType.SEND:
                c_t += 1
            elif e.event_type == GBNEventType.LOSS:
                c_l += 1
            cum_acks.append(c_a)
            cum_trans.append(c_t)
            cum_losses.append(c_l)

        return {
            "total_frames": self.total_frames,
            "total_transmissions": self.total_transmissions,
            "delivered_frames": del_count,
            "lost_transmissions": lost_count,
            "retransmissions": retrans_count,
            "timeouts": self.total_timeouts,
            "ack_count": ack_count,
            "delivery_pct": del_pct,
            "channel_efficiency_pct": eff_pct,
            "avg_delay_ticks": round(avg_delay, 2),
            "attempts_per_frame": attempts_list,
            "delay_per_frame": delay_per_frame,
            "status_distribution": {
                "delivered": del_count,
                "lost": lost_count,
                "retransmitted": retrans_count,
            },
            "timeline": {
                "ticks": timeline_ticks,
                "cumulative_acks": cum_acks,
                "cumulative_transmissions": cum_trans,
                "cumulative_losses": cum_losses,
            }
        }

    def to_dict(self) -> dict:
        return {
            "total_frames":        self.total_frames,
            "window_size":         self.window_size,
            "timeout_ticks":       self.timeout_ticks,
            "modulus":             self.modulus,
            "delivered_in_order":  self.delivered_in_order,
            "total_transmissions": self.total_transmissions,
            "total_timeouts":      self.total_timeouts,
            "total_ticks":         self.total_ticks,
            "events":              [e.to_dict() for e in self.events],
            "analytics":           self.compute_analytics(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Simulator
# ─────────────────────────────────────────────────────────────────────────────

class GBNSimulator:
    """
    Tick-based Go-Back-N ARQ simulator.

    Parameters
    ----------
    total_frames : int
        Number of data frames the sender wants to deliver (>= 1).
    window_size : int
        Maximum number of unacknowledged frames in flight (>= 1).
    timeout_ticks : int
        How many ticks the sender waits for an ACK before timing out (>= 1).
    lost_frames : set of (seq_num, attempt) tuples, optional
        Pairs ``(sequence_number, attempt_number)`` that should be silently
        dropped.  The attempt counter is 1-based and frame-id-scoped,
        so ``(2, 1)`` means "drop the first transmission of the frame whose
        sequence number at that moment is 2".
    max_ticks : int, optional
        Safety cap on total simulation ticks (default 10 000).
    """

    def __init__(
        self,
        total_frames: int,
        window_size:  int,
        timeout_ticks: int,
        lost_frames:  Optional[Set[Tuple[int, int]]] = None,
        max_ticks:    int = 10_000,
    ) -> None:
        if total_frames < 1:
            raise ValueError("total_frames must be >= 1.")
        if window_size < 1:
            raise ValueError("window_size must be >= 1.")
        if timeout_ticks < 1:
            raise ValueError("timeout_ticks must be >= 1.")
        if max_ticks < 1:
            raise ValueError("max_ticks must be >= 1.")

        self.total_frames  = total_frames
        self.window_size   = window_size
        self.timeout_ticks = timeout_ticks
        self.modulus       = window_size + 1   # seq-num space
        self.lost_frames: Set[Tuple[int, int]] = lost_frames or set()
        self.max_ticks     = max_ticks

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> GBNResult:
        """
        Execute the full Go-Back-N simulation until all frames are delivered
        or *max_ticks* is reached.

        State model
        -----------
        * ``window`` is an ordered list of ``(frame_id, seq_num)`` pairs
          representing frames currently in transit (sent but not yet ACKed).
        * On timeout the entire window content is retransmitted (GBN rule).
        * ``next_frame_id`` only advances when a *new* (never-sent) frame
          is added to the window; retransmissions re-use existing window entries.

        Returns
        -------
        GBNResult
        """
        # ── Sender window: ordered list of (frame_id, seq_num) in-flight ──────
        # window[0] is the oldest unACKed frame (send_base)
        window: List[Tuple[int, int]] = []   # [(frame_id, seq_num), ...]

        next_frame_id = 0   # next frame not yet placed in the window
        next_seq      = 0   # absolute sequence counter (wraps via modulus)

        # per-frame transmission attempt counter
        attempts: Dict[int, int] = {}

        # ── Receiver state ────────────────────────────────────────────────────
        expected_seq  = 0   # absolute, unwrapped expected sequence number
        delivered: List[int] = []

        # ── Timer ─────────────────────────────────────────────────────────────
        timer_start: Optional[int] = None   # tick when current timer started

        # ── Metrics / log ─────────────────────────────────────────────────────
        events:              List[GBNEvent] = []
        total_transmissions = 0
        total_timeouts      = 0
        tick = 0

        # ── Helpers ───────────────────────────────────────────────────────────
        def window_seq_list() -> List[int]:
            return [seq % self.modulus for _, seq in window]

        def current_base() -> int:
            return window[0][0] if window else next_frame_id

        def log(event_type, seq_num, frame_id, attempt, desc, action=""):
            events.append(GBNEvent(
                tick=tick,
                event_type=event_type,
                seq_num=seq_num,
                frame_id=frame_id,
                attempt=attempt,
                window_state=window_seq_list(),
                description=desc,
                base=current_base(),
                next_seq=next_frame_id,
                expected_seq=expected_seq % self.modulus,
                action=action or event_type.value,
            ))

        def transmit_frame(fid: int, seq: int) -> bool:
            """
            Transmit one frame.  Returns True if the frame was delivered
            to the receiver (not lost, in-order).
            """
            nonlocal total_transmissions, expected_seq

            seq_mod = seq % self.modulus
            attempts[fid] = attempts.get(fid, 0) + 1
            att = attempts[fid]

            if (seq_mod, att) in self.lost_frames or (fid, att) in self.lost_frames:
                log(GBNEventType.LOSS, seq_mod, fid, att,
                    f"Frame {fid} (seq {seq_mod}) attempt {att} lost in channel.",
                    action="LOSS")
                return False

            is_retry = att > 1
            log(GBNEventType.SEND, seq_mod, fid, att,
                f"{'Retransmitted' if is_retry else 'Sent'} frame {fid} (seq {seq_mod}), attempt {att}.",
                action="RETRY" if is_retry else "SEND")
            total_transmissions += 1

            if seq_mod == expected_seq % self.modulus:
                # In-order — accepted by receiver
                log(GBNEventType.DELIVERED, seq_mod, fid, att,
                    f"Receiver accepted frame {fid} (seq {seq_mod}).",
                    action="DELIVERED")
                delivered.append(fid)
                expected_seq += 1

                log(GBNEventType.ACK, seq_mod, fid, att,
                    f"ACK {seq_mod} sent. Window advances.",
                    action="ACK")
                return True
            else:
                # Out-of-order — discarded
                log(GBNEventType.DISCARD, seq_mod, fid, att,
                    f"Receiver discarded frame {fid} (seq {seq_mod}), "
                    f"expected seq {expected_seq % self.modulus}.",
                    action="DISCARD")
                return False

        # ── Main loop ─────────────────────────────────────────────────────────
        while len(delivered) < self.total_frames and tick < self.max_ticks:
            tick += 1

            # ── Timeout? → retransmit whole window ───────────────────────────
            if (timer_start is not None
                    and (tick - timer_start) >= self.timeout_ticks
                    and window):
                total_timeouts += 1
                base_seq = window[0][1] % self.modulus
                log(GBNEventType.TIMEOUT, base_seq, None, 0,
                    f"Timeout fired. Going back to seq {base_seq}.",
                    action="TIMEOUT")
                timer_start = tick   # reset timer

                # Retransmit every frame currently in the window
                i = 0
                while i < len(window) and len(delivered) < self.total_frames:
                    fid, seq = window[i]
                    delivered_now = transmit_frame(fid, seq)
                    if delivered_now:
                        window.pop(i)   # ACKed — slide out
                        if not window:
                            timer_start = None
                        # don't increment i — next frame is now at position i
                    else:
                        i += 1
                continue   # go to next tick after handling timeout

            # ── Fill window with new frames ───────────────────────────────────
            while len(window) < self.window_size and next_frame_id < self.total_frames:
                fid = next_frame_id
                seq = next_seq
                window.append((fid, seq))
                next_frame_id += 1
                next_seq      += 1

                if timer_start is None:
                    timer_start = tick

                delivered_now = transmit_frame(fid, seq)
                if delivered_now:
                    window.pop()   # just added and immediately ACKed
                    if not window:
                        timer_start = None

                if len(delivered) == self.total_frames:
                    break

        if len(delivered) == self.total_frames:
            events.append(GBNEvent(
                tick=tick,
                event_type=GBNEventType.DONE,
                seq_num=None,
                frame_id=None,
                attempt=0,
                window_state=[],
                description="All frames delivered successfully.",
                base=self.total_frames,
                next_seq=self.total_frames,
                expected_seq=self.total_frames % self.modulus,
                action="DONE",
            ))

        return GBNResult(
            total_frames=self.total_frames,
            window_size=self.window_size,
            timeout_ticks=self.timeout_ticks,
            modulus=self.modulus,
            delivered_in_order=delivered,
            total_transmissions=total_transmissions,
            total_timeouts=total_timeouts,
            total_ticks=tick,
            events=events,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatibility shim used by app/simulation/engine.py
# ─────────────────────────────────────────────────────────────────────────────

class GoBackN:
    """Lightweight wrapper around GBNSimulator used by SimulationEngine.

    The engine uses this to decide, per-hop, whether a frame should be
    considered lost.  It does *not* run the full simulation; it simply
    exposes :meth:`is_lost` which checks the caller-supplied ``lost_frames``
    set.

    Parameters
    ----------
    lost_frames : set of (seq_num, attempt) tuples, optional
        Same semantics as :class:`GBNSimulator`.  Pairs that should be
        treated as lost.
    """

    def __init__(self, lost_frames: Optional[Set[Tuple[int, int]]] = None) -> None:
        self.lost_frames: Set[Tuple[int, int]] = lost_frames or set()

    def is_lost(self, seq_num: int, attempt: int) -> bool:
        """Return *True* if ``(seq_num, attempt)`` is in the loss set."""
        return (seq_num, attempt) in self.lost_frames

    def run_simulation(
        self,
        total_frames: int,
        window_size: int = 4,
        timeout_ticks: int = 5,
    ) -> GBNResult:
        """Run a full GBN simulation and return the result.

        Delegates to :class:`GBNSimulator` with the already-configured
        ``lost_frames``.
        """
        sim = GBNSimulator(
            total_frames=total_frames,
            window_size=window_size,
            timeout_ticks=timeout_ticks,
            lost_frames=self.lost_frames,
        )
        return sim.run()
