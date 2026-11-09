# ResQNet — Project Report

**Course**: Computer Networks and Internet Protocols (CNIP)  
**Title**: ResQNet — Reliable Emergency Communication Network Under Congested Conditions  
**Python**: 3.10+  **Framework**: Flask 3.x  **Tests**: 233 passed

---

## 1. Introduction

Emergency communication networks face extreme conditions: high traffic bursts,
physical link failures, and the need for guaranteed message delivery. ResQNet
is an educational simulation platform that demonstrates how classical networking
protocols and algorithms address these challenges.

The system models a realistic emergency network with 8 nodes (command centre,
police, fire, ambulance, routers, field teams) and 16 directed links, and
provides interactive simulations for:

- Shortest-path routing (Dijkstra, Distance-Vector)
- Link failure detection and route recovery
- CRC error detection
- Go-Back-N retransmission for reliability
- Leaky Bucket congestion control
- Full 7-layer OSI model trace

---

## 2. System Design

### 2.1 Network Topology

The `EmergencyNetwork` graph uses an adjacency-list representation. Each `Link`
carries:

| Attribute | Type | Description |
|-----------|------|-------------|
| `cost` | float | Routing metric (lower = preferred) |
| `latency_ms` | float | Propagation delay in milliseconds |
| `bandwidth_mbps` | float | Link capacity in Megabits/s |
| `queue_capacity` | int | Max concurrent in-flight packets |
| `status` | `LinkStatus` | OPERATIONAL or FAILED |

Links can be toggled via `disable_link()` / `restore_link()`.

### 2.2 Routing Algorithms

#### Dijkstra's Algorithm
- **Complexity**: O((V + E) log V) with a binary min-heap
- **Behaviour**: Skips FAILED links; returns the shortest-cost path
- **Output**: Path, total cost, per-step execution trace

#### Distance-Vector (Bellman-Ford)
- **Convergence**: Iterative relaxation until no table updates
- **Failure handling**: Excludes disabled links from neighbour discovery
- **Output**: Full routing tables for every node; convergence report

**Cross-algorithm consistency**: Both algorithms produce the same optimal path
costs on all verified node pairs (confirmed by `TestCrossAlgorithmConsistency`).

### 2.3 CRC Error Detection

The `CRCEngine` implements binary XOR polynomial division:

```
padded_dataword = dataword + ('0' × degree(generator))
remainder       = padded_dataword mod generator   (XOR long division)
codeword        = dataword + remainder
syndrome        = received_codeword mod generator
valid           = (syndrome == '0' × degree)
```

**Tested presets**: CRC-4 (`10011`), CRC-8, CRC-16, CRC-CCITT.

### 2.4 Go-Back-N ARQ

The `GBNSimulator` implements sliding-window ARQ:

- Sender window of size W; sequence numbers mod (W+1)
- On timeout: retransmit the entire window from the oldest unACKed frame
- Receiver accepts only in-order frames; out-of-order frames are discarded
- Loss is deterministic via `lost_frames = {(seq, attempt), ...}`

**Metrics**:
- `total_transmissions` — includes retransmissions
- `total_timeouts` — number of timeout events fired
- `delivered_in_order` — frame IDs in delivery order

### 2.5 Leaky Bucket Congestion Control

Each tick t:
```
arriving(t)  = arrivals.get(t, 0)   (clamped to ≥ 0)
space(t)     = capacity − queue_before(t)
admitted(t)  = min(arriving(t), space(t))
dropped(t)   = arriving(t) − admitted(t)
queue_mid(t) = queue_before(t) + admitted(t)
leaked(t)    = min(queue_mid(t), leak_rate)
queue_after  = queue_mid(t) − leaked(t)
```

**drop_rate** = total_dropped / total_arriving

### 2.6 OSI Model Simulation

The 7-layer stack encapsulates a message top-down (L7→L1) and decapsulates
bottom-up (L1→L7):

| Layer | PDU | Implementation |
|-------|-----|----------------|
| 7 Application | Message | Creates `EmergencyMessage` with unique ID |
| 6 Presentation | Encoded Data | hex(UTF-8) + base64 metadata |
| 5 Session | Session Block | State machine: OPEN → ACTIVE → CLOSE |
| 4 Transport | Segment(s) | 32-byte segmentation + optional GBN ARQ |
| 3 Network | Packet | Dijkstra path; fails on unreachable destination |
| 2 Data Link | Frame | CRC-4 checksum; preamble + MAC addresses |
| 1 Physical | Bits | Link check; bandwidth + latency record |

