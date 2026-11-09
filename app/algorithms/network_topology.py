"""
ResQNet — app/algorithms/network_topology.py
============================================
Weighted, directed graph that models an emergency communication network.

Key concepts
------------
* Node  — any physical/logical endpoint (control centre, unit, router…).
* Link  — a directed connection between two nodes carrying bandwidth,
          latency, cost, queue capacity, and an operational status flag.

Routing algorithms are intentionally **not** implemented here; this module
only provides the topology data-structure and helper queries.

Usage
-----
    from app.algorithms.network_topology import EmergencyNetwork, build_sample_network

    net = build_sample_network()
    neighbours = net.get_available_neighbours("ECC-01")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    """Logical type of a network node."""
    EMERGENCY_CONTROL_CENTER = "Emergency Control Center"
    POLICE_STATION           = "Police Station"
    FIRE_STATION             = "Fire Station"
    AMBULANCE_UNIT           = "Ambulance Unit"
    FIELD_TEAM               = "Field Team"
    EMERGENCY_SHELTER        = "Emergency Shelter"
    ROUTER                   = "Router"


class LinkStatus(str, Enum):
    """Operational status of a network link."""
    OPERATIONAL = "operational"
    DISABLED    = "disabled"


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Node:
    """
    A vertex in the emergency network graph.

    Attributes
    ----------
    node_id : str
        Unique identifier (e.g. ``"ECC-01"``).
    name : str
        Human-readable label.
    node_type : NodeType
        Logical role of this node.
    x : int
        Visual X-coordinate for canvas rendering.
    y : int
        Visual Y-coordinate for canvas rendering.
    description : str
        Human-readable description.
    """
    node_id:     str
    name:        str
    node_type:   NodeType
    x:           int = 0
    y:           int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id must not be blank.")
        if not self.name.strip():
            raise ValueError("name must not be blank.")
        if not isinstance(self.node_type, NodeType):
            raise TypeError(f"node_type must be a NodeType, got {type(self.node_type)!r}.")

    def to_dict(self) -> dict:
        """Serialise the node to a plain dictionary."""
        return {
            "node_id":   self.node_id,
            "name":      self.name,
            "node_type": self.node_type.value,
        }


@dataclass
class Link:
    """
    A directed, weighted edge between two nodes.

    Attributes
    ----------
    source_id : str
        ID of the originating node.
    target_id : str
        ID of the destination node.
    cost : float
        Abstract routing cost (lower is preferred).
    bandwidth_mbps : float
        Maximum throughput in Megabits per second.
    latency_ms : float
        One-way propagation + processing delay in milliseconds.
    queue_capacity : int
        Maximum number of packets that can be buffered on this link.
    status : LinkStatus
        Whether the link is currently usable.
    """
    source_id:      str
    target_id:      str
    cost:           float
    bandwidth_mbps: float
    latency_ms:     float
    queue_capacity: int
    status:         LinkStatus = LinkStatus.OPERATIONAL

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.source_id == self.target_id:
            raise ValueError("Self-loops are not allowed: source and target must differ.")
        if self.cost < 0:
            raise ValueError(f"cost must be >= 0, got {self.cost}.")
        if self.bandwidth_mbps <= 0:
            raise ValueError(f"bandwidth_mbps must be > 0, got {self.bandwidth_mbps}.")
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms must be >= 0, got {self.latency_ms}.")
        if self.queue_capacity < 0:
            raise ValueError(f"queue_capacity must be >= 0, got {self.queue_capacity}.")

    @property
    def is_operational(self) -> bool:
        """Return ``True`` only if the link can currently carry traffic."""
        return self.status == LinkStatus.OPERATIONAL

    def disable(self) -> None:
        """Mark this link as non-operational (e.g. link failure, maintenance)."""
        self.status = LinkStatus.DISABLED

    def restore(self) -> None:
        """Mark this link as operational again."""
        self.status = LinkStatus.OPERATIONAL

    def toggle(self) -> LinkStatus:
        """Toggle link status between OPERATIONAL and DISABLED."""
        if self.is_operational:
            self.disable()
        else:
            self.restore()
        return self.status

    def to_dict(self) -> dict:
        """Serialise the link to a plain dictionary."""
        return {
            "source_id":      self.source_id,
            "target_id":      self.target_id,
            "cost":           self.cost,
            "bandwidth_mbps": self.bandwidth_mbps,
            "latency_ms":     self.latency_ms,
            "queue_capacity": self.queue_capacity,
            "status":         self.status.value,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────────────────────────

class EmergencyNetwork:
    """
    Directed weighted graph representing an emergency communication network.

    The graph stores nodes in an ID-keyed dictionary and adjacency links in a
    nested dictionary ``{source_id: {target_id: Link}}``.  Multiple parallel
    edges between the same pair of nodes are **not** supported (the latest
    ``add_link`` call overwrites the previous one).

    Examples
    --------
    >>> net = EmergencyNetwork()
    >>> net.add_node(Node("A", "Alpha", NodeType.ROUTER))
    >>> net.add_node(Node("B", "Beta",  NodeType.ROUTER))
    >>> net.add_link(Link("A", "B", cost=1, bandwidth_mbps=100,
    ...                   latency_ms=5, queue_capacity=64))
    >>> net.get_available_neighbours("A")
    ['B']
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, Node] = {}
        # adjacency: {source_id: {target_id: Link}}
        self._adj:   Dict[str, Dict[str, Link]] = {}

    # ── Node operations ───────────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        """
        Add a node to the network.

        Parameters
        ----------
        node : Node
            The node to add.

        Raises
        ------
        TypeError
            If *node* is not a :class:`Node` instance.
        ValueError
            If a node with the same ID already exists.
        """
        if not isinstance(node, Node):
            raise TypeError(f"Expected a Node instance, got {type(node)!r}.")
        if node.node_id in self._nodes:
            raise ValueError(f"Node '{node.node_id}' already exists in the network.")
        self._nodes[node.node_id] = node
        self._adj.setdefault(node.node_id, {})

    def get_node(self, node_id: str) -> Node:
        """
        Retrieve a node by its ID.

        Raises
        ------
        KeyError
            If no node with *node_id* exists.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found.")
        return self._nodes[node_id]

    def list_nodes(self) -> List[Node]:
        """Return all nodes in insertion order."""
        return list(self._nodes.values())

    # ── Link operations ───────────────────────────────────────────────────────

    def add_link(self, link: Link) -> None:
        """
        Add a directed link to the network.

        Parameters
        ----------
        link : Link
            The link to add.

        Raises
        ------
        TypeError
            If *link* is not a :class:`Link` instance.
        KeyError
            If either endpoint node does not exist.
        """
        if not isinstance(link, Link):
            raise TypeError(f"Expected a Link instance, got {type(link)!r}.")
        self._require_node(link.source_id)
        self._require_node(link.target_id)
        self._adj[link.source_id][link.target_id] = link

    def get_link(self, source_id: str, target_id: str) -> Link:
        """
        Retrieve the directed link from *source_id* → *target_id*.

        Raises
        ------
        KeyError
            If the link does not exist.
        """
        self._require_node(source_id)
        self._require_node(target_id)
        try:
            return self._adj[source_id][target_id]
        except KeyError:
            raise KeyError(f"No link from '{source_id}' to '{target_id}'.")

    def list_links(self) -> List[Link]:
        """Return every link in the network (all directions)."""
        links: List[Link] = []
        for targets in self._adj.values():
            links.extend(targets.values())
        return links

    # ── Connectivity queries ──────────────────────────────────────────────────

    def validate_connection(self, source_id: str, target_id: str) -> Tuple[bool, str]:
        """
        Check whether a usable path **exists on the direct link** from
        *source_id* → *target_id*.

        Returns
        -------
        (valid : bool, reason : str)
            *valid* is ``True`` only when the link exists **and** is operational.
        """
        self._require_node(source_id)
        self._require_node(target_id)
        if target_id not in self._adj.get(source_id, {}):
            return False, f"No link from '{source_id}' to '{target_id}'."
        link = self._adj[source_id][target_id]
        if not link.is_operational:
            return False, f"Link '{source_id}' → '{target_id}' is {link.status.value}."
        return True, "Connection is operational."

    def get_available_neighbours(self, node_id: str) -> List[str]:
        """
        Return the IDs of all nodes reachable from *node_id* via an
        **operational** direct link.

        Parameters
        ----------
        node_id : str
            Source node ID.

        Returns
        -------
        list[str]
            Sorted list of reachable neighbour IDs.
        """
        self._require_node(node_id)
        return sorted(
            tid
            for tid, lnk in self._adj.get(node_id, {}).items()
            if lnk.is_operational
        )

    def get_all_neighbours(self, node_id: str) -> List[str]:
        """
        Return IDs of all nodes with a direct link from *node_id*,
        regardless of operational status.
        """
        self._require_node(node_id)
        return sorted(self._adj.get(node_id, {}).keys())

    # ── Link state management ─────────────────────────────────────────────────

    def disable_link(self, source_id: str, target_id: str, bidirectional: bool = False) -> None:
        """
        Mark the link *source_id* → *target_id* as disabled.
        If *bidirectional* is True and reverse link exists, disables it as well.
        """
        link = self.get_link(source_id, target_id)
        link.disable()
        if bidirectional:
            try:
                self.get_link(target_id, source_id).disable()
            except KeyError:
                pass

    def restore_link(self, source_id: str, target_id: str, bidirectional: bool = False) -> None:
        """
        Mark the link *source_id* → *target_id* as operational.
        If *bidirectional* is True and reverse link exists, restores it as well.
        """
        link = self.get_link(source_id, target_id)
        link.restore()
        if bidirectional:
            try:
                self.get_link(target_id, source_id).restore()
            except KeyError:
                pass

    def toggle_link(self, source_id: str, target_id: str, bidirectional: bool = True) -> bool:
        """
        Toggle the link between source_id and target_id.
        If bidirectional=True, toggles reverse link as well if it exists.
        Returns True if now operational, False if disabled.
        """
        link = self.get_link(source_id, target_id)
        new_status = (
            LinkStatus.DISABLED if link.is_operational else LinkStatus.OPERATIONAL
        )
        link.status = new_status
        if bidirectional:
            try:
                self.get_link(target_id, source_id).status = new_status
            except KeyError:
                pass
        return new_status == LinkStatus.OPERATIONAL

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Export the entire network as a JSON-serialisable dictionary."""
        return {
            "nodes": [n.to_dict() for n in self.list_nodes()],
            "links": [l.to_dict() for l in self.list_links()],
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _require_node(self, node_id: str) -> None:
        """Raise ``KeyError`` if *node_id* is not in the network."""
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found in the network.")

    def __repr__(self) -> str:
        return (
            f"EmergencyNetwork("
            f"nodes={len(self._nodes)}, links={len(self.list_links())})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Node Aliases & Resolution
# ─────────────────────────────────────────────────────────────────────────────

NODE_ALIASES: Dict[str, str] = {
    "ECC": "ECC-01",
    "ECC-01": "ECC-01",
    "POL": "PS-01",
    "PS": "PS-01",
    "PS-01": "PS-01",
    "FIRE": "FS-01",
    "FS": "FS-01",
    "FS-01": "FS-01",
    "AMB": "AMB-01",
    "AMB-01": "AMB-01",
    "FT": "FT-01",
    "FT1": "FT-01",
    "FT-01": "FT-01",
    "SHT1": "SHL-01",
    "SHT": "SHL-01",
    "SHL": "SHL-01",
    "SHL-01": "SHL-01",
    "R1": "RTR-01",
    "RTR1": "RTR-01",
    "RTR-01": "RTR-01",
    "R2": "RTR-02",
    "RTR2": "RTR-02",
    "RTR-02": "RTR-02",
}


def resolve_node_id(node_id: str) -> str:
    """Resolve shorthand aliases (e.g. SHT1, ECC, POL) to canonical node IDs."""
    if not node_id:
        return node_id
    clean = str(node_id).strip()
    if clean in NODE_ALIASES:
        return NODE_ALIASES[clean]
    upper = clean.upper()
    if upper in NODE_ALIASES:
        return NODE_ALIASES[upper]
    return clean


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic sample network
# ─────────────────────────────────────────────────────────────────────────────

def build_sample_network() -> EmergencyNetwork:
    """
    Build and return a deterministic sample emergency network.

    Topology (node IDs)
    -------------------
    ::

        ECC-01 (Emergency Control Center)
          │  ╲
          │   ╲── RTR-01 ──────────────╮
          │                            │
        PS-01  ──── RTR-02 ────── FS-01
          │                            │
        AMB-01 ──── FT-01 ──── SHL-01

    Guarantees at least **two distinct routes** between each major
    emergency unit and the control centre via different routers.

    Returns
    -------
    EmergencyNetwork
        Fully populated, ready-to-query network instance.
    """
    net = EmergencyNetwork()

    # ── Nodes ────────────────────────────────────────────────────────────────
    nodes = [
        Node("ECC-01", "Emergency Control Center (ECC)", NodeType.EMERGENCY_CONTROL_CENTER, x=450, y=90, description="Central Emergency Command Headquarters"),
        Node("PS-01",  "Police Station (POL)",           NodeType.POLICE_STATION,           x=220, y=220, description="Law Enforcement & Perimeter Security"),
        Node("FS-01",  "North Fire Station (FIRE)",       NodeType.FIRE_STATION,              x=450, y=260, description="Fire Response & Hazard Containment"),
        Node("AMB-01", "Ambulance Unit (AMB)",           NodeType.AMBULANCE_UNIT,           x=680, y=220, description="Medical Emergency & Ambulance Triage"),
        Node("FT-01",  "Field Team Bravo (FT)",          NodeType.FIELD_TEAM,               x=180, y=490, description="Search & Rescue Field Team"),
        Node("SHL-01", "Emergency Shelter North (SHT1)", NodeType.EMERGENCY_SHELTER,        x=380, y=570, description="Civilian Emergency Shelter North"),
        Node("RTR-01", "North Relay Tower (R1)",         NodeType.ROUTER,                   x=320, y=390, description="Hardened Microwave Mesh Relay Alpha"),
        Node("RTR-02", "East Sector Relay (R2)",         NodeType.ROUTER,                   x=580, y=390, description="Satellite-Backed Mesh Relay Bravo"),
    ]
    for n in nodes:
        net.add_node(n)

    # ── Links ─────────────────────────────────────────────────────────────────
    # Format: (source, target, cost, bandwidth_mbps, latency_ms, queue_cap)
    raw_links = [
        # ECC backbone connections
        ("ECC-01", "RTR-01",  1,  1000, 2,   256),
        ("ECC-01", "PS-01",   3,   500, 5,   128),

        # Router mesh
        ("RTR-01", "RTR-02",  1,  1000, 1,   512),
        ("RTR-01", "FS-01",   2,   500, 4,   128),

        # Police station links (Primary Command Link & North Relay Link)
        ("PS-01",  "ECC-01",  3,   500, 5,   128),
        ("PS-01",  "RTR-01",  5,   200, 8,    64),
        ("PS-01",  "RTR-02",  3,   200, 8,    64),
        ("PS-01",  "AMB-01",  4,   100, 10,   32),

        # RTR-02 fan-out
        ("RTR-02", "FS-01",   2,   500, 3,   128),
        ("RTR-02", "AMB-01",  3,   200, 6,    64),
        ("RTR-02", "SHL-01",  4,   100, 12,   32),

        # Field connections
        ("AMB-01", "FT-01",   5,    50, 15,   16),
        ("FT-01",  "SHL-01",  4,    50, 10,   16),

        # Reverse connections
        ("RTR-01", "ECC-01",  1,  1000, 2,   256),
        ("RTR-01", "PS-01",   5,   200, 8,    64),
        ("RTR-02", "RTR-01",  1,  1000, 1,   512),
        ("FS-01",  "RTR-01",  2,   500, 4,   128),
        ("FS-01",  "RTR-02",  2,   500, 3,   128),
        ("AMB-01", "PS-01",   4,   100, 10,   32),
        ("AMB-01", "RTR-02",  3,   200, 6,    64),
        ("SHL-01", "RTR-02",  4,   100, 12,   32),
        ("SHL-01", "FT-01",   4,    50, 10,   16),
        ("FT-01",  "AMB-01",  5,    50, 15,   16),
        ("SHL-01", "RTR-01",  6,   100, 14,   32),
        ("RTR-01", "SHL-01",  6,   100, 14,   32),
    ]

    for src, tgt, cost, bw, lat, qcap in raw_links:
        net.add_link(Link(
            source_id=src,
            target_id=tgt,
            cost=cost,
            bandwidth_mbps=bw,
            latency_ms=lat,
            queue_capacity=qcap,
        ))

    return net
