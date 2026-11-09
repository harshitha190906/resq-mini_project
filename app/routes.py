"""
ResQNet — app/routes.py
========================
Flask blueprint that connects the educational simulation modules to HTTP
JSON endpoints.
"""

from __future__ import annotations

from flask import Blueprint, Flask, jsonify, request, current_app, render_template, Response, make_response
from werkzeug.exceptions import BadRequest, NotFound

from app.algorithms.dijkstra import dijkstra
from app.algorithms.distance_vector import DistanceVectorRouter
from app.algorithms.crc import CRCEngine
from app.algorithms.go_back_n import GBNSimulator, parse_lost_frames_input, GBNResult, GBNEventType
from app.algorithms.leaky_bucket import LeakyBucket
from app.services.dv_service import service as dv_service
from app.services.leaky_bucket_service import service as leaky_bucket_service
from app.services.history_service import history_service
from app.services.congestion_service import congestion_service
from app.services.analytics_service import analytics_service

# ── Compatibility shims ──────────────────────────────────────────────────────

def distance_vector(network):
    """Run Distance-Vector routing on *network* and return all routing tables
    serialised as a dict ``{node_id: [{dest, next_hop, cost, reachable}, ...]}`.
    """
    router = DistanceVectorRouter(network)
    router.run()
    return {node_id: [e.to_dict() for e in table.values()]
            for node_id, table in router.all_routing_tables().items()}


def compute_crc(data_bits: str, generator: str) -> str:
    """Return the CRC remainder (checksum) for *data_bits*."""
    return CRCEngine(generator).generate(data_bits).remainder


def verify_crc(received_bits: str, generator: str) -> bool:
    """Return *True* if the received codeword has a zero syndrome."""
    return CRCEngine(generator).verify(received_bits).valid


from app.algorithms.network_topology import (
    build_sample_network,
    EmergencyNetwork,
    resolve_node_id,
)

from app.simulation.engine import SimulationEngine, TrafficLevel
from app.simulation.metrics import SimulationMetrics
from app.simulation.osi_model import OSIStack, build_osi_network

# ---------------------------------------------------------------------------
# Global service container – keeps state between requests without polluting the
# route functions. In a real service you would use a proper dependency‑injection
# framework or external store.
# ---------------------------------------------------------------------------
class ServiceContainer:
    def __init__(self) -> None:
        self.network: EmergencyNetwork = build_sample_network()
        self.engine: SimulationEngine = SimulationEngine(network=self.network)
        self.last_osi_result = None  # type: ignore[assignment]
        self.gbn_result: Optional[GBNResult] = None
        self.gbn_step_index: int = 0

    def reset_engine(self, **engine_kwargs) -> None:
        self.engine = SimulationEngine(network=self.network, **engine_kwargs)

    def reset_all(self) -> None:
        self.network = build_sample_network()
        self.reset_engine()
        self.last_osi_result = None
        self.gbn_result = None
        self.gbn_step_index = 0

# One shared instance – Flask creates a single process for the dev server.
services = ServiceContainer()

# Blueprint registration
main = Blueprint("main", __name__)

# ------------------------------- Helper utilities -------------------------------

# ------------------------------- Page Endpoints -----------------------------------
@main.route('/')
def dashboard():
    """Render the main overview dashboard page."""
    return render_template('dashboard.html')

@main.route('/topology')
def topology():
    """Render the network topology explorer page."""
    return render_template('topology.html')

@main.route('/osi_explorer')
def osi_explorer():
    """Render the OSI layer explorer page."""
    return render_template('osi_explorer.html')

@main.route('/routing')
def routing():
    """Render the routing simulation page."""
    return render_template('routing.html')

@main.route('/reliability')
def reliability():
    """Render the error recovery (reliability) page."""
    return render_template('reliability.html')

@main.route('/congestion')
def congestion():
    """Render the congestion control page."""
    return render_template('congestion.html')

@main.route('/analytics')
def analytics():
    """Render the performance analytics page."""
    return render_template('analytics.html')

@main.route('/history')
def history():
    """Render the simulation history page."""
    return render_template('history.html')

def _json_error(message: str, status_code: int = 400):
    response = jsonify({"error": message})
    response.status_code = status_code
    return response

def _require_json_keys(data: dict, *keys: str):
    missing = [k for k in keys if k not in data]
    if missing:
        raise BadRequest(f"Missing required fields: {', '.join(missing)}")

# ------------------------------- Endpoints -----------------------------------
@main.route("/api/health", methods=["GET"])  # noqa: D401
def health():
    """Simple health‑check endpoint.

    Returns
    -------
    JSON with ``{"status": "ok"}``.
    """
    return jsonify({"status": "ok"})

