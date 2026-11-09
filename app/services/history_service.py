"""
ResQNet — app/services/history_service.py
==========================================
Persistent SQLite database service for simulation history audit logs.
Stores and indexes every simulation across:
- Dijkstra & Distance Vector Routing
- Go-Back-N ARQ Protocol
- Leaky Bucket Congestion Control
- CRC Error Detection
- Emergency Communication Traffic Workloads
"""

import os
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any


class HistoryService:
    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            # Place database in project root
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            self.db_path = os.path.join(base_dir, "resqnet_history.db")
        else:
            self.db_path = db_path
        self._init_db()
        self._ensure_seed_data()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the simulations schema if it does not exist."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS simulations (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    packets_sent INTEGER NOT NULL,
                    packets_delivered INTEGER NOT NULL,
                    packets_lost INTEGER NOT NULL,
                    avg_delay_ms REAL NOT NULL,
                    throughput_kbps REAL NOT NULL,
                    status TEXT NOT NULL,
                    parameters_json TEXT,
                    details_json TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_timestamp ON simulations(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_algorithm ON simulations(algorithm);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sim_status ON simulations(status);")

    def _ensure_seed_data(self) -> None:
        """Seed initial realistic records if database is fresh."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM simulations;")
            count = cur.fetchone()[0]
            if count == 0:
                self._seed_default_history(conn)

    def _seed_default_history(self, conn: sqlite3.Connection) -> None:
        """Insert baseline historical records for demo and testing."""
        seeds = [
            (
                "SIM-20261109-152011-A101",
                "2026-11-09 15:20:11",
                "Emergency Traffic Engine",
                20, 20, 0, 18.5, 480.2, "SUCCESS",
                json.dumps({"traffic_level": "low", "nodes": 8, "workload": "Triage & Shelter Coordination"}),
                json.dumps({"routes": ["SHL-01 -> ECC-01", "AMB-01 -> ECC-01"], "retransmissions": 0})
            ),
            (
                "SIM-20261109-154522-B202",
                "2026-11-09 15:45:22",
                "Dijkstra Routing",
                12, 12, 0, 12.0, 520.0, "SUCCESS",
                json.dumps({"source": "SHT1", "destination": "ECC", "algorithm": "Dijkstra"}),
                json.dumps({"path": ["SHL-01", "RTR-02", "RTR-01", "ECC-01"], "cost": 6.0, "hops": 3})
            ),
            (
                "SIM-20261109-161033-C303",
                "2026-11-09 16:10:33",
                "Go-Back-N ARQ",
                14, 8, 2, 28.4, 210.5, "COMPLETED_WITH_LOSS",
                json.dumps({"total_frames": 8, "window_size": 4, "lost_frames": "1,1"}),
                json.dumps({"delivered_frames": 8, "retransmissions": 4, "timeouts": 1})
            ),
            (
                "SIM-20261109-163544-D404",
                "2026-11-09 16:35:44",
                "Leaky Bucket Congestion",
                56, 42, 14, 16.2, 340.0, "COMPLETED_WITH_LOSS",
                json.dumps({"capacity": 15, "leak_rate": 4, "burst": [12, 2, 14, 0, 8, 16, 2, 0]}),
                json.dumps({"dropped_packets": 14, "leaked_packets": 42, "final_queue": 0})
            ),
            (
                "SIM-20261109-170155-E505",
                "2026-11-09 17:01:55",
                "Distance Vector Routing",
                10, 10, 0, 14.5, 490.0, "SUCCESS",
                json.dumps({"source": "POL", "destination": "ECC", "algorithm": "Distance Vector"}),
                json.dumps({"path": ["PS-01", "ECC-01"], "cost": 3.0, "hops": 1})
            )
        ]
        conn.executemany("""
            INSERT INTO simulations (
                id, timestamp, algorithm, packets_sent, packets_delivered,
                packets_lost, avg_delay_ms, throughput_kbps, status,
                parameters_json, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, seeds)

    def record_simulation(
        self,
        algorithm: str,
        packets_sent: int,
        packets_delivered: int,
        packets_lost: int,
        avg_delay_ms: float,
        throughput_kbps: float,
        status: str = "SUCCESS",
        parameters: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record a completed simulation run in SQLite database."""
        now = datetime.now()
        sim_id = f"SIM-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
        ts_str = now.strftime("%Y-%m-%d %H:%M:%S")

        param_str = json.dumps(parameters or {})
        detail_str = json.dumps(details or {})

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO simulations (
                    id, timestamp, algorithm, packets_sent, packets_delivered,
                    packets_lost, avg_delay_ms, throughput_kbps, status,
                    parameters_json, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                sim_id, ts_str, algorithm, packets_sent, packets_delivered,
                packets_lost, round(avg_delay_ms, 2), round(throughput_kbps, 2),
                status, param_str, detail_str
            ))

        return sim_id

    def get_simulations(
        self,
        query: str = "",
        algorithm: str = "all",
        status: str = "all",
        sort: str = "newest",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Retrieve simulation records matching filters and sort order."""
        sql = "SELECT * FROM simulations WHERE 1=1"
        params: List[Any] = []

        if query:
            sql += " AND (id LIKE ? OR algorithm LIKE ? OR parameters_json LIKE ?)"
            pattern = f"%{query.strip()}%"
            params.extend([pattern, pattern, pattern])

        if algorithm and algorithm.lower() != "all":
            sql += " AND LOWER(algorithm) LIKE ?"
            params.append(f"%{algorithm.strip().lower()}%")

        if status and status.lower() != "all":
            sql += " AND LOWER(status) = ?"
            params.append(status.strip().lower())

        # Sort order
        if sort == "oldest":
            sql += " ORDER BY timestamp ASC"
        elif sort == "throughput":
            sql += " ORDER BY throughput_kbps DESC"
        elif sort == "loss":
            sql += " ORDER BY packets_lost DESC"
        else:
            sql += " ORDER BY timestamp DESC"

        sql += f" LIMIT {int(limit)}"

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["delivery_ratio"] = round((item["packets_delivered"] / item["packets_sent"] * 100.0), 1) if item["packets_sent"] > 0 else 0.0
                item["loss_ratio"] = round((item["packets_lost"] / item["packets_sent"] * 100.0), 1) if item["packets_sent"] > 0 else 0.0
                try:
                    item["parameters"] = json.loads(item["parameters_json"]) if item["parameters_json"] else {}
                except Exception:
                    item["parameters"] = {}
                try:
                    item["details"] = json.loads(item["details_json"]) if item["details_json"] else {}
                except Exception:
                    item["details"] = {}
                results.append(item)
            return results

    def get_simulation_by_id(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Fetch complete detail record for a given simulation ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM simulations WHERE id = ?;", (simulation_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["delivery_ratio"] = round((item["packets_delivered"] / item["packets_sent"] * 100.0), 1) if item["packets_sent"] > 0 else 0.0
            item["loss_ratio"] = round((item["packets_lost"] / item["packets_sent"] * 100.0), 1) if item["packets_sent"] > 0 else 0.0
            try:
                item["parameters"] = json.loads(item["parameters_json"]) if item["parameters_json"] else {}
            except Exception:
                item["parameters"] = {}
            try:
                item["details"] = json.loads(item["details_json"]) if item["details_json"] else {}
            except Exception:
                item["details"] = {}
            return item

    def delete_simulation(self, simulation_id: str) -> bool:
        """Delete an individual simulation by ID."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM simulations WHERE id = ?;", (simulation_id,))
            return cur.rowcount > 0

    def clear_history(self) -> int:
        """Delete all simulation history records."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM simulations;")
            return cur.rowcount

    def get_summary(self) -> Dict[str, Any]:
        """Compute summary KPI statistics across all simulations."""
        with self._get_connection() as conn:
            total_sims = conn.execute("SELECT COUNT(*) FROM simulations;").fetchone()[0]
            if total_sims == 0:
                return {
                    "total_simulations": 0,
                    "successful_simulations": 0,
                    "failed_simulations": 0,
                    "total_packets": 0,
                    "avg_delivery_ratio": 0.0,
                    "avg_throughput_kbps": 0.0,
                }

            succ = conn.execute("SELECT COUNT(*) FROM simulations WHERE status = 'SUCCESS';").fetchone()[0]
            failed = total_sims - succ
            tot_packets = conn.execute("SELECT SUM(packets_sent) FROM simulations;").fetchone()[0] or 0
            avg_throughput = conn.execute("SELECT AVG(throughput_kbps) FROM simulations;").fetchone()[0] or 0.0

            rows = conn.execute("SELECT packets_sent, packets_delivered FROM simulations;").fetchall()
            total_sent = sum(r[0] for r in rows)
            total_del = sum(r[1] for r in rows)
            overall_delivery_ratio = round((total_del / total_sent * 100.0), 1) if total_sent > 0 else 0.0

            return {
                "total_simulations": total_sims,
                "successful_simulations": succ,
                "failed_simulations": failed,
                "total_packets": tot_packets,
                "avg_delivery_ratio": overall_delivery_ratio,
                "avg_throughput_kbps": round(float(avg_throughput), 1),
            }

    def export_csv(self) -> str:
        """Export all simulations as a CSV formatted string."""
        sims = self.get_simulations(limit=1000)
        lines = [
            "Simulation ID,Timestamp,Algorithm,Packets Sent,Packets Delivered,Packets Lost,Delivery Ratio (%),Average Delay (ms),Throughput (kbps),Status"
        ]
        for s in sims:
            lines.append(
                f"{s['id']},{s['timestamp']},{s['algorithm']},{s['packets_sent']},{s['packets_delivered']},{s['packets_lost']},{s['delivery_ratio']},{s['avg_delay_ms']},{s['throughput_kbps']},{s['status']}"
            )
        return "\n".join(lines)


# Singleton instance
history_service = HistoryService()

