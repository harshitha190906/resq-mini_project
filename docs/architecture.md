# ResQNet — System Architecture

## 1. High-Level Overview

ResQNet is a monolithic Flask application organised in a layered architecture:

```
Browser
  │  HTTP (JSON / HTML)
  ▼
Flask Blueprint (app/routes.py)
  │
  ├─ Page endpoints → Jinja2 templates (app/templates/)
  │
  └─ API endpoints
       │
       ├─ ServiceContainer (global state)
       │    ├─ EmergencyNetwork   (graph model)
       │    └─ SimulationEngine  (packet engine)
       │
       ├─ app/algorithms/        (pure functions / classes)
       │    ├─ network_topology.py
       │    ├─ dijkstra.py
       │    ├─ distance_vector.py
       │    ├─ crc.py
       │    ├─ go_back_n.py
       │    └─ leaky_bucket.py
       │
       └─ app/simulation/        (orchestration)
            ├─ engine.py         (DiscreteEventEngine)
            ├─ metrics.py        (KPI calculations)
            └─ osi_model.py      (7-layer OSI stack)
```

---

## 2. Module Details

### 2.1 `app/algorithms/network_topology.py`

| Class | Responsibility |
|-------|---------------|
| `Node` | Represents a network node (ID, name, type, position) |
| `Link` | Directed weighted edge (cost, latency_ms, bandwidth_mbps, status, queue_capacity) |
| `EmergencyNetwork` | Adjacency-list graph with `disable_link`, `restore_link`, `get_link`, `get_all_neighbours`, `get_available_neighbours`, `to_dict` |

`build_sample_network()` constructs an 8-node, 16-link emergency network:
- ECC-01 (Emergency Command Centre)
- PS-01 (Police Station)
- FS-01 (Fire Station)
- AMB-01 (Ambulance Hub)
- RTR-01, RTR-02 (Routers)
- FT-01 (Field Team Alpha), FT-02 (Field Team Bravo… mapped to SHL-01)

### 2.2 `app/algorithms/dijkstra.py`

| Symbol | Description |
|--------|-------------|
| `dijkstra(network, source, destination)` | Returns `DijkstraResult` with `.path`, `.total_cost`, `.reachable`, `.steps` |
| `DijkstraStep` | One settled node with a snapshot of all tentative costs |

Algorithm: standard binary min-heap Dijkstra. Only **operational** links are
explored (`_operational_edges` helper). Complexity: O((V+E) log V).

### 2.3 `app/algorithms/distance_vector.py`

| Class | Description |
|-------|-------------|
| `DistanceVectorRouter` | Bellman-Ford iterative relaxation over all nodes |
| `RoutingEntry` | `(destination, next_hop, cost)` |
| `ConvergenceReport` | `converged`, `iterations`, `iteration_log` |

Converges when a full pass produces zero table updates. Respects disabled links
via `get_available_neighbours`.

### 2.4 `app/algorithms/crc.py`

Implements binary XOR division for CRC checksum generation and verification.

| Class | Method | Description |
|-------|--------|-------------|
| `CRCEngine(generator)` | `generate(dataword)` | Returns `CRCGenerateResult` with `remainder`, `codeword`, `division_steps` |
| `CRCEngine` | `verify(received)` | Returns `CRCVerifyResult` with `syndrome`, `valid` |
| `CRCEngine` | `inject_errors(bits, positions)` | Bit-flip injection for testing |
| `CRCPreset` | Enum values | CRC4 (`10011`), CRC8, CRC16, CRC_CCITT, CUSTOM |

### 2.5 `app/algorithms/go_back_n.py`

Tick-based sliding-window ARQ simulator.

| Class | Description |
|-------|-------------|
| `GBNSimulator(total_frames, window_size, timeout_ticks, lost_frames)` | Runs full simulation via `.run()` |
| `GBNResult` | `delivered_in_order`, `total_transmissions`, `total_timeouts`, `events` |
| `GBNEvent` | Per-tick event: SEND, ACK, LOSS, TIMEOUT, DISCARD, DELIVERED, DONE |
| `GoBackN` | Thin shim used by `SimulationEngine`: `is_lost(seq, attempt)` |

Loss is **deterministic**: the caller supplies `lost_frames = {(seq, attempt), ...}`.

### 2.6 `app/algorithms/leaky_bucket.py`