@main.route("/api/topology", methods=["GET"])  # noqa: D401
def api_topology():
    """Return the current network topology as a serialisable dict with rich metadata."""
    net = services.network
    nodes_data = [
        {
            "node_id":     n.node_id,
            "id":          n.node_id,
            "name":        n.name,
            "node_type":   n.node_type.value,
            "type":        n.node_type.value,
            "x":           n.x,
            "y":           n.y,
            "description": n.description,
        }
        for n in net.list_nodes()
    ]
    links_data = [
        {
            "source_id":      l.source_id,
            "target_id":      l.target_id,
            "u":              l.source_id,
            "v":              l.target_id,
            "cost":           l.cost,
            "bandwidth_mbps": l.bandwidth_mbps,
            "latency_ms":     l.latency_ms,
            "delay_ms":       l.latency_ms,
            "queue_capacity": l.queue_capacity,
            "status":         l.status.value,
            "is_active":      l.is_operational,
        }
        for l in net.list_links()
    ]

    def _get_link_status(u: str, v: str) -> bool:
        try:
            return net.get_link(u, v).is_operational
        except KeyError:
            return False

    predefined_links = [
        {
            "id":        "btnFailLink1",
            "name":      "POL ↔ ECC (Primary Command Link)",
            "node_a":    "PS-01",
            "node_b":    "ECC-01",
            "alias_a":   "POL",
            "alias_b":   "ECC",
            "is_active": _get_link_status("PS-01", "ECC-01"),
        },
        {
            "id":        "btnFailLink2",
            "name":      "POL ↔ R1 (North Relay Link)",
            "node_a":    "PS-01",
            "node_b":    "RTR-01",
            "alias_a":   "POL",
            "alias_b":   "R1",
            "is_active": _get_link_status("PS-01", "RTR-01"),
        },
        {
            "id":        "btnFailLink3",
            "name":      "FIRE ↔ R2 (East Sector Relay)",
            "node_a":    "FS-01",
            "node_b":    "RTR-02",
            "alias_a":   "FIRE",
            "alias_b":   "R2",
            "is_active": _get_link_status("FS-01", "RTR-02"),
        },
    ]

    active_count = sum(1 for l in links_data if l["is_active"])
    failed_count = sum(1 for l in links_data if not l["is_active"])
    summary = {
        "total_nodes":  len(nodes_data),
        "total_links":  len(links_data),
        "active_links": active_count,
        "failed_links": failed_count,
    }

    return jsonify({
        "nodes":            nodes_data,
        "links":            links_data,
        "edges":            links_data,
        "predefined_links": predefined_links,
        "summary":          summary,
        "total_nodes":      len(nodes_data),
        "total_links":      len(links_data),
        "active_links":     active_count,
        "failed_links":     failed_count,
    })

def _run_default_simulation_workload(count: int = 20) -> List[PacketEvent]:
    """Execute realistic emergency communication packet workload across disaster network."""
    scenarios = [
        ("SHL-01", "ECC-01", "Civilian Shelter Status & Medical Supply Requisition", 512, "HIGH"),
        ("AMB-01", "ECC-01", "Patient Triage & Critical Care Evacuation Telemetry",  768, "CRITICAL"),
        ("FT-01",  "PS-01",  "Flood Sector Perimeter Search & Rescue Progress",       384, "NORMAL"),
        ("FS-01",  "ECC-01", "Hazard Containment & Gas Leak Suppression Report",      640, "HIGH"),
        ("ECC-01", "AMB-01", "Ambulance Unit Dispatch Order for Sector Bravo",        256, "CRITICAL"),
        ("SHL-01", "FT-01",  "Shelter Perimeter Security & Escort Status",            320, "NORMAL"),
        ("PS-01",  "ECC-01", "Downtown Evacuation Route Clearance Confirmation",      512, "HIGH"),
        ("ECC-01", "FS-01",  "Fire & Rescue Secondary Water Pump Coordination",        400, "HIGH"),
    ]

    events = []
    for i in range(count):
        src, dst, msg, size, priority = scenarios[i % len(scenarios)]
        ev = services.engine.send_packet(
            src=src,
            dst=dst,
            message=f"{msg} [Seq #{i+1}]",
            size_bytes=size,
            priority=priority,
        )
        events.append(ev)
        services.engine.current_time += services.engine.traffic_level.inter_arrival

    return events

