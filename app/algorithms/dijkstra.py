"""
ResQNet — app/algorithms/dijkstra.py
=====================================
Dijkstra's single-source shortest-path algorithm adapted for the
:class:`~app.algorithms.network_topology.EmergencyNetwork` weighted graph.

Design decisions
----------------
* Uses Python's ``heapq`` (binary min-heap) for O((V + E) log V) performance.
* Skips every link whose ``status`` is not ``OPERATIONAL``; failed links are
  completely invisible to the algorithm.
* Returns a rich :class:`DijkstraResult` dataclass so callers can inspect the
  path, total cost, and the step-by-step execution trace independently.
* No routing state is mutated — the network graph is read-only from this
  module's perspective.

Usage
-----
    from app.algorithms.dijkstra import dijkstra
    from app.algorithms.network_topology import build_sample_network

    net    = build_sample_network()
    result = dijkstra(net, "ECC-01", "SHL-01")

    if result.reachable:
        print(result.path, result.total_cost)
    else:
        print("Destination unreachable")
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.algorithms.network_topology import EmergencyNetwork


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DijkstraStep:
    """
    One iteration of the main Dijkstra loop.

    Attributes
    ----------
    step_number : int
        1-based index of this relaxation step.
    visited_node : str
        The node dequeued (settled) at this step.
    tentative_costs : dict
        Snapshot of all current best-known costs at the moment of settlement.
    """
    step_number:      int
    visited_node:     str
    tentative_costs:  Dict[str, float]


@dataclass
class DijkstraLogEvent:
    """A discrete event in Dijkstra's algorithm execution."""
    step: int
    event_type: str  # "start", "init", "visit", "evaluate", "update", "skip_failed", "skip_visited", "destination_reached", "complete", "unreachable"
    message: str
    node: Optional[str] = None
    neighbor: Optional[str] = None
    cost: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "event_type": self.event_type,
            "message": self.message,
            "node": self.node,
            "neighbor": self.neighbor,
            "cost": self.cost,
        }


