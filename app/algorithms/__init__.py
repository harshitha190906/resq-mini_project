"""
ResQNet — Algorithms package.

Public exports
--------------
network_topology
    EmergencyNetwork, Node, NodeType, Link, LinkStatus, build_sample_network

dijkstra
    dijkstra(), DijkstraResult, DijkstraStep

distance_vector
    DistanceVectorRouter, RoutingEntry, ConvergenceReport

crc
    CRCEngine, CRCPreset, CRCGenerateResult, CRCVerifyResult

go_back_n
    GBNSimulator, GBNResult, GBNEvent, GBNEventType

leaky_bucket
    LeakyBucket, LeakyBucketResult, LeakyBucketEvent

Planned future modules
----------------------
  - congestion.py     : Congestion detection & scoring
  - priority_queue.py : Priority-based message queuing for emergencies
"""

from app.algorithms.network_topology import (
    EmergencyNetwork,
    Node,
    NodeType,
    Link,
    LinkStatus,
    build_sample_network,
)
from app.algorithms.dijkstra import dijkstra, DijkstraResult, DijkstraStep
from app.algorithms.distance_vector import (
    DistanceVectorRouter,
    RoutingEntry,
    ConvergenceReport,
    IterationSnapshot,
)

from app.algorithms.crc import (
    CRCEngine,
    CRCPreset,
    CRCGenerateResult,
    CRCVerifyResult,
    CRCErrorInjectionResult,
)
from app.algorithms.go_back_n import (
    GBNSimulator,
    GBNResult,
    GBNEvent,
    GBNEventType,
)
from app.algorithms.leaky_bucket import (
    LeakyBucket,
    LeakyBucketResult,
    LeakyBucketEvent,
)

__all__ = [
    # topology
    "EmergencyNetwork", "Node", "NodeType", "Link", "LinkStatus",
    "build_sample_network",
    # dijkstra
    "dijkstra", "DijkstraResult", "DijkstraStep",
    # distance vector
    "DistanceVectorRouter", "RoutingEntry", "ConvergenceReport",
    "IterationSnapshot",
    # crc
    "CRCEngine", "CRCPreset", "CRCGenerateResult",
    "CRCVerifyResult", "CRCErrorInjectionResult",
    # go-back-n
    "GBNSimulator", "GBNResult", "GBNEvent", "GBNEventType",
    # leaky bucket
    "LeakyBucket", "LeakyBucketResult", "LeakyBucketEvent",
]