Failure at any layer aborts the encapsulation and sets `delivered = False`.

---

## 3. Performance Metrics

| Metric | Formula | Unit |
|--------|---------|------|
| Delivery Ratio | delivered / total_sent | fraction (0–1) |
| Loss Ratio | lost / total_sent | fraction (0–1) |
| Throughput | Σ(size_bytes × 8) / duration | bits/second |
| Avg End-to-End Delay | mean(arrival_ts − send_ts) | seconds |
| Retransmission Rate | Σ(retransmissions) / total_sent | avg per packet |

---

## 4. Test Results

All **233 tests pass** across 6 test modules:

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_network_topology.py` | ~50 | Graph construction, link ops, serialisation |
| `test_routing.py` | ~60 | Dijkstra, DV, failure, restoration, consistency |
| `test_reliability.py` | ~70 | CRC generate/verify/inject, GBN events, Leaky Bucket |
| `test_osi_model.py` | 4 | Delivery, CRC error, unreachable, GBN warning |
| `test_simulation.py` | 5 | Engine delivery, failure, overflow, GBN batch, metrics |
| `test_flask_app.py` | 6 | Health, topology, send, routing, OSI, simulation API |

**Test execution**: `pytest -v` — deterministic, no network I/O, no sleeps.

---

## 5. Demonstration Scenarios

### Scenario A — Normal Delivery
```
POST /api/messages/send
{"src":"ECC-01","dst":"AMB-01","message":"MAYDAY: fire at grid 4F","priority":"HIGH"}
→ delivered: true, route: ["ECC-01","RTR-01","AMB-01"], cost: 4
```

### Scenario B — Link Failure and Recovery
```
POST /api/links/fail   {"source_id":"ECC-01","target_id":"RTR-01"}
POST /api/messages/send {"src":"ECC-01","dst":"AMB-01","message":"EVAC","priority":"CRITICAL"}
→ delivered: true, route: ["ECC-01","PS-01","RTR-02","AMB-01"]  (rerouted)

POST /api/links/restore {"source_id":"ECC-01","target_id":"RTR-01"}
→ link restored; subsequent packets use original path
```

### Scenario C — CRC Error Detection
```
POST /api/osi/run
{"message":"MAYDAY","source_id":"ECC-01","dest_id":"FS-01","priority":"CRITICAL"}
With inject_crc_error=True:
→ delivered: false, Data Link receive step → status: ERROR, syndrome ≠ 0
```

### Scenario D — Go-Back-N Retransmission
```
POST /api/go-back-n/run
{"total_frames":6,"window_size":3,"timeout_ticks":4,"lost_frames":[[0,1],[2,1]]}
→ all 6 frames delivered, total_transmissions > 6, total_timeouts ≥ 2
```

### Scenario E — Leaky Bucket Congestion
```
POST /api/leaky-bucket/run
{"capacity":3,"leak_rate":1,"arrivals":[10,0,0,0,0],"duration":5}
→ admitted: 3, dropped: 7, drop_rate: 0.70, smooth output at 1/tick
```

---

## 6. Known Limitations and Future Work

| Limitation | Mitigation / Future Work |
|------------|--------------------------|
| In-memory state | Add Redis or SQLite persistence |
| Single session | User session isolation via Flask sessions |
| Static topology | Allow dynamic node/link addition from UI |
| No WebSocket | Add Flask-SocketIO for real-time animation |
| OSI simplification | Model TCP/IP specifics (sequence numbers, flow control) |
| No IPv6 | Extend network layer to support IPv6 addressing |

---

## 7. References

1. Forouzan, B.A. (2013). *Data Communications and Networking*, 5th ed. McGraw-Hill.
2. Tanenbaum, A.S. & Wetherall, D. (2011). *Computer Networks*, 5th ed. Pearson.
3. RFC 3022 — Traditional IP Network Address Translator.
4. Peterson, L.L. & Davie, B.S. (2011). *Computer Networks: A Systems Approach*, 5th ed. Elsevier.