@dataclass
class DijkstraResult:
    """
    Complete output of a Dijkstra run.

    Attributes
    ----------
    source : str
        Source node ID.
    destination : str
        Target node ID.
    path : list[str]
        Ordered node IDs from *source* to *destination*.
        Empty list when *destination* is unreachable.
    total_cost : float
        Sum of edge costs along *path*.
        ``float('inf')`` when *destination* is unreachable.
    reachable : bool
        Convenience flag — ``True`` iff a path exists.
    steps : list[DijkstraStep]
        Ordered execution trace (one entry per settled node).
    log : list[DijkstraLogEvent]
        Detailed relaxation and event log.
    total_delay_ms : float
        Total accumulated latency along the path in milliseconds.
    bottleneck_bw_mbps : float
        Minimum bandwidth available along the path in Mbps.
    hops : int
        Number of hops along the path.
    links : list[dict]
        Detailed info for each link along the path.
    """
    source:             str
    destination:        str
    path:               List[str]
    total_cost:         float
    reachable:          bool
    steps:              List[DijkstraStep] = field(default_factory=list)
    log:                List[DijkstraLogEvent] = field(default_factory=list)
    total_delay_ms:     Optional[float] = None
    bottleneck_bw_mbps: Optional[float] = None
    hops:               int = 0
    links:              List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise the result to a JSON-serialisable dictionary."""
        return {
            "source":             self.source,
            "destination":        self.destination,
            "path":               self.path,
            "total_cost":         self.total_cost if self.reachable else None,
            "reachable":          self.reachable,
            "total_delay_ms":     self.total_delay_ms if self.reachable else None,
            "bottleneck_bw_mbps": self.bottleneck_bw_mbps if self.reachable else None,
            "hops":               self.hops,
            "links":              self.links,
            "log":                [e.to_dict() for e in self.log],
            "steps": [
                {
                    "step_number":     s.step_number,
                    "visited_node":    s.visited_node,
                    "tentative_costs": {
                        k: (v if v != float("inf") else None)
                        for k, v in s.tentative_costs.items()
                    },
                }
                for s in self.steps
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Algorithm
# ─────────────────────────────────────────────────────────────────────────────

def dijkstra(
    network: EmergencyNetwork,
    source: str,
    destination: str,
) -> DijkstraResult:
    """
    Run Dijkstra's algorithm on *network* from *source* to *destination*.

    Only **operational** links (``LinkStatus.OPERATIONAL``) are considered.
    Failed links are completely skipped, so the algorithm naturally routes
    around network faults.

    Parameters
    ----------
    network : EmergencyNetwork
        The network graph to search.  Must contain both *source* and
        *destination* nodes.
    source : str
        ID of the starting node.
    destination : str
        ID of the target node.

    Returns
    -------
    DijkstraResult
        Contains the shortest path (if any), total cost, reachability flag,
        and per-step execution trace.

    Raises
    ------
    KeyError
        If *source* or *destination* are not present in *network*.
    """
    # Validate that both endpoints exist (raises KeyError if not)
    network.get_node(source)
    network.get_node(destination)

    all_node_ids: List[str] = [n.node_id for n in network.list_nodes()]

    # dist[node_id] = best known cost from source
    dist: Dict[str, float] = {nid: float("inf") for nid in all_node_ids}
    dist[source] = 0.0

    # prev[node_id] = predecessor on the best path found so far
    prev: Dict[str, Optional[str]] = {nid: None for nid in all_node_ids}

    # Min-heap entries: (cost, node_id)
    heap: List[tuple] = [(0.0, source)]

    visited: set = set()
    steps:   List[DijkstraStep] = []
    log:     List[DijkstraLogEvent] = []
    step_number = 0
    log_step = 0

    def add_log(event_type: str, message: str, node: Optional[str] = None, neighbor: Optional[str] = None, cost: Optional[float] = None) -> None:
        nonlocal log_step
        log_step += 1
        log.append(DijkstraLogEvent(
            step=log_step,
            event_type=event_type,
            message=message,
            node=node,
            neighbor=neighbor,
            cost=cost,
        ))

    add_log("start", f"Algorithm started: Shortest path routing from '{source}' to '{destination}'", node=source)
    add_log("init", f"Source distance initialized to zero: dist[{source}] = 0.0", node=source, cost=0.0)

    while heap:
        current_cost, current_node = heapq.heappop(heap)

        # Skip stale heap entries (lazy deletion)
        if current_node in visited:
            continue
        visited.add(current_node)

        step_number += 1
        steps.append(DijkstraStep(
            step_number=step_number,
            visited_node=current_node,
            tentative_costs=dict(dist),   # snapshot
        ))

        add_log("visit", f"Dequeued settled node '{current_node}' with tentative cost {current_cost:.1f}", node=current_node, cost=current_cost)

        # Early exit once the destination is settled
        if current_node == destination:
            add_log("destination_reached", f"Destination '{destination}' settled with optimal cost {current_cost:.1f}", node=destination, cost=current_cost)
            break

        # Check all outgoing edges (including failed links for logging)
        for neighbour_id in network.get_all_neighbours(current_node):
            link = network.get_link(current_node, neighbour_id)
            if not link.is_operational:
                add_log("skip_failed", f"Link {current_node} → {neighbour_id} ignored (status: {link.status.value.upper()})", node=current_node, neighbor=neighbour_id)
                continue
            if neighbour_id in visited:
                continue

            new_cost = current_cost + link.cost
            add_log("evaluate", f"Evaluating neighbor '{neighbour_id}' via {current_node} → {neighbour_id} (link cost: {link.cost:.1f}, candidate: {new_cost:.1f})", node=current_node, neighbor=neighbour_id, cost=new_cost)

            if new_cost < dist[neighbour_id]:
                prev_cost_str = "∞" if dist[neighbour_id] == float("inf") else f"{dist[neighbour_id]:.1f}"
                dist[neighbour_id] = new_cost
                prev[neighbour_id] = current_node
                heapq.heappush(heap, (new_cost, neighbour_id))
                add_log("update", f"Distance updated for '{neighbour_id}': improved from {prev_cost_str} to {new_cost:.1f} via '{current_node}'", node=current_node, neighbor=neighbour_id, cost=new_cost)

    # ── Reconstruct path ──────────────────────────────────────────────────────
    if dist[destination] == float("inf"):
        add_log("unreachable", f"No available route exists between '{source}' and '{destination}'. Destination unreachable.", node=source, neighbor=destination)
        return DijkstraResult(
            source=source,
            destination=destination,
            path=[],
            total_cost=float("inf"),
            reachable=False,
            steps=steps,
            log=log,
            total_delay_ms=None,
            bottleneck_bw_mbps=None,
            hops=0,
            links=[],
        )

    path: List[str] = []
    node: Optional[str] = destination
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()

    # Calculate telemetry metrics along path
    total_delay = 0.0
    bottleneck_bw = float("inf")
    links_info: List[dict] = []

    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        lnk = network.get_link(u, v)
        total_delay += lnk.latency_ms
        if lnk.bandwidth_mbps < bottleneck_bw:
            bottleneck_bw = lnk.bandwidth_mbps
        links_info.append({
            "source_id":      u,
            "target_id":      v,
            "cost":           lnk.cost,
            "latency_ms":     lnk.latency_ms,
            "bandwidth_mbps": lnk.bandwidth_mbps,
            "status":         lnk.status.value,
        })

    add_log("complete", f"Shortest route found: {' → '.join(path)} (Cost: {dist[destination]:.1f}, Delay: {total_delay:.1f}ms, Hops: {len(path)-1})", cost=dist[destination])

    return DijkstraResult(
        source=source,
        destination=destination,
        path=path,
        total_cost=dist[destination],
        reachable=True,
        steps=steps,
        log=log,
        total_delay_ms=total_delay,
        bottleneck_bw_mbps=bottleneck_bw if bottleneck_bw != float("inf") else 0.0,
        hops=len(path) - 1,
        links=links_info,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _operational_edges(network: EmergencyNetwork, node_id: str):
    """
    Yield ``(neighbour_id, Link)`` pairs for every **operational** outgoing
    edge from *node_id*.
    """
    # Access internal adjacency via the public get_link interface
    for neighbour_id in network.get_all_neighbours(node_id):
        link = network.get_link(node_id, neighbour_id)
        if link.is_operational:
            yield neighbour_id, link