@main.route("/api/messages/send", methods=["POST"])  # noqa: D401
def send_message():
    data = request.get_json(silent=True) or {}
    try:
        _require_json_keys(data, "src", "dst", "message")
        src = resolve_node_id(data["src"])
        dst = resolve_node_id(data["dst"])
        msg = data["message"]
        size = data.get("size_bytes")
        priority = data.get("priority", "NORMAL")
        ev = services.engine.send_packet(src, dst, msg, size, priority)
    except BadRequest as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:  # pragma: no cover – unexpected error
        return _json_error(str(exc), 500)
    # Convert PacketEvent to a dict for JSON output
    ev_dict = {
        "packet_id": ev.packet_id,
        "src": ev.src,
        "dst": ev.dst,
        "size_bytes": ev.size_bytes,
        "route": ev.route,
        "timestamps": ev.timestamps,
        "delivered": ev.delivered,
        "loss_reason": ev.loss_reason,
        "retransmissions": ev.retransmissions,
        "priority": ev.priority,
    }
    return jsonify(ev_dict)

@main.route("/api/simulation/start", methods=["POST"])  # noqa: D401
@main.route("/api/simulation/run", methods=["POST"])
@main.route("/simulate", methods=["POST"])
def simulation_start():
    """Create a fresh ``SimulationEngine`` and execute realistic emergency traffic workload.

    Accepted JSON fields:
    * ``traffic_level`` – ``low``, ``medium`` or ``high`` (default low)
    * ``packet_size_bytes`` – integer (default 1024)
    * ``enable_gbn`` – boolean (default false)
    * ``gbn_lost_frames`` – list of ``[seq, attempt]`` pairs
    * ``count`` / ``num_packets`` – integer packet count (default 20)
    """
    data = request.get_json(silent=True) or {}
    try:
        level = TrafficLevel(data.get("traffic_level", "low"))
        size = data.get("packet_size_bytes", 1024)
        enable_gbn = data.get("enable_gbn", False)
        lost_frames = data.get("gbn_lost_frames")
        if lost_frames is not None:
            # Convert list of lists/tuples into a set of tuples of ints
            lost_frames = {tuple(map(int, pair)) for pair in lost_frames}
        services.reset_engine(
            traffic_level=level,
            packet_size_bytes=size,
            enable_gbn=enable_gbn,
            gbn_lost_frames=lost_frames,
        )

        packet_count = int(data.get("num_packets") or data.get("count") or 20)
        events = _run_default_simulation_workload(count=packet_count)
        metrics = SimulationMetrics(events=services.engine.events)

        # Record to persistent history
        sim_status = "SUCCESS" if metrics.total_lost == 0 else "COMPLETED_WITH_LOSS"
        history_service.record_simulation(
            algorithm="Emergency Traffic Engine",
            packets_sent=len(events),
            packets_delivered=metrics.total_delivered,
            packets_lost=metrics.total_lost,
            avg_delay_ms=metrics.avg_delay_ms,
            throughput_kbps=metrics.throughput_kbps,
            status=sim_status,
            parameters={"traffic_level": level.value, "count": packet_count, "enable_gbn": enable_gbn},
            details={"retransmissions": metrics.total_retransmissions, "duration_s": metrics.simulation_duration}
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:  # pragma: no cover
        return _json_error(str(exc), 500)
    return jsonify({
        "status":        "engine_started",
        "traffic_level": level.value,
        "packets_sent":  len(events),
        "message":       f"Simulation completed: {len(events)} packets transmitted across emergency network.",
        "metrics":       metrics.as_dict(),
    })

@main.route("/api/simulation/reset", methods=["POST"])  # noqa: D401
@main.route("/reset", methods=["POST"])
def simulation_reset():
    """Reset the whole simulation state (network + engine events)."""
    services.reset_engine()
    services.engine.events.clear()
    services.engine.current_time = 0.0
    services.last_osi_result = None
    return jsonify({"status": "reset_complete"})

@main.route("/api/routing/dijkstra", methods=["POST"])  # noqa: D401
def routing_dijkstra():
    data = request.get_json(silent=True) or {}
    try:
        raw_src = data.get("src") or data.get("source")
        raw_dst = data.get("dst") or data.get("destination") or data.get("target")
        if not raw_src or not raw_dst:
            raise BadRequest("Missing required fields: source/src and destination/dst.")

        src = resolve_node_id(str(raw_src).strip())
        dst = resolve_node_id(str(raw_dst).strip())

        result = dijkstra(services.network, src, dst)
        path_names = [services.network.get_node(nid).name for nid in result.path]
    except (KeyError, BadRequest) as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        return _json_error(str(exc), 500)

    res_dict = result.to_dict()
    res_dict["path_names"] = path_names

    # Record into persistent history
    history_service.record_simulation(
        algorithm="Dijkstra Routing",
        packets_sent=len(result.path) if result.path else 1,
        packets_delivered=len(result.path) if result.path else 0,
        packets_lost=0 if result.path else 1,
        avg_delay_ms=result.total_delay_ms,
        throughput_kbps=round((result.bottleneck_bw_mbps or 0.0) * 1000.0, 2),
        status="SUCCESS" if result.path else "FAILED",
        parameters={"source": src, "destination": dst, "algorithm": "Dijkstra"},
        details=res_dict
    )

    return jsonify(res_dict)

@main.route("/api/routing/distance-vector", methods=["POST"])  # noqa: D401
def routing_distance_vector():
    data = request.get_json(silent=True) or {}
    try:
        raw_src = data.get("src") or data.get("source")
        raw_dst = data.get("dst") or data.get("destination") or data.get("target")
        if not raw_src or not raw_dst:
            raise BadRequest("Missing required fields: source/src and destination/dst.")

        src = resolve_node_id(str(raw_src).strip())
        dst = resolve_node_id(str(raw_dst).strip())

        # Validate nodes exist
        services.network.get_node(src)
        services.network.get_node(dst)

        router = DistanceVectorRouter(services.network)
        report = router.run()
        dv_details = router.get_path_details(src, dst)
        path_names = [services.network.get_node(nid).name for nid in dv_details["path"]]

        src_table = [e.to_dict() for e in router.get_routing_table(src).values()]
        dst_table = [e.to_dict() for e in router.get_routing_table(dst).values()]
    except (KeyError, BadRequest) as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        return _json_error(str(exc), 500)

    res_data = {
        "source":             src,
        "destination":        dst,
        "reachable":          dv_details["reachable"],
        "path":               dv_details["path"],
        "path_names":         path_names,
        "total_cost":         dv_details["total_cost"],
        "total_delay_ms":     dv_details["total_delay_ms"],
        "bottleneck_bw_mbps": dv_details["bottleneck_bw_mbps"],
        "hops":               dv_details["hops"],
        "links":              dv_details["links"],
        "converged":          report.converged,
        "iterations":         report.iterations,
        "src":                src_table,
        "dst":                dst_table,
        "tables":             router.to_dict(),
    }

    # Record into persistent history
    history_service.record_simulation(
        algorithm="Distance Vector Routing",
        packets_sent=len(dv_details["path"]) if dv_details["path"] else 1,
        packets_delivered=len(dv_details["path"]) if dv_details["reachable"] else 0,
        packets_lost=0 if dv_details["reachable"] else 1,
        avg_delay_ms=dv_details["total_delay_ms"],
        throughput_kbps=round(dv_details["bottleneck_bw_mbps"] * 1000.0, 2),
        status="SUCCESS" if dv_details["reachable"] else "FAILED",
        parameters={"source": src, "destination": dst, "algorithm": "Distance Vector"},
        details=res_data
    )

    return jsonify(res_data)

def _parse_link_endpoints(data: dict) -> Tuple[str, str]:
    raw_a = data.get("node_a") or data.get("source_id") or data.get("u") or data.get("source") or data.get("src")
    raw_b = data.get("node_b") or data.get("target_id") or data.get("v") or data.get("destination") or data.get("dst") or data.get("target")
    if not raw_a or not raw_b:
        raise BadRequest("Missing required link endpoint fields (node_a/source_id and node_b/target_id).")
    return resolve_node_id(str(raw_a).strip()), resolve_node_id(str(raw_b).strip())

@main.route("/api/links/toggle", methods=["POST"])  # noqa: D401
def links_toggle():
    """Toggle a network link operational status (bidirectional)."""
    data = request.get_json(silent=True) or {}
    try:
        u, v = _parse_link_endpoints(data)
        is_active = services.network.toggle_link(u, v, bidirectional=True)
    except KeyError as exc:
        return _json_error(f"Link not found between specified nodes: {exc}", 404)
    except Exception as exc:
        return _json_error(str(exc), 400)

    action = "restored" if is_active else "disabled"
    status_str = "operational" if is_active else "disabled"
    return jsonify({
        "status":      "success",
        "action":      action,
        "node_a":      u,
        "node_b":      v,
        "is_active":   is_active,
        "link_status": status_str,
        "message":     f"Link {u} ↔ {v} {action} ({status_str.upper()}).",
    })

@main.route("/api/links/fail", methods=["POST"])  # noqa: D401
def links_fail():
    data = request.get_json(silent=True) or {}
    try:
        u, v = _parse_link_endpoints(data)
        services.network.disable_link(u, v, bidirectional=True)
    except KeyError as exc:
        return _json_error(f"Link not found: {exc}", 404)
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify({
        "status":      "link_disabled",
        "node_a":      u,
        "node_b":      v,
        "is_active":   False,
        "link_status": "disabled",
        "message":     f"Link {u} ↔ {v} marked as FAILED.",
    })

@main.route("/api/links/restore", methods=["POST"])  # noqa: D401
def links_restore():
    data = request.get_json(silent=True) or {}
    try:
        u, v = _parse_link_endpoints(data)
        services.network.restore_link(u, v, bidirectional=True)
    except KeyError as exc:
        return _json_error(f"Link not found: {exc}", 404)
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify({
        "status":      "link_restored",
        "node_a":      u,
        "node_b":      v,
        "is_active":   True,
        "link_status": "operational",
        "message":     f"Link {u} ↔ {v} restored to ACTIVE.",
    })

@main.route("/api/crc/check", methods=["POST"])  # noqa: D401
def crc_check():
    data = request.get_json(silent=True) or {}
    try:
        _require_json_keys(data, "hex_data", "generator")
        hex_data = data["hex_data"]
        generator = data["generator"]
        # Convert hexadecimal payload to binary string for CRC processing
        try:
            bit_data = bin(int(hex_data, 16))[2:]
        except ValueError:
            raise BadRequest("hex_data must be a valid hexadecimal string.")
        # ``compute_crc`` returns the remainder; ``verify_crc`` validates.
        crc = compute_crc(bit_data, generator)
        ok = verify_crc(bit_data + crc, generator)
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify({"crc": crc, "valid": ok})

@main.route("/api/go-back-n/run", methods=["POST"])  # noqa: D401
def go_back_n_run():
    data = request.get_json(silent=True) or {}
    try:
        _require_json_keys(data, "total_frames", "window_size", "timeout_ticks")
        total_frames = int(data["total_frames"])
        window_size = int(data["window_size"])
        timeout_ticks = int(data["timeout_ticks"])
        lost_frames = parse_lost_frames_input(data.get("lost_frames"))
        sim = GBNSimulator(
            total_frames=total_frames,
            window_size=window_size,
            timeout_ticks=timeout_ticks,
            lost_frames=lost_frames,
        )
        result = sim.run()
        services.gbn_result = result
        services.gbn_step_index = len(result.events)

        # Record into persistent history
        analytics = result.compute_analytics()
        history_service.record_simulation(
            algorithm="Go-Back-N ARQ",
            packets_sent=result.total_transmissions,
            packets_delivered=len(result.delivered_in_order),
            packets_lost=analytics["lost_transmissions"],
            avg_delay_ms=analytics["avg_delay_ticks"] * 10.0,
            throughput_kbps=round(analytics["channel_efficiency_pct"] * 5.0, 2),
            status="SUCCESS" if analytics["lost_transmissions"] == 0 else "COMPLETED_WITH_LOSS",
            parameters={"total_frames": total_frames, "window_size": window_size, "timeout_ticks": timeout_ticks},
            details={"retransmissions": analytics["retransmissions"], "timeouts": result.total_timeouts}
        )
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify(result.to_dict())

@main.route("/api/go-back-n/init", methods=["POST"])  # noqa: D401
def go_back_n_init():
    """Initialize a step-by-step Go-Back-N simulation session."""
    data = request.get_json(silent=True) or {}
    try:
        total_frames = int(data.get("total_frames", 8))
        window_size = int(data.get("window_size", 4))
        timeout_ticks = int(data.get("timeout_ticks", 4))
        lost_frames = parse_lost_frames_input(data.get("lost_frames"))
        sim = GBNSimulator(
            total_frames=total_frames,
            window_size=window_size,
            timeout_ticks=timeout_ticks,
            lost_frames=lost_frames,
        )
        result = sim.run()
        services.gbn_result = result
        services.gbn_step_index = 0
    except Exception as exc:
        return _json_error(str(exc), 400)

    res_dict = result.to_dict()
    res_dict["status"] = "initialized"
    res_dict["current_step"] = 0
    res_dict["total_events"] = len(result.events)
    return jsonify(res_dict)

@main.route("/api/go-back-n/step", methods=["POST"])  # noqa: D401
def go_back_n_step():
    """Advance the Go-Back-N session by one event step."""
    data = request.get_json(silent=True) or {}
    if services.gbn_result is None:
        # Auto-initialize with provided or default parameters
        total_frames = int(data.get("total_frames", 8))
        window_size = int(data.get("window_size", 4))
        timeout_ticks = int(data.get("timeout_ticks", 4))
        lost_frames = parse_lost_frames_input(data.get("lost_frames"))
        sim = GBNSimulator(
            total_frames=total_frames,
            window_size=window_size,
            timeout_ticks=timeout_ticks,
            lost_frames=lost_frames,
        )
        services.gbn_result = sim.run()
        services.gbn_step_index = 0

    events = services.gbn_result.events
    total_events = len(events)
    
    # If a specific step target is requested:
    req_step = data.get("step_index")
    if req_step is not None:
        idx = min(max(0, int(req_step)), total_events - 1)
    else:
        idx = min(services.gbn_step_index, total_events - 1)

    ev = events[idx]
    is_done = (idx >= total_events - 1)
    if not is_done and req_step is None:
        services.gbn_step_index = idx + 1

    return jsonify({
        "status": "step_executed",
        "current_step": idx,
        "total_events": total_events,
        "is_done": is_done,
        "event": ev.to_dict(),
        "delivered": services.gbn_result.delivered_in_order,
        "total_frames": services.gbn_result.total_frames,
        "window_size": services.gbn_result.window_size,
        "modulus": services.gbn_result.modulus,
    })

@main.route("/api/go-back-n/play", methods=["POST"])  # noqa: D401
def go_back_n_play():
    """Execute all remaining events and return the complete timeline and analytics."""
    if services.gbn_result is None:
        data = request.get_json(silent=True) or {}
        total_frames = int(data.get("total_frames", 8))
        window_size = int(data.get("window_size", 4))
        timeout_ticks = int(data.get("timeout_ticks", 4))
        lost_frames = parse_lost_frames_input(data.get("lost_frames"))
        sim = GBNSimulator(
            total_frames=total_frames,
            window_size=window_size,
            timeout_ticks=timeout_ticks,
            lost_frames=lost_frames,
        )
        services.gbn_result = sim.run()

    services.gbn_step_index = len(services.gbn_result.events)
    res_dict = services.gbn_result.to_dict()
    res_dict["status"] = "completed"
    res_dict["current_step"] = len(services.gbn_result.events) - 1

    # Record into persistent history
    analytics = services.gbn_result.compute_analytics()
    history_service.record_simulation(
        algorithm="Go-Back-N ARQ",
        packets_sent=services.gbn_result.total_transmissions,
        packets_delivered=len(services.gbn_result.delivered_in_order),
        packets_lost=analytics["lost_transmissions"],
        avg_delay_ms=analytics["avg_delay_ticks"] * 10.0,
        throughput_kbps=round(analytics["channel_efficiency_pct"] * 5.0, 2),
        status="SUCCESS" if analytics["lost_transmissions"] == 0 else "COMPLETED_WITH_LOSS",
        parameters={"total_frames": services.gbn_result.total_frames, "window_size": services.gbn_result.window_size, "timeout_ticks": services.gbn_result.timeout_ticks},
        details={"retransmissions": analytics["retransmissions"], "timeouts": services.gbn_result.total_timeouts}
    )

    return jsonify(res_dict)

@main.route("/api/go-back-n/reset", methods=["POST"])  # noqa: D401
def go_back_n_reset():
    """Reset the Go-Back-N simulation session."""
    services.gbn_result = None
    services.gbn_step_index = 0
    return jsonify({"status": "reset_complete"})

@main.route("/api/go-back-n/state", methods=["GET"])  # noqa: D401
def go_back_n_state():
    """Return the current step and state of the Go-Back-N session."""
    if services.gbn_result is None:
        return jsonify({
            "has_session": False,
            "status": "not_initialized",
            "current_step": 0,
            "total_events": 0,
        })
    events = services.gbn_result.events
    idx = min(services.gbn_step_index, len(events) - 1)
    ev = events[idx] if events else None
    return jsonify({
        "has_session": True,
        "status": "active",
        "current_step": idx,
        "total_events": len(events),
        "total_frames": services.gbn_result.total_frames,
        "window_size": services.gbn_result.window_size,
        "modulus": services.gbn_result.modulus,
        "current_event": ev.to_dict() if ev else None,
        "is_done": idx >= len(events) - 1,
    })

@main.route("/api/go-back-n/stats", methods=["GET"])  # noqa: D401
def go_back_n_stats():
    """Return the comprehensive analytical KPIs and chart telemetry."""
    if services.gbn_result is None:
        return _json_error("No active Go-Back-N simulation session.", 404)
    return jsonify(services.gbn_result.compute_analytics())

@main.route("/api/leaky-bucket/run", methods=["POST"])  # noqa: D401
def leaky_bucket_run():
    data = request.get_json(silent=True) or {}
    try:
        _require_json_keys(data, "capacity", "leak_rate", "arrivals")
        capacity = int(data["capacity"])
        leak_rate = int(data["leak_rate"])
        raw_arrivals = data["arrivals"]
        # Support both list [n0, n1, ...] and dict {"0": n0, "1": n1, ...}
        if isinstance(raw_arrivals, list):
            arrivals = {i: int(v) for i, v in enumerate(raw_arrivals)}
        else:
            arrivals = {int(k): int(v) for k, v in raw_arrivals.items()}
        duration = data.get("duration", max(arrivals.keys()) + 1 if arrivals else 1)
        bucket = LeakyBucket(capacity=capacity, leak_rate=leak_rate)
        result = bucket.run(arrivals, duration=int(duration))
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify(result.to_dict())

@main.route("/api/osi/last-trace", methods=["GET"])  # noqa: D401
def osi_last_trace():
    if services.last_osi_result is None:
        return _json_error("No OSI trace available.", 404)
    # ``OSIResult`` already provides a ``as_dict``‑like representation via its
    # attributes – we construct a serialisable view.
    res = services.last_osi_result
    return jsonify({
        "delivered": res.delivered,
        "path": res.path,
        "total_cost": res.total_cost,
        "send_steps": [s.__dict__ for s in res.send_steps],
        "receive_steps": [s.__dict__ for s in res.receive_steps],
        "errors": res.errors,
        "warnings": res.warnings,
    })

@main.route("/api/metrics", methods=["GET"])  # noqa: D401
def api_metrics():
    metrics = SimulationMetrics(events=services.engine.events)
    res = metrics.as_dict()
    # Attach current topology overview
    net = services.network
    nodes = net.list_nodes()
    links = net.list_links()
    res["total_nodes"] = len(nodes)
    res["total_links"] = len(links)
    res["active_links"] = sum(1 for l in links if l.is_operational)
    res["failed_links"] = sum(1 for l in links if not l.is_operational)
    return jsonify(res)

@main.route("/api/events", methods=["GET"])  # noqa: D401
def api_events():
    # Convert PacketEvent objects to dicts for JSON rendering.
    def ev_to_dict(ev):
        return {
            "packet_id": ev.packet_id,
            "src": ev.src,
            "dst": ev.dst,
            "size_bytes": ev.size_bytes,
            "route": ev.route,
            "timestamps": ev.timestamps,
            "delivered": ev.delivered,
            "loss_reason": ev.loss_reason,
            "retransmissions": ev.retransmissions,
            "priority": ev.priority,
        }

    return jsonify([ev_to_dict(e) for e in services.engine.events])

# ---------------------------------------------------------------------------
# New API endpoints for advanced features
# ---------------------------------------------------------------------------
@main.route("/api/dv-routing", methods=["GET"])  # noqa: D401
def api_dv_routing():
    """Return the latest Distance‑Vector routing tables."""
    tables = dv_service.tables
    return jsonify(tables)

@main.route("/api/leaky-bucket", methods=["GET"])  # noqa: D401
def api_leaky_bucket():
    """Return the most recent Leaky‑Bucket simulation result."""
    if leaky_bucket_service.last_result is None:
        return _json_error("Leaky bucket not run yet", 400)
    return jsonify(leaky_bucket_service.last_result.to_dict())

@main.route("/api/packet-debug/<int:packet_id>", methods=["GET"])  # noqa: D401
def packet_debug(packet_id):
    """Return detailed information for a specific packet event."""
    ev = next((e for e in services.engine.events if e.packet_id == packet_id), None)
    if ev is None:
        return _json_error(f"Packet {packet_id} not found", 404)
    ev_dict = {
        "packet_id": ev.packet_id,
        "src": ev.src,
        "dst": ev.dst,
        "size_bytes": ev.size_bytes,
        "route": ev.route,
        "timestamps": ev.timestamps,
        "delivered": ev.delivered,
        "loss_reason": ev.loss_reason,
        "retransmissions": ev.retransmissions,
        "priority": ev.priority,
    }
    return jsonify(ev_dict)

# ---------------------------------------------------------------------------
# Optional: expose an endpoint that runs the OSI stack for a demo message.
# This is useful for quick manual testing.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Optional: expose an endpoint that runs the OSI stack for a demo message.
# This is useful for quick manual testing.
# ---------------------------------------------------------------------------
@main.route("/api/osi/run", methods=["POST"])  # noqa: D401
def osi_run():
    data = request.get_json(silent=True) or {}
    try:
        _require_json_keys(data, "message", "source_id", "dest_id", "priority")
        stack = OSIStack(network=services.network)
        result = stack.send(
            message=data["message"],
            source_id=data["source_id"],
            dest_id=data["dest_id"],
            priority=data.get("priority", "NORMAL"),
        )
        services.last_osi_result = result
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify({"status": "completed", "delivered": result.delivered})

# ---------------------------------------------------------------------------
# Congestion Control Endpoints (Leaky Bucket Lab)
# ---------------------------------------------------------------------------
@main.route("/api/congestion/status", methods=["GET"])
def congestion_status():
    """Return the current Leaky Bucket simulation state."""
    return jsonify(congestion_service.get_status())

@main.route("/api/congestion/simulate", methods=["POST"])
def congestion_simulate():
    """Run an interactive Leaky Bucket congestion simulation."""
    data = request.get_json(silent=True) or {}
    try:
        cap = int(data.get("capacity", 15))
        rate = int(data.get("leak_rate", 4))
        arrivals = data.get("arrivals", [12, 2, 14, 0, 8, 16, 2, 0])
        dur = data.get("duration")
        res = congestion_service.simulate(capacity=cap, leak_rate=rate, arrivals_input=arrivals, duration=dur)
    except Exception as exc:
        return _json_error(str(exc), 400)
    return jsonify(res)

@main.route("/api/congestion/reset", methods=["POST"])
def congestion_reset():
    """Reset the Leaky Bucket state."""
    return jsonify(congestion_service.reset())

# ---------------------------------------------------------------------------
# Performance Analytics Endpoints
# ---------------------------------------------------------------------------
@main.route("/api/analytics/overview", methods=["GET"])
def analytics_overview():
    """Return executive KPI telemetry and metrics for analytics dashboard."""
    kpis = analytics_service.get_overview_kpis(services.engine)
    return jsonify(kpis)

@main.route("/api/analytics/performance", methods=["GET"])
@main.route("/api/analytics/compare", methods=["GET", "POST"])
def analytics_performance_compare():
    """Return comparative load curves (uncontrolled vs Leaky Bucket controlled)."""
    comparison = analytics_service.compute_traffic_load_comparison()
    return jsonify(comparison)

@main.route("/api/analytics/export", methods=["GET"])
def analytics_export():
    """Export formatted CSV performance audit report."""
    csv_text = analytics_service.export_csv_report(services.engine)
    response = make_response(csv_text)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=resqnet_performance_report.csv"
    return response

# ---------------------------------------------------------------------------
# Simulation History Endpoints (SQLite Persistent Audit Trail)
# ---------------------------------------------------------------------------
@main.route("/api/history", methods=["GET"])
def api_history_list():
    """List simulation history records with optional search, filters, and sort."""
    query = request.args.get("query", "")
    algorithm = request.args.get("algorithm", "all")
    status = request.args.get("status", "all")
    sort = request.args.get("sort", "newest")
    limit = int(request.args.get("limit", 100))

    sims = history_service.get_simulations(query=query, algorithm=algorithm, status=status, sort=sort, limit=limit)
    summary = history_service.get_summary()
    return jsonify({
        "simulations": sims,
        "summary": summary
    })

@main.route("/api/history/<simulation_id>", methods=["GET"])
def api_history_detail(simulation_id):
    """Retrieve full detail snapshot for a specific simulation."""
    item = history_service.get_simulation_by_id(simulation_id)
    if not item:
        return _json_error(f"Simulation record '{simulation_id}' not found.", 404)
    return jsonify(item)

@main.route("/api/history/<simulation_id>", methods=["DELETE"])
def api_history_delete(simulation_id):
    """Delete an individual simulation record."""
    ok = history_service.delete_simulation(simulation_id)
    if not ok:
        return _json_error(f"Simulation record '{simulation_id}' not found.", 404)
    return jsonify({"status": "deleted", "id": simulation_id})

@main.route("/api/history/clear", methods=["DELETE", "POST"])
def api_history_clear():
    """Clear all simulation history records."""
    count = history_service.clear_history()
    return jsonify({"status": "cleared", "deleted_count": count})

@main.route("/api/history/export", methods=["GET"])
def api_history_export():
    """Export all simulation history records as CSV."""
    csv_text = history_service.export_csv()
    response = make_response(csv_text)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=resqnet_simulation_history.csv"
    return response

"""End of routes module."""
