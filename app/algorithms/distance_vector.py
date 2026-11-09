"""
ResQNet — app/algorithms/distance_vector.py
============================================
Distance-Vector (DV) routing protocol simulation built on top of
:class:`~app.algorithms.network_topology.EmergencyNetwork`.

Overview
--------
Each node maintains a **routing table** — a mapping of every known
destination to the best ``(next_hop, cost)`` pair discovered so far.
Nodes exchange their tables with **direct operational neighbours** in
iterative rounds until no table changes (convergence).

The implementation follows the Bellman-Ford relaxation rule::

    dist[u][v] = min over all operational neighbours w of:
                     cost(u → w) + dist[w][v]

Design goals
------------
* **No hard-coded routes** — all paths emerge from iterative relaxation.
* **Link-failure aware** — failed links are invisible; recalculation after
  ``disable_link`` or ``restore_link`` produces fresh, correct tables.
* **Convergence detection** — the engine stops as soon as a full pass
  produces zero table updates.
* **Independent & reusable** — imports only from
  ``app.algorithms.network_topology``; no shared mutable state with Dijkstra.

Usage
-----
    from app.algorithms.distance_vector import DistanceVectorRouter
    from app.algorithms.network_topology import build_sample_network

    net    = build_sample_network()
    router = DistanceVectorRouter(net)
    router.run()                         # converge

    table = router.get_routing_table("ECC-01")
    for dest, entry in table.items():
        print(dest, entry.next_hop, entry.cost)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.algorithms.network_topology import EmergencyNetwork


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingEntry:
    """
    One row in a node's routing table.

    Attributes
    ----------
    destination : str
        Node ID of the final target.
    next_hop : str or None
        Immediate neighbour to forward packets toward *destination*.
        ``None`` when the destination is the node itself or unreachable.
    cost : float
        Total path cost. ``float('inf')`` means unreachable.
    """
    destination: str
    next_hop:    Optional[str]
    cost:        float

    @property
    def reachable(self) -> bool:
        """``True`` when *cost* is finite."""
        return self.cost < float("inf")

    def to_dict(self) -> dict:
        return {
            "destination": self.destination,
            "next_hop":    self.next_hop,
            "cost":        self.cost if self.reachable else None,
            "reachable":   self.reachable,
        }


@dataclass
class ConvergenceReport:
    """
    Summary produced after :meth:`DistanceVectorRouter.run` completes.

    Attributes
    ----------
    converged : bool
        Whether the algorithm reached a stable state within *max_iterations*.
    iterations : int
        Number of full passes performed.
    max_iterations : int
        The cap that was applied.
    iteration_log : list[IterationSnapshot]
        Per-iteration record of which tables changed.
    """
    converged:      bool
    iterations:     int
    max_iterations: int
    iteration_log:  List["IterationSnapshot"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "converged":      self.converged,
            "iterations":     self.iterations,
            "max_iterations": self.max_iterations,
            "iteration_log":  [s.to_dict() for s in self.iteration_log],
        }


@dataclass
class IterationSnapshot:
    """Records which nodes updated their tables in one pass."""
    iteration:     int
    updated_nodes: List[str]   # node IDs whose tables changed this pass

    def to_dict(self) -> dict:
        return {
            "iteration":     self.iteration,
            "updated_nodes": self.updated_nodes,
        }


# Routing table type alias: {node_id: {destination_id: RoutingEntry}}
RoutingTables = Dict[str, Dict[str, RoutingEntry]]


# ─────────────────────────────────────────────────────────────────────────────
# Router class
# ─────────────────────────────────────────────────────────────────────────────

class DistanceVectorRouter:
    """
    Simulates the Distance-Vector routing protocol over an
    :class:`~app.algorithms.network_topology.EmergencyNetwork`.

    The router is stateful: calling :meth:`run` (re)builds routing tables
    from scratch, which makes it safe to call after topology changes (link
    disable / restore).

    Parameters
    ----------
    network : EmergencyNetwork
        The underlying topology.  The router reads link costs and operational
        status directly from the network object, so topology mutations are
        visible immediately on the next :meth:`run`.
    max_iterations : int, optional
        Safety cap on the number of relaxation passes (default 100).
        Prevents infinite loops on negative-cost cycles (not expected in
        emergency networks but guarded against defensively).
    """

    def __init__(self, network: EmergencyNetwork, max_iterations: int = 100) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1.")
        self._network:        EmergencyNetwork = network
        self._max_iterations: int              = max_iterations
        # Routing tables, populated by run()
        self._tables: RoutingTables = {}
        self._last_report: Optional[ConvergenceReport] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> ConvergenceReport:
        """
        (Re)initialise and iterate until convergence or *max_iterations*.

        This method is idempotent — it always starts from a fresh initialisation
        so calling it again after a topology change yields correct results.

        Returns
        -------
        ConvergenceReport
            Summary of the convergence process.
        """
        self._tables = self._initialise_tables()
        report = self._iterate()
        self._last_report = report
        return report

    def get_routing_table(self, node_id: str) -> Dict[str, RoutingEntry]:
        """
        Return the routing table for *node_id* after the last :meth:`run`.

        Parameters
        ----------
        node_id : str
            A node that exists in the network.

        Returns
        -------
        dict[str, RoutingEntry]
            Mapping ``destination_id → RoutingEntry``.

        Raises
        ------
        KeyError
            If *node_id* is not in the network or :meth:`run` has not been called.
        RuntimeError
            If :meth:`run` has not been called yet.
        """
        self._network.get_node(node_id)   # validates existence
        if not self._tables:
            raise RuntimeError("Call run() before querying routing tables.")
        return self._tables[node_id]

    def get_route(self, source: str, destination: str) -> RoutingEntry:
        """
        Return the :class:`RoutingEntry` for reaching *destination* from *source*.

        Raises
        ------
        KeyError
            If either node is unknown.
        RuntimeError
            If :meth:`run` has not been called yet.
        """
        table = self.get_routing_table(source)
        self._network.get_node(destination)   # validate target exists
        return table[destination]

    def get_path(self, source: str, destination: str) -> Tuple[List[str], float, bool]:
        """
        Trace the path from *source* to *destination* using next-hop pointers.
        Returns ``(path, total_cost, reachable)``.
        """
        self._network.get_node(source)
        self._network.get_node(destination)
        if source == destination:
            return [source], 0.0, True

        entry = self.get_route(source, destination)
        if not entry.reachable or entry.next_hop is None:
            return [], float("inf"), False

        path = [source]
        curr = source
        visited = {source}
        total_cost = 0.0

        while curr != destination:
            e = self.get_route(curr, destination)
            if not e.reachable or e.next_hop is None:
                return [], float("inf"), False
            next_hop = e.next_hop
            if next_hop in visited:
                return [], float("inf"), False
            try:
                link = self._network.get_link(curr, next_hop)
                if not link.is_operational:
                    return [], float("inf"), False
                total_cost += link.cost
            except KeyError:
                return [], float("inf"), False

            path.append(next_hop)
            visited.add(next_hop)
            curr = next_hop

        return path, total_cost, True

    def get_path_details(self, source: str, destination: str) -> dict:
        """Return comprehensive telemetry metrics for the DV path."""
        path, total_cost, reachable = self.get_path(source, destination)
        if not reachable:
            return {
                "source":             source,
                "destination":        destination,
                "reachable":          False,
                "path":               [],
                "total_cost":         None,
                "total_delay_ms":     None,
                "bottleneck_bw_mbps": None,
                "hops":               0,
                "links":              [],
            }

        total_delay = 0.0
        bottleneck_bw = float("inf")
        links_info = []

        for i in range(len(path) - 1):
            u = path[i]
            v = path[i + 1]
            link = self._network.get_link(u, v)
            total_delay += link.latency_ms
            if link.bandwidth_mbps < bottleneck_bw:
                bottleneck_bw = link.bandwidth_mbps
            links_info.append({
                "source_id":      u,
                "target_id":      v,
                "cost":           link.cost,
                "latency_ms":     link.latency_ms,
                "bandwidth_mbps": link.bandwidth_mbps,
                "status":         link.status.value,
            })

        return {
            "source":             source,
            "destination":        destination,
            "reachable":          True,
            "path":               path,
            "total_cost":         total_cost,
            "total_delay_ms":     total_delay,
            "bottleneck_bw_mbps": bottleneck_bw if bottleneck_bw != float("inf") else 0.0,
            "hops":               len(path) - 1,
            "links":              links_info,
        }

    def all_routing_tables(self) -> RoutingTables:
        """Return a shallow copy of all routing tables."""
        return {nid: dict(entries) for nid, entries in self._tables.items()}

    def last_report(self) -> Optional[ConvergenceReport]:
        """Return the :class:`ConvergenceReport` from the most recent :meth:`run`."""
        return self._last_report

    def to_dict(self) -> dict:
        """Serialise all routing tables to a JSON-friendly dictionary."""
        return {
            node_id: [e.to_dict() for e in entries.values()]
            for node_id, entries in self._tables.items()
        }

    # ── Initialisation ────────────────────────────────────────────────────────

    def _initialise_tables(self) -> RoutingTables:
        """
        Seed each node's table:
        * Cost 0 to itself, next_hop=None.
        * Direct cost to each operational neighbour, next_hop=neighbour.
        * Infinity to all other nodes.
        """
        nodes = self._network.list_nodes()
        tables: RoutingTables = {}

        for node in nodes:
            nid = node.node_id
            table: Dict[str, RoutingEntry] = {}

            for dest_node in nodes:
                did = dest_node.node_id
                if did == nid:
                    table[did] = RoutingEntry(did, None, 0.0)
                else:
                    table[did] = RoutingEntry(did, None, float("inf"))

            # Seed direct neighbours
            for neighbour_id in self._network.get_available_neighbours(nid):
                link = self._network.get_link(nid, neighbour_id)
                table[neighbour_id] = RoutingEntry(
                    destination=neighbour_id,
                    next_hop=neighbour_id,
                    cost=link.cost,
                )

            tables[nid] = table

        return tables

    # ── Iterative relaxation ──────────────────────────────────────────────────

    def _iterate(self) -> ConvergenceReport:
        """
        Repeatedly apply the Bellman-Ford relaxation rule until no table
        changes or *max_iterations* is reached.
        """
        iteration_log: List[IterationSnapshot] = []

        for iteration in range(1, self._max_iterations + 1):
            updated_nodes: List[str] = []

            for node in self._network.list_nodes():
                nid = node.node_id
                changed = self._relax_node(nid)
                if changed:
                    updated_nodes.append(nid)

            snapshot = IterationSnapshot(
                iteration=iteration,
                updated_nodes=updated_nodes,
            )
            iteration_log.append(snapshot)

            if not updated_nodes:
                # No changes — converged
                return ConvergenceReport(
                    converged=True,
                    iterations=iteration,
                    max_iterations=self._max_iterations,
                    iteration_log=iteration_log,
                )

        # Reached cap without convergence
        return ConvergenceReport(
            converged=False,
            iterations=self._max_iterations,
            max_iterations=self._max_iterations,
            iteration_log=iteration_log,
        )

    def _relax_node(self, node_id: str) -> bool:
        """
        Apply one relaxation pass for *node_id*.

        For every destination, check whether routing through any operational
        neighbour yields a lower cost than the current best.  Update the
        table if an improvement is found.

        Returns
        -------
        bool
            ``True`` if at least one entry was updated.
        """
        table    = self._tables[node_id]
        changed  = False

        for neighbour_id in self._network.get_available_neighbours(node_id):
            direct_link    = self._network.get_link(node_id, neighbour_id)
            direct_cost    = direct_link.cost
            neighbour_table = self._tables[neighbour_id]

            for dest_id, nbr_entry in neighbour_table.items():
                if dest_id == node_id:
                    continue   # skip self

                candidate_cost = direct_cost + nbr_entry.cost
                if candidate_cost < table[dest_id].cost:
                    table[dest_id] = RoutingEntry(
                        destination=dest_id,
                        next_hop=neighbour_id,
                        cost=candidate_cost,
                    )
                    changed = True

        return changed