Tick-based leaky bucket queue model.

| Class | Method | Description |
|-------|--------|-------------|
| `LeakyBucket(capacity, leak_rate)` | `run(arrivals, duration)` | Returns `LeakyBucketResult` |
| `LeakyBucket` | `tick(current_queue, arriving)` | Single-tick helper |

Each tick: admits min(arriving, space), drops excess, leaks min(queue, leak_rate).

### 2.7 `app/simulation/engine.py`

`SimulationEngine` drives packet flows over the `EmergencyNetwork`:

1. Calls `dijkstra` to find the best current route.
2. Returns `no_path` if unreachable.
3. Walks each hop: checks `is_operational`, then `queue_capacity`.
4. Optionally consults `GoBackN.is_lost` for hop-level loss simulation.
5. Accumulates `PacketEvent` objects in `self.events`.

### 2.8 `app/simulation/metrics.py`

`SimulationMetrics(events)` computes:

| Metric | Formula |
|--------|---------|
| `delivery_ratio` | delivered / total_sent |
| `loss_ratio` | lost / total_sent |
| `throughput_bps` | Σ(size_bytes × 8) / simulation_duration |
| `average_end_to_end_delay` | mean(arrival_ts − send_ts) for delivered packets |
| `retransmission_rate` | Σ(retransmissions) / total_sent |

All timestamps are in **seconds**; size in **bytes**; throughput in **bits/s**.

### 2.9 `app/simulation/osi_model.py`

`OSIStack.send(message, source_id, dest_id, priority)` encapsulates a message
through all 7 layers (L7→L1) then decapsulates (L1→L7).

| Layer | PDU | Key actions |
|-------|-----|-------------|
| 7 Application | Message | Create `EmergencyMessage`, assign message_id |
| 6 Presentation | Encoded Data | UTF-8 → hex encoding; base64 metadata |
| 5 Session | Session Block | Open/Active/Close session lifecycle |
| 4 Transport | Segment(s) | Segment by 32-byte chunks; optional GBN ARQ |
| 3 Network | Packet | Dijkstra routing; fail if unreachable |
| 2 Data Link | Frame | CRC-4 framing; optional CRC error injection |
| 1 Physical | Bits | Link availability check; bandwidth/latency record |

Returns `OSIResult` with `send_steps`, `receive_steps`, `delivered`, `path`,
`total_cost`, `errors`, `warnings`.

---

## 3. Request / Response Flows

### 3.1 Send a packet
```
POST /api/messages/send  {src, dst, message}
  → routes.py:send_message()
  → ServiceContainer.engine.send_packet()
  → dijkstra(network, src, dst)      # route computation
  → walk hops: check link status + queue
  → PacketEvent appended to engine.events
  → JSON response {delivered, route, timestamps, …}
```

### 3.2 OSI trace
```
POST /api/osi/run  {message, source_id, dest_id, priority}
  → routes.py:osi_run()
  → OSIStack(network).send()
      L7 → L6 → L5 → L4 → L3 → L2 → L1  (encapsulation)
      L1 → L2 → L3 → L4 → L5 → L6 → L7  (decapsulation)
  → OSIResult stored in services.last_osi_result
  → JSON {status, delivered}
```

---

## 4. State Management

A single `ServiceContainer` instance is created at module import time:

```python
services = ServiceContainer()
```

It holds:
- `services.network` — `EmergencyNetwork` (mutable; links can be disabled/restored)
- `services.engine` — `SimulationEngine` (holds `events` list)
- `services.last_osi_result` — last `OSIResult` (overwritten on each `/api/osi/run`)

`/api/simulation/reset` calls `services.reset_all()` which rebuilds both
network and engine from scratch.

> **Note**: This is a single-process, in-memory design. Multiple concurrent
> requests could race on `services`. For production use, replace with a
> proper database or message queue.

---

## 5. Known Limitations

| Limitation | Details |
|------------|---------|
| No persistence | All simulation state is lost on server restart |
| Single-process | No support for concurrent simulation sessions |
| Simplified OSI | Educational approximation; not a real TCP/IP stack |
| No WebSocket | Frontend must poll `/api/events` for live updates |
| Network scope | Fixed 8-node topology; not configurable from UI |
| GBN in engine | Loss is per-hop/attempt, not per-frame as in real ARQ |
