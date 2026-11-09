# ResQNet — Reliable Emergency Communication Network

> An educational simulation platform for studying reliable communication
> strategies in emergency scenarios under congested network conditions.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-233%20passed-brightgreen)](#testing)

---

## Overview

ResQNet models an emergency communications network — fire stations, ambulances,
police stations, field teams, a shelter, and a central command (ECC) — and lets
you explore:

| Feature | Description |
|---------|-------------|
| **OSI Explorer** | Step through all 7 OSI layers for a live message trace |
| **Routing** | Dijkstra and Distance-Vector path-finding with link failures |
| **Reliability** | CRC error detection, Go-Back-N retransmissions |
| **Congestion** | Leaky Bucket queue simulation with drop metrics |
| **Analytics** | Throughput, delay, delivery ratio, retransmission rate |

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd ResQNet

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the development server
python run.py
```

Open **http://localhost:5000** in your browser.

---

## Project Structure

```
ResQNet/
├── app/
│   ├── __init__.py            # Application factory (create_app)
│   ├── config.py              # Flask configuration class
│   ├── routes.py              # Blueprint: page + API endpoints
│   ├── algorithms/
│   │   ├── network_topology.py  # EmergencyNetwork graph model
│   │   ├── dijkstra.py          # Dijkstra shortest-path
│   │   ├── distance_vector.py   # Distance-Vector (Bellman-Ford)
│   │   ├── crc.py               # CRC error detection engine
│   │   ├── go_back_n.py         # Go-Back-N ARQ simulator
│   │   └── leaky_bucket.py      # Leaky Bucket congestion control
│   └── simulation/
│       ├── engine.py            # Discrete-event simulation engine
│       ├── metrics.py           # KPI calculations (throughput, delay…)
│       └── osi_model.py         # 7-layer OSI educational stack
├── tests/
│   ├── test_flask_app.py        # Flask endpoint integration tests
│   ├── test_network_topology.py # Graph model unit tests
│   ├── test_osi_model.py        # OSI stack unit tests
│   ├── test_reliability.py      # CRC / GBN / LeakyBucket tests
│   ├── test_routing.py          # Dijkstra + DV routing tests
│   └── test_simulation.py       # Engine + metrics tests
├── docs/
│   ├── architecture.md          # System architecture deep-dive
│   └── project_report.md        # Academic project report
├── reports/                     # Generated JSON/CSV exports (git-ignored)
├── run.py                       # Entry point: python run.py
├── requirements.txt
├── .gitignore
└── README.md
```

---

## API Endpoints

### Health & Topology
| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/health` | Health check → `{"status":"ok"}` |
| GET | `/api/topology` | Full network graph (nodes + links) |

### Messaging & Simulation
| Method | URL | Body fields | Description |
|--------|-----|-------------|-------------|
| POST | `/api/messages/send` | `src`, `dst`, `message`, `size_bytes?`, `priority?` | Send a single packet |
| POST | `/api/simulation/start` | `traffic_level`, `packet_size_bytes`, `enable_gbn`, `gbn_lost_frames` | (Re)configure engine |
| POST | `/api/simulation/reset` | — | Reset network + engine |
| GET | `/api/events` | — | All packet events |
| GET | `/api/metrics` | — | Aggregated KPIs |

### Routing
| Method | URL | Body | Description |
|--------|-----|------|-------------|
| POST | `/api/routing/dijkstra` | `src`, `dst` | Dijkstra path + cost + steps |
| POST | `/api/routing/distance-vector` | `src`, `dst` | DV routing tables |

### Link Management
| Method | URL | Body | Description |
|--------|-----|------|-------------|
| POST | `/api/links/fail` | `source_id`, `target_id` | Disable a link |
| POST | `/api/links/restore` | `source_id`, `target_id` | Re-enable a link |

### Reliability & Congestion
| Method | URL | Body | Description |
|--------|-----|------|-------------|
| POST | `/api/crc/check` | `hex_data`, `generator` | Compute + verify CRC |
| POST | `/api/go-back-n/run` | `total_frames`, `window_size`, `timeout_ticks`, `lost_frames?` | Run GBN simulation |
| POST | `/api/leaky-bucket/run` | `capacity`, `leak_rate`, `arrivals`, `duration?` | Run Leaky Bucket |

### OSI Explorer
| Method | URL | Body | Description |
|--------|-----|------|-------------|
| POST | `/api/osi/run` | `message`, `source_id`, `dest_id`, `priority` | Run full 7-layer trace |
| GET | `/api/osi/last-trace` | — | Retrieve last OSI trace |

---

## Testing

```bash
# Run all 233 tests
pytest -v

# Run a specific module
pytest tests/test_reliability.py -v
pytest tests/test_routing.py -v
```

All tests are deterministic — no random seeds, no real-time sleeps.

---

## Configuration

Edit `app/config.py` to change:
- `SECRET_KEY` — Flask session secret (set via `FLASK_SECRET_KEY` env var)
- `DEBUG` — enabled by default in development

---

## License

MIT — see `LICENSE` for details.
