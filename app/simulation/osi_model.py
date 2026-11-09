"""
ResQNet — app/simulation/osi_model.py
======================================
Educational simulation of the seven-layer OSI model tailored for
emergency communication scenarios.

⚠️  EDUCATIONAL SIMULATION DISCLAIMER
--------------------------------------
This module is an **educational simulation**, not a real-world protocol
stack.  Layer behaviours are simplified and linearised to illustrate the
OSI encapsulation / decapsulation principle clearly.  Real implementations
of TCP/IP, IEEE 802, etc. are far more complex.

OSI Layer Map
-------------
+-------+--------------+---------------------------+
| Layer | Name         | PDU                       |
+-------+--------------+---------------------------+
|   7   | Application  | Message                   |
|   6   | Presentation | Encoded Data              |
|   5   | Session      | Session Block             |
|   4   | Transport    | Segment(s)                |
|   3   | Network      | Packet                    |
|   2   | Data Link    | Frame                     |
|   1   | Physical     | Bits                      |
+-------+--------------+---------------------------+

Integration points
------------------
* **Layer 7** — creates :class:`EmergencyMessage` payloads.
* **Layer 6** — UTF-8 encoding / decoding + base-64-style hex encoding.
* **Layer 5** — session lifecycle (OPEN → ACTIVE → CLOSE).
* **Layer 4** — segments long messages, optionally runs Go-Back-N ARQ.
* **Layer 3** — Dijkstra path-finding over the emergency network.
* **Layer 2** — frames with CRC-4 error detection.
* **Layer 1** — bit transmission with link-availability and latency model.

Usage
-----
::

    from app.simulation.osi_model import OSIStack, build_osi_network
    from app.algorithms.network_topology import build_sample_network

    net   = build_sample_network()
    stack = OSIStack(network=net)

    result = stack.send(
        message="MAYDAY: building collapse at grid 4-F",
        source_id="ECC-01",
        dest_id="AMB-01",
        priority="HIGH",
    )
    for step in result.send_steps:
        print(step.layer_name, "→", step.action, "|", step.output_summary)
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.algorithms.crc import CRCEngine
from app.algorithms.dijkstra import dijkstra
from app.algorithms.go_back_n import GBNSimulator
from app.algorithms.network_topology import EmergencyNetwork, build_sample_network


# ─────────────────────────────────────────────────────────────────────────────
# Constants / presets
# ─────────────────────────────────────────────────────────────────────────────

CRC_GENERATOR   = "10011"          # CRC-4 for Data Link layer
SEGMENT_SIZE    = 32               # bytes per Transport segment
GBN_WINDOW      = 3
GBN_TIMEOUT     = 4


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class LayerNumber(int, Enum):
    PHYSICAL     = 1
    DATA_LINK    = 2
    NETWORK      = 3
    TRANSPORT    = 4
    SESSION      = 5
    PRESENTATION = 6
    APPLICATION  = 7


class LayerName(str, Enum):
    PHYSICAL     = "Physical"
    DATA_LINK    = "Data Link"
    NETWORK      = "Network"
    TRANSPORT    = "Transport"
    SESSION      = "Session"
    PRESENTATION = "Presentation"
    APPLICATION  = "Application"


class ProcessingStatus(str, Enum):
    SUCCESS   = "SUCCESS"
    WARNING   = "WARNING"   # e.g. CRC corrected / retransmission occurred
    ERROR     = "ERROR"     # e.g. CRC fail, link down, no route


class Direction(str, Enum):
    SEND    = "SEND"      # encapsulation (7 → 1)
    RECEIVE = "RECEIVE"   # decapsulation (1 → 7)


class Priority(str, Enum):
    LOW      = "LOW"
    NORMAL   = "NORMAL"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class SessionState(str, Enum):
    CLOSED = "CLOSED"
    OPEN   = "OPEN"
    ACTIVE = "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Layer step result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LayerStep:
    """
    Records everything that happened inside one OSI layer during processing.

    Attributes
    ----------
    layer_number : int
        1–7.
    layer_name : str
        Human-readable layer name.
    direction : Direction
        SEND (encapsulation) or RECEIVE (decapsulation).
    action : str
        Short verb phrase describing what this layer did.
    pdu_name : str
        Name of the Protocol Data Unit at this layer.
    input_data : Any
        The data handed *into* this layer.
    output_data : Any
        The data produced *by* this layer.
    output_summary : str
        One-line human-readable summary of ``output_data``.
    status : ProcessingStatus
        SUCCESS / WARNING / ERROR.
    details : dict
        Extra per-layer metadata (e.g. CRC remainder, path, segment count).
    error_message : str or None
        Populated only when status is ERROR or WARNING.
    """
    layer_number:   int
    layer_name:     str
    direction:      Direction
    action:         str
    pdu_name:       str
    input_data:     Any
    output_data:    Any
    output_summary: str
    status:         ProcessingStatus
    details:        Dict[str, Any] = field(default_factory=dict)
    error_message:  Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "layer_number":   self.layer_number,
            "layer_name":     self.layer_name,
            "direction":      self.direction.value,
            "action":         self.action,
            "pdu_name":       self.pdu_name,
            "output_summary": self.output_summary,
            "status":         self.status.value,
            "details":        self.details,
            "error_message":  self.error_message,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Emergency message
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EmergencyMessage:
    """
    Application-layer payload created at Layer 7.

    Attributes
    ----------
    content : str
        The human-readable emergency text.
    source_id : str
        Sending node ID.
    dest_id : str
        Destination node ID.
    priority : Priority
        Message urgency level.
    message_id : str
        SHA-256 derived short identifier.
    timestamp : float
        Unix timestamp (deterministic when overridden in tests).
    """
    content:    str
    source_id:  str
    dest_id:    str
    priority:   Priority
    message_id: str
    timestamp:  float

    def to_dict(self) -> dict:
        return {
            "content":    self.content,
            "source_id":  self.source_id,
            "dest_id":    self.dest_id,
            "priority":   self.priority.value,
            "message_id": self.message_id,
            "timestamp":  self.timestamp,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OSIResult:
    """
    Complete output of one :meth:`OSIStack.send` call.

    Attributes
    ----------
    message : EmergencyMessage
        The original application message.
    send_steps : list[LayerStep]
        Encapsulation steps, Layer 7 → Layer 1.
    receive_steps : list[LayerStep]
        Decapsulation steps, Layer 1 → Layer 7.
    delivered : bool
        True iff decapsulation completed without an ERROR step.
    path : list[str]
        Network path computed by Dijkstra (node IDs).
    total_cost : float
        Path cost from Dijkstra.
    errors : list[str]
        Aggregated error messages from all layers.
    warnings : list[str]
        Aggregated warning messages from all layers.
    """
    message:       EmergencyMessage
    send_steps:    List[LayerStep]
    receive_steps: List[LayerStep]
    delivered:     bool
    path:          List[str]
    total_cost:    float
    errors:        List[str]
    warnings:      List[str]

    def to_dict(self) -> dict:
        return {
            "message":       self.message.to_dict(),
            "delivered":     self.delivered,
            "path":          self.path,
            "total_cost":    self.total_cost,
            "errors":        self.errors,
            "warnings":      self.warnings,
            "send_steps":    [s.to_dict() for s in self.send_steps],
            "receive_steps": [s.to_dict() for s in self.receive_steps],
        }


# ─────────────────────────────────────────────────────────────────────────────
# OSI Stack
# ─────────────────────────────────────────────────────────────────────────────

class OSIStack:
    """
    Seven-layer OSI encapsulation / decapsulation pipeline.

    Parameters
    ----------
    network : EmergencyNetwork
        The topology used for Layer-3 routing.
    crc_generator : str, optional
        Binary generator polynomial for the Data Link layer (default CRC-4).
    segment_size : int, optional
        Maximum bytes per Transport segment (default 32).
    use_gbn : bool, optional
        If True, the Transport layer runs Go-Back-N ARQ simulation.
    gbn_lost_frames : set, optional
        ``{(seq, attempt)}`` pairs to drop in the GBN simulation.
    inject_physical_error : bool, optional
        If True, the Physical layer flips one bit to test error detection.
    inject_crc_error : bool, optional
        If True, flip a bit in the Data Link frame to trigger a CRC failure.
    fixed_timestamp : float, optional
        Override ``time.time()`` for deterministic test output.
    """

    def __init__(
        self,
        network:               EmergencyNetwork,
        crc_generator:         str   = CRC_GENERATOR,
        segment_size:          int   = SEGMENT_SIZE,
        use_gbn:               bool  = False,
        gbn_lost_frames:       Optional[set] = None,
        inject_physical_error: bool  = False,
        inject_crc_error:      bool  = False,
        fixed_timestamp:       Optional[float] = None,
    ) -> None:
        self._network               = network
        self._crc                   = CRCEngine(crc_generator)
        self._segment_size          = segment_size
        self._use_gbn               = use_gbn
        self._gbn_lost_frames       = gbn_lost_frames or set()
        self._inject_physical_error = inject_physical_error
        self._inject_crc_error      = inject_crc_error
        self._fixed_timestamp       = fixed_timestamp
        self._session_state         = SessionState.CLOSED
        self._session_id: Optional[str] = None

    # ── Public entry point ────────────────────────────────────────────────────

    def send(
        self,
        message:   str,
        source_id: str,
        dest_id:   str,
        priority:  str = "NORMAL",
    ) -> OSIResult:
        """
        Process *message* through all seven OSI layers (send + receive).

        Parameters
        ----------
        message : str
            Plain-text emergency message content.
        source_id : str
            Source node ID (must exist in the network).
        dest_id : str
            Destination node ID (must exist in the network).
        priority : str, optional
            One of ``LOW | NORMAL | HIGH | CRITICAL``.

        Returns
        -------
        OSIResult
        """
        try:
            prio = Priority(priority.upper())
        except ValueError:
            prio = Priority.NORMAL

        send_steps:    List[LayerStep] = []
        receive_steps: List[LayerStep] = []
        errors:        List[str]       = []
        warnings:      List[str]       = []

        # ── SEND: encapsulation 7 → 1 ─────────────────────────────────────────
        #
        # Each _send_layerN returns (output_data, LayerStep).
        # If a step has status ERROR we stop the pipeline early.

        # L7 — Application
        app_msg, l7 = self._send_l7(message, source_id, dest_id, prio)
        send_steps.append(l7)
        if l7.status == ProcessingStatus.ERROR:
            errors.append(l7.error_message)
            return self._abort(app_msg or EmergencyMessage(
                message, source_id, dest_id, prio, "ERR", 0.0),
                send_steps, receive_steps, errors, warnings)

        # L6 — Presentation
        encoded, l6 = self._send_l6(app_msg)
        send_steps.append(l6)

        # L5 — Session
        session_block, l5 = self._send_l5(encoded, source_id, dest_id)
        send_steps.append(l5)

        # L4 — Transport
        segments, l4 = self._send_l4(session_block)
        send_steps.append(l4)
        if l4.status == ProcessingStatus.WARNING:
            warnings.append(l4.error_message)

        # L3 — Network
        packet, l3 = self._send_l3(segments, source_id, dest_id)
        send_steps.append(l3)
        if l3.status == ProcessingStatus.ERROR:
            errors.append(l3.error_message)
            return self._abort(app_msg, send_steps, receive_steps, errors, warnings)

        path       = l3.details.get("path", [])
        total_cost = l3.details.get("total_cost", float("inf"))

        # L2 — Data Link
        frame, l2 = self._send_l2(packet)
        send_steps.append(l2)

        # L1 — Physical
        bits, l1 = self._send_l1(frame, source_id, dest_id)
        send_steps.append(l1)
        if l1.status == ProcessingStatus.ERROR:
            errors.append(l1.error_message)
            return self._abort(app_msg, send_steps, receive_steps, errors, warnings)

        # ── RECEIVE: decapsulation 1 → 7 ─────────────────────────────────────

        # L1 receive
        rx_frame, r1 = self._recv_l1(bits, source_id, dest_id)
        receive_steps.append(r1)
        if r1.status == ProcessingStatus.ERROR:
            errors.append(r1.error_message)
            return self._abort(app_msg, send_steps, receive_steps, errors, warnings)

        # L2 receive
        rx_packet, r2 = self._recv_l2(rx_frame)
        receive_steps.append(r2)
        if r2.status == ProcessingStatus.ERROR:
            errors.append(r2.error_message)
            return self._abort(app_msg, send_steps, receive_steps, errors, warnings)

        # L3 receive
        rx_segments, r3 = self._recv_l3(rx_packet)
        receive_steps.append(r3)

        # L4 receive
        rx_session, r4 = self._recv_l4(rx_segments)
        receive_steps.append(r4)

        # L5 receive
        rx_encoded, r5 = self._recv_l5(rx_session)
        receive_steps.append(r5)
        if r5.status == ProcessingStatus.ERROR:
            errors.append(r5.error_message)
            return self._abort(app_msg, send_steps, receive_steps, errors, warnings)

        # L6 receive
        rx_text, r6 = self._recv_l6(rx_encoded)
        receive_steps.append(r6)

        # L7 receive
        rx_msg, r7 = self._recv_l7(rx_text, app_msg)
        receive_steps.append(r7)

        delivered = all(
            s.status != ProcessingStatus.ERROR
            for s in send_steps + receive_steps
        )

        return OSIResult(
            message=app_msg,
            send_steps=send_steps,
            receive_steps=receive_steps,
            delivered=delivered,
            path=path,
            total_cost=total_cost,
            errors=errors,
            warnings=warnings,
        )

    # =========================================================================
    # SEND — encapsulation (Layer 7 → 1)
    # =========================================================================

    # ── Layer 7: Application ──────────────────────────────────────────────────

    def _send_l7(
        self,
        content:   str,
        source_id: str,
        dest_id:   str,
        priority:  Priority,
    ) -> Tuple[Optional[EmergencyMessage], LayerStep]:
        """
        Create an :class:`EmergencyMessage` from the raw content string.

        Actions
        -------
        * Validate source/dest nodes exist in the network.
        * Assign a message ID (SHA-256 of content+source+dest).
        * Stamp with timestamp.
        """
        # Validate nodes
        try:
            self._network.get_node(source_id)
            self._network.get_node(dest_id)
        except KeyError as exc:
            step = LayerStep(
                layer_number=7, layer_name="Application",
                direction=Direction.SEND,
                action="Create emergency message",
                pdu_name="Message",
                input_data=content,
                output_data=None,
                output_summary="FAILED — unknown node",
                status=ProcessingStatus.ERROR,
                error_message=str(exc),
            )
            return None, step

        ts = self._fixed_timestamp if self._fixed_timestamp is not None else time.time()
        msg_id = hashlib.sha256(
            f"{content}{source_id}{dest_id}{ts}".encode()
        ).hexdigest()[:12]

        msg = EmergencyMessage(
            content=content,
            source_id=source_id,
            dest_id=dest_id,
            priority=priority,
            message_id=msg_id,
            timestamp=ts,
        )

        src_name  = self._network.get_node(source_id).name
        dest_name = self._network.get_node(dest_id).name

        step = LayerStep(
            layer_number=7, layer_name="Application",
            direction=Direction.SEND,
            action="Create emergency message",
            pdu_name="Message",
            input_data=content,
            output_data=msg.to_dict(),
            output_summary=(
                f"[{priority.value}] {content[:40]}{'…' if len(content)>40 else ''} "
                f"| {src_name} → {dest_name} | id={msg_id}"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "message_id": msg_id,
                "priority":   priority.value,
                "source":     source_id,
                "dest":       dest_id,
            },
        )
        return msg, step

    # ── Layer 6: Presentation ─────────────────────────────────────────────────

    def _send_l6(self, msg: EmergencyMessage) -> Tuple[dict, LayerStep]:
        """
        Encode the message for transmission.

        Actions
        -------
        * UTF-8 encode the content → raw bytes.
        * Hex-encode for a printable wire format.
        * Attach metadata header (priority, message_id).
        """
        raw_bytes   = msg.content.encode("utf-8")
        hex_payload = raw_bytes.hex()
        b64_meta    = base64.b64encode(
            f"{msg.priority.value}:{msg.message_id}".encode()
        ).decode()

        encoded = {
            "encoding":    "utf-8+hex",
            "payload_hex": hex_payload,
            "meta_b64":    b64_meta,
            "byte_length": len(raw_bytes),
        }

        step = LayerStep(
            layer_number=6, layer_name="Presentation",
            direction=Direction.SEND,
            action="Encode message (UTF-8 → hex)",
            pdu_name="Encoded Data",
            input_data=msg.content,
            output_data=encoded,
            output_summary=(
                f"Encoded {len(raw_bytes)} bytes → {len(hex_payload)} hex chars "
                f"| meta={b64_meta[:16]}…"
            ),
            status=ProcessingStatus.SUCCESS,
            details={"byte_length": len(raw_bytes), "encoding": "utf-8+hex"},
        )
        return encoded, step

    # ── Layer 5: Session ──────────────────────────────────────────────────────

    def _send_l5(
        self, encoded: dict, source_id: str, dest_id: str
    ) -> Tuple[dict, LayerStep]:
        """
        Manage the session lifecycle.

        Actions
        -------
        * Open a new session (CLOSED → OPEN → ACTIVE).
        * Wrap the encoded data in a session block with session ID.
        """
        self._session_state = SessionState.OPEN
        self._session_id    = hashlib.md5(
            f"{source_id}{dest_id}{encoded['payload_hex'][:8]}".encode()
        ).hexdigest()[:8]
        self._session_state = SessionState.ACTIVE

        session_block = {
            "session_id":    self._session_id,
            "session_state": self._session_state.value,
            "source_id":     source_id,
            "dest_id":       dest_id,
            "payload":       encoded,
        }

        step = LayerStep(
            layer_number=5, layer_name="Session",
            direction=Direction.SEND,
            action="Open session & wrap payload",
            pdu_name="Session Block",
            input_data=encoded,
            output_data=session_block,
            output_summary=(
                f"Session {self._session_id} ACTIVE | "
                f"{source_id} ↔ {dest_id}"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "session_id":    self._session_id,
                "session_state": self._session_state.value,
            },
        )
        return session_block, step

    # ── Layer 4: Transport ────────────────────────────────────────────────────

    def _send_l4(self, session_block: dict) -> Tuple[List[dict], LayerStep]:
        """
        Segment the session block and optionally run Go-Back-N ARQ.

        Actions
        -------
        * Serialise session block to bytes.
        * Split into segments of at most ``segment_size`` bytes.
        * Attach sequence number to each segment.
        * If ``use_gbn=True``, run GBN simulation and report retransmissions.
        """
        import json
        raw   = json.dumps(session_block).encode("utf-8")
        segs  = [raw[i:i + self._segment_size]
                 for i in range(0, max(len(raw), 1), self._segment_size)]

        segments = [
            {
                "seq":     idx,
                "total":   len(segs),
                "payload": seg.hex(),
                "length":  len(seg),
            }
            for idx, seg in enumerate(segs)
        ]

        gbn_details: dict = {}
        status = ProcessingStatus.SUCCESS
        warn_msg: Optional[str] = None

        if self._use_gbn:
            gbn = GBNSimulator(
                total_frames=len(segments),
                window_size=GBN_WINDOW,
                timeout_ticks=GBN_TIMEOUT,
                lost_frames=self._gbn_lost_frames,
            )
            gbn_result = gbn.run()
            gbn_details = {
                "gbn_total_transmissions": gbn_result.total_transmissions,
                "gbn_total_timeouts":      gbn_result.total_timeouts,
                "gbn_delivered":           len(gbn_result.delivered_in_order),
                "gbn_window_size":         GBN_WINDOW,
            }
            if gbn_result.total_timeouts > 0:
                status   = ProcessingStatus.WARNING
                warn_msg = (
                    f"GBN: {gbn_result.total_timeouts} timeout(s), "
                    f"{gbn_result.total_transmissions} total transmissions "
                    f"for {len(segments)} segment(s)."
                )

        step = LayerStep(
            layer_number=4, layer_name="Transport",
            direction=Direction.SEND,
            action="Segment payload" + (" + GBN ARQ" if self._use_gbn else ""),
            pdu_name="Segment(s)",
            input_data=session_block,
            output_data=segments,
            output_summary=(
                f"{len(segments)} segment(s) × ≤{self._segment_size}B"
                + (f" | GBN: {gbn_details.get('gbn_total_transmissions', 0)} tx" if self._use_gbn else "")
            ),
            status=status,
            details={"segment_count": len(segments), "segment_size": self._segment_size, **gbn_details},
            error_message=warn_msg,
        )
        return segments, step

    # ── Layer 3: Network ──────────────────────────────────────────────────────

    def _send_l3(
        self, segments: List[dict], source_id: str, dest_id: str
    ) -> Tuple[Optional[dict], LayerStep]:
        """
        Address and route the segments using Dijkstra.

        Actions
        -------
        * Run Dijkstra on the current network topology.
        * Wrap segments in a packet with source/dest IP-style addressing.
        * Fail if destination is unreachable.
        """
        dj_result = dijkstra(self._network, source_id, dest_id)

        if not dj_result.reachable:
            step = LayerStep(
                layer_number=3, layer_name="Network",
                direction=Direction.SEND,
                action="Route packet",
                pdu_name="Packet",
                input_data=segments,
                output_data=None,
                output_summary=f"NO ROUTE from {source_id} to {dest_id}",
                status=ProcessingStatus.ERROR,
                details={"source": source_id, "dest": dest_id},
                error_message=f"Network layer: no route from '{source_id}' to '{dest_id}'.",
            )
            return None, step

        packet = {
            "source_addr": source_id,
            "dest_addr":   dest_id,
            "ttl":         64,
            "path":        dj_result.path,
            "route_cost":  dj_result.total_cost,
            "hop_count":   len(dj_result.path) - 1,
            "payload":     segments,
        }

        step = LayerStep(
            layer_number=3, layer_name="Network",
            direction=Direction.SEND,
            action="Route packet (Dijkstra)",
            pdu_name="Packet",
            input_data=segments,
            output_data=packet,
            output_summary=(
                f"{source_id} → {dest_id} | path={' → '.join(dj_result.path)} "
                f"| cost={dj_result.total_cost}"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "path":       dj_result.path,
                "total_cost": dj_result.total_cost,
                "hop_count":  len(dj_result.path) - 1,
                "ttl":        64,
            },
        )
        return packet, step

    # ── Layer 2: Data Link ────────────────────────────────────────────────────

    def _send_l2(self, packet: dict) -> Tuple[dict, LayerStep]:
        """
        Frame the packet and attach a CRC checksum.

        Actions
        -------
        * Serialise packet to a hex bitstring representation.
        * Compute CRC checksum via :class:`CRCEngine`.
        * Optionally corrupt one bit (inject_crc_error flag).
        * Build the frame: preamble + payload + CRC.
        """
        import json
        raw_hex  = json.dumps(packet).encode().hex()
        # Convert hex string to binary string for CRC
        dataword = bin(int(raw_hex, 16))[2:].zfill(len(raw_hex) * 4)
        # Truncate to a safe length for CRC demo (CRC works on the first 64 bits)
        crc_data = dataword[:64].ljust(64, "0")

        crc_result = self._crc.generate(crc_data)
        codeword   = crc_result.codeword

        if self._inject_crc_error:
            err_result = self._crc.inject_errors(codeword, [0])
            codeword   = err_result.corrupted

        frame = {
            "preamble":  "10101010",
            "src_mac":   packet["source_addr"],
            "dst_mac":   packet["dest_addr"],
            "payload_hex": raw_hex[:128] + ("…" if len(raw_hex) > 128 else ""),
            "crc_checksum": crc_result.remainder,
            "codeword_sample": codeword[:32] + "…",
            "frame_size_bytes": len(raw_hex) // 2 + self._crc.checksum_length,
            "_raw_codeword": codeword,   # kept for L1 transmission
            "_raw_hex":      raw_hex,    # kept for L2 receive
        }

        step = LayerStep(
            layer_number=2, layer_name="Data Link",
            direction=Direction.SEND,
            action="Frame packet + CRC",
            pdu_name="Frame",
            input_data=packet,
            output_data=frame,
            output_summary=(
                f"Frame {frame['src_mac']}→{frame['dst_mac']} "
                f"| CRC={crc_result.remainder} "
                f"| size≈{frame['frame_size_bytes']}B"
                + (" [CRC ERROR INJECTED]" if self._inject_crc_error else "")
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "crc_remainder": crc_result.remainder,
                "frame_size":    frame["frame_size_bytes"],
                "crc_injected":  self._inject_crc_error,
            },
        )
        return frame, step

    # ── Layer 1: Physical ─────────────────────────────────────────────────────

    def _send_l1(
        self, frame: dict, source_id: str, dest_id: str
    ) -> Tuple[Optional[dict], LayerStep]:
        """
        Transmit bits over the physical link.

        Actions
        -------
        * Check the direct link between source and first-hop (or source→dest).
        * Extract bandwidth and latency from the link.
        * Convert frame to a bit-level representation.
        * Optionally inject a random physical bit error.
        """
        # Use the first hop of the network path if available; otherwise direct
        try:
            dj = dijkstra(self._network, source_id, dest_id)
            first_hop = dj.path[1] if len(dj.path) > 1 else dest_id
            link = self._network.get_link(source_id, first_hop)
        except (KeyError, IndexError):
            step = LayerStep(
                layer_number=1, layer_name="Physical",
                direction=Direction.SEND,
                action="Transmit bits",
                pdu_name="Bits",
                input_data=frame,
                output_data=None,
                output_summary="LINK DOWN — no physical link available",
                status=ProcessingStatus.ERROR,
                error_message="Physical layer: no operational link from source.",
            )
            return None, step

        if not link.is_operational:
            step = LayerStep(
                layer_number=1, layer_name="Physical",
                direction=Direction.SEND,
                action="Transmit bits",
                pdu_name="Bits",
                input_data=frame,
                output_data=None,
                output_summary=f"LINK DOWN ({source_id}→{first_hop})",
                status=ProcessingStatus.ERROR,
                error_message=f"Physical layer: link {source_id}→{first_hop} is disabled.",
            )
            return None, step

        bitstream = frame["_raw_codeword"]
        if self._inject_physical_error and len(bitstream) > 4:
            inj = self._crc.inject_errors(bitstream, [4])
            bitstream = inj.corrupted

        bits_payload = {
            "bitstream_sample": bitstream[:48] + ("…" if len(bitstream) > 48 else ""),
            "total_bits":       len(bitstream),
            "bandwidth_mbps":   link.bandwidth_mbps,
            "latency_ms":       link.latency_ms,
            "link":             f"{source_id}→{first_hop}",
            "link_status":      link.status.value,
            "_raw_codeword":    bitstream,
        }

        step = LayerStep(
            layer_number=1, layer_name="Physical",
            direction=Direction.SEND,
            action="Transmit bits over physical medium",
            pdu_name="Bits",
            input_data=frame,
            output_data=bits_payload,
            output_summary=(
                f"{len(bitstream)} bits | BW={link.bandwidth_mbps} Mbps "
                f"| latency={link.latency_ms} ms | link={source_id}→{first_hop}"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "total_bits":     len(bitstream),
                "bandwidth_mbps": link.bandwidth_mbps,
                "latency_ms":     link.latency_ms,
                "link":           f"{source_id}→{first_hop}",
            },
        )
        return bits_payload, step

    # =========================================================================
    # RECEIVE — decapsulation (Layer 1 → 7)
    # =========================================================================

    # ── Layer 1: Physical (receive) ───────────────────────────────────────────

    def _recv_l1(
        self, bits: dict, source_id: str, dest_id: str
    ) -> Tuple[Optional[str], LayerStep]:
        """Receive raw bits and pass the codeword up to Data Link."""
        codeword = bits.get("_raw_codeword", "")
        step = LayerStep(
            layer_number=1, layer_name="Physical",
            direction=Direction.RECEIVE,
            action="Receive bits from medium",
            pdu_name="Bits",
            input_data=bits.get("bitstream_sample", ""),
            output_data=codeword,
            output_summary=(
                f"Received {bits.get('total_bits', 0)} bits | "
                f"latency={bits.get('latency_ms', 0)} ms"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "total_bits": bits.get("total_bits", 0),
                "latency_ms": bits.get("latency_ms", 0),
            },
        )
        return codeword, step

    # ── Layer 2: Data Link (receive) ──────────────────────────────────────────

    def _recv_l2(self, codeword: str) -> Tuple[Optional[dict], LayerStep]:
        """
        Verify CRC and extract the packet from the frame.

        If CRC verification fails, return an ERROR step and no packet.
        """
        import json

        verify = self._crc.verify(codeword)

        if not verify.valid:
            step = LayerStep(
                layer_number=2, layer_name="Data Link",
                direction=Direction.RECEIVE,
                action="Deframe + CRC verify",
                pdu_name="Frame",
                input_data=codeword[:32] + "…",
                output_data=None,
                output_summary=f"CRC FAILED — syndrome={verify.syndrome}",
                status=ProcessingStatus.ERROR,
                details={"syndrome": verify.syndrome},
                error_message=f"Data Link: CRC check failed (syndrome={verify.syndrome}). Frame discarded.",
            )
            return None, step

        # CRC passed — recover the original frame metadata stored during send
        # In a real stack the raw_hex would be re-parsed; here we reconstruct
        # from the stored _raw_hex inside the codeword context.
        # Since this is a simulation, we read the raw_hex from the codeword
        # (the codeword encodes the first 64 bits; full payload is in raw_hex).
        # We propagate the packet by re-creating it from stored data.
        raw_hex = getattr(self, "_last_raw_hex", None)
        if raw_hex is None:
            # fallback: just signal success with no packet content (harmless for tests)
            packet = {"source_addr": "?", "dest_addr": "?", "payload": []}
        else:
            try:
                packet = json.loads(bytes.fromhex(raw_hex).decode("utf-8"))
            except Exception:
                packet = {"source_addr": "?", "dest_addr": "?", "payload": []}

        step = LayerStep(
            layer_number=2, layer_name="Data Link",
            direction=Direction.RECEIVE,
            action="Deframe + CRC verify",
            pdu_name="Frame",
            input_data=codeword[:32] + "…",
            output_data=packet,
            output_summary=f"CRC OK (syndrome all-zeros) | packet extracted",
            status=ProcessingStatus.SUCCESS,
            details={"syndrome": verify.syndrome, "crc_valid": True},
        )
        return packet, step

    # ── Layer 3: Network (receive) ────────────────────────────────────────────

    def _recv_l3(self, packet: dict) -> Tuple[List[dict], LayerStep]:
        """Strip network header and pass segments to Transport."""
        segments = packet.get("payload", [])
        step = LayerStep(
            layer_number=3, layer_name="Network",
            direction=Direction.RECEIVE,
            action="Deliver packet to destination",
            pdu_name="Packet",
            input_data=packet,
            output_data=segments,
            output_summary=(
                f"Delivered to {packet.get('dest_addr', '?')} | "
                f"{len(segments)} segment(s)"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "dest_addr": packet.get("dest_addr"),
                "hop_count": packet.get("hop_count", 0),
            },
        )
        return segments, step

    # ── Layer 4: Transport (receive) ──────────────────────────────────────────

    def _recv_l4(self, segments: List[dict]) -> Tuple[Optional[dict], LayerStep]:
        """Reassemble segments into the session block."""
        import json

        if not segments:
            # No segments — reconstruct empty session block
            session_block = {}
            step = LayerStep(
                layer_number=4, layer_name="Transport",
                direction=Direction.RECEIVE,
                action="Reassemble segments",
                pdu_name="Segment(s)",
                input_data=[],
                output_data={},
                output_summary="0 segments reassembled (empty payload)",
                status=ProcessingStatus.SUCCESS,
                details={"segment_count": 0},
            )
            return session_block, step

        # Re-join hex payloads in sequence order
        sorted_segs = sorted(segments, key=lambda s: s.get("seq", 0))
        raw_bytes   = b"".join(bytes.fromhex(s["payload"]) for s in sorted_segs)
        try:
            session_block = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            session_block = {}

        step = LayerStep(
            layer_number=4, layer_name="Transport",
            direction=Direction.RECEIVE,
            action="Reassemble segments",
            pdu_name="Segment(s)",
            input_data=segments,
            output_data=session_block,
            output_summary=(
                f"{len(segments)} segment(s) reassembled → "
                f"{len(raw_bytes)} bytes"
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "segment_count": len(segments),
                "reassembled_bytes": len(raw_bytes),
            },
        )
        return session_block, step

    # ── Layer 5: Session (receive) ────────────────────────────────────────────

    def _recv_l5(self, session_block: dict) -> Tuple[Optional[dict], LayerStep]:
        """Validate session ID and close the session."""
        sid = session_block.get("session_id", None)

        if sid != self._session_id:
            step = LayerStep(
                layer_number=5, layer_name="Session",
                direction=Direction.RECEIVE,
                action="Validate & close session",
                pdu_name="Session Block",
                input_data=session_block,
                output_data=None,
                output_summary=f"SESSION MISMATCH: got {sid}, expected {self._session_id}",
                status=ProcessingStatus.ERROR,
                error_message=f"Session layer: session ID mismatch ({sid} ≠ {self._session_id}).",
            )
            return None, step

        encoded = session_block.get("payload", {})
        self._session_state = SessionState.CLOSED

        step = LayerStep(
            layer_number=5, layer_name="Session",
            direction=Direction.RECEIVE,
            action="Validate & close session",
            pdu_name="Session Block",
            input_data=session_block,
            output_data=encoded,
            output_summary=f"Session {sid} validated → CLOSED | payload extracted",
            status=ProcessingStatus.SUCCESS,
            details={
                "session_id":    sid,
                "session_state": SessionState.CLOSED.value,
            },
        )
        return encoded, step

    # ── Layer 6: Presentation (receive) ──────────────────────────────────────

    def _recv_l6(self, encoded: dict) -> Tuple[str, LayerStep]:
        """Decode hex-encoded payload back to UTF-8 text."""
        try:
            text = bytes.fromhex(encoded.get("payload_hex", "")).decode("utf-8")
        except Exception:
            text = ""

        step = LayerStep(
            layer_number=6, layer_name="Presentation",
            direction=Direction.RECEIVE,
            action="Decode payload (hex → UTF-8)",
            pdu_name="Encoded Data",
            input_data=encoded,
            output_data=text,
            output_summary=("Decoded " + str(len(text)) + " chars: \"" + text[:50] + ("..." if len(text) > 50 else "") + "\""),
            status=ProcessingStatus.SUCCESS,
            details={"decoded_length": len(text), "encoding": "utf-8+hex"},
        )
        return text, step

    # ── Layer 7: Application (receive) ────────────────────────────────────────

    def _recv_l7(
        self, text: str, original: EmergencyMessage
    ) -> Tuple[EmergencyMessage, LayerStep]:
        """Deliver decoded text to the application as an EmergencyMessage."""
        matches = text == original.content
        rx_msg  = EmergencyMessage(
            content=text,
            source_id=original.source_id,
            dest_id=original.dest_id,
            priority=original.priority,
            message_id=original.message_id,
            timestamp=original.timestamp,
        )

        step = LayerStep(
            layer_number=7, layer_name="Application",
            direction=Direction.RECEIVE,
            action="Deliver message to application",
            pdu_name="Message",
            input_data=text,
            output_data=rx_msg.to_dict(),
            output_summary=(
                ("Message delivered "
                 + ("✓ intact" if matches else "✗ MISMATCH") + ": "
                 + '"' + text[:50] + ("..." if len(text) > 50 else "") + '"')
            ),
            status=ProcessingStatus.SUCCESS if matches else ProcessingStatus.WARNING,
            details={"content_matches": matches},
            error_message=None if matches else "Received content differs from sent content.",
        )
        return rx_msg, step

    # ── Pipeline helpers ──────────────────────────────────────────────────────

    def _abort(
        self,
        msg: EmergencyMessage,
        send_steps: List[LayerStep],
        receive_steps: List[LayerStep],
        errors: List[str],
        warnings: List[str],
    ) -> OSIResult:
        """Return an OSIResult marked as not delivered."""
        return OSIResult(
            message=msg,
            send_steps=send_steps,
            receive_steps=receive_steps,
            delivered=False,
            path=[],
            total_cost=float("inf"),
            errors=errors,
            warnings=warnings,
        )

    # ── Internal hook used by _recv_l2 to recover full raw_hex ───────────────
    # In a real stack the entire serialised frame travels as bits; here we
    # take a shortcut and store the raw_hex during _send_l2 so receive can
    # recover it.  This is an acknowledged simulation simplification.

    def _send_l2(self, packet: dict) -> Tuple[dict, LayerStep]:  # noqa: F811
        frame, step = super()._send_l2(packet) if False else (None, None)
        # Re-implement here so we can store _last_raw_hex
        import json
        raw_hex  = json.dumps(packet).encode().hex()
        self._last_raw_hex = raw_hex  # stash for receive path

        dataword   = bin(int(raw_hex, 16))[2:].zfill(len(raw_hex) * 4)
        crc_data   = dataword[:64].ljust(64, "0")
        crc_result = self._crc.generate(crc_data)
        codeword   = crc_result.codeword

        if self._inject_crc_error:
            err_result = self._crc.inject_errors(codeword, [0])
            codeword   = err_result.corrupted

        frame = {
            "preamble":          "10101010",
            "src_mac":           packet["source_addr"],
            "dst_mac":           packet["dest_addr"],
            "payload_hex":       raw_hex[:128] + ("…" if len(raw_hex) > 128 else ""),
            "crc_checksum":      crc_result.remainder,
            "codeword_sample":   codeword[:32] + "…",
            "frame_size_bytes":  len(raw_hex) // 2 + self._crc.checksum_length,
            "_raw_codeword":     codeword,
            "_raw_hex":          raw_hex,
        }

        step = LayerStep(
            layer_number=2, layer_name="Data Link",
            direction=Direction.SEND,
            action="Frame packet + CRC",
            pdu_name="Frame",
            input_data=packet,
            output_data=frame,
            output_summary=(
                f"Frame {frame['src_mac']}→{frame['dst_mac']} "
                f"| CRC={crc_result.remainder} "
                f"| size≈{frame['frame_size_bytes']}B"
                + (" [CRC ERROR INJECTED]" if self._inject_crc_error else "")
            ),
            status=ProcessingStatus.SUCCESS,
            details={
                "crc_remainder": crc_result.remainder,
                "frame_size":    frame["frame_size_bytes"],
                "crc_injected":  self._inject_crc_error,
            },
        )
        return frame, step


# ─────────────────────────────────────────────────────────────────────────────
# Convenience factory
# ─────────────────────────────────────────────────────────────────────────────

def build_osi_network() -> EmergencyNetwork:
    """Return the standard ResQNet sample emergency network."""
    return build_sample_network()
