"""
ResQNet — tests/test_routing.py
================================
Unit tests for Dijkstra and Distance-Vector routing algorithms.

Coverage
--------
* Dijkstra  : shortest paths, equal-cost alternatives, link failures,
              link restoration, unreachable destinations, single-node
              graphs, step trace integrity.
* DV Router : routing table contents, next-hop correctness, convergence,
              link failures, link restoration, unreachable destinations,
              disconnected graphs, idempotent re-runs.

Run with:
    python -m pytest tests/test_routing.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.algorithms.network_topology import (
    EmergencyNetwork,
    Node,
    NodeType,
    Link,
    build_sample_network,
)
from app.algorithms.dijkstra import dijkstra, DijkstraResult
from app.algorithms.distance_vector import DistanceVectorRouter, RoutingEntry


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_net(*node_ids: str) -> EmergencyNetwork:
    """Create a network with the given node IDs (all typed as ROUTER)."""
    net = EmergencyNetwork()
    for nid in node_ids:
        net.add_node(Node(nid, nid, NodeType.ROUTER))
    return net


def _add_link(net: EmergencyNetwork, src: str, tgt: str,
              cost: float = 1.0, bw: float = 100.0,
              latency: float = 5.0, qcap: int = 64) -> None:
    """Add a directed link with sensible defaults."""
    net.add_link(Link(src, tgt, cost=cost, bandwidth_mbps=bw,
                      latency_ms=latency, queue_capacity=qcap))


def _bidirectional(net: EmergencyNetwork, a: str, b: str,
                   cost: float = 1.0) -> None:
    """Add two directed links A→B and B→A with the same cost."""
    _add_link(net, a, b, cost=cost)
    _add_link(net, b, a, cost=cost)


@pytest.fixture
def linear_net() -> EmergencyNetwork:
    """A → B → C (linear, bidirectional)."""
    net = _make_net("A", "B", "C")
    _bidirectional(net, "A", "B", cost=1)
    _bidirectional(net, "B", "C", cost=2)
    return net


@pytest.fixture
def triangle_net() -> EmergencyNetwork:
    """
    Triangle with two routes from A to C:
      Route 1: A → B → C  (cost 1+1 = 2)
      Route 2: A → C      (cost 5)
    """
    net = _make_net("A", "B", "C")
    _bidirectional(net, "A", "B", cost=1)
    _bidirectional(net, "B", "C", cost=1)
    _bidirectional(net, "A", "C", cost=5)
    return net


@pytest.fixture
def sample_net() -> EmergencyNetwork:
    """Full emergency sample network."""
    return build_sample_network()


@pytest.fixture
def diamond_net() -> EmergencyNetwork:
    """
    Diamond topology — equal-cost paths from S to T:
      S → L → T  (cost 2)
      S → R → T  (cost 2)
    """
    net = _make_net("S", "L", "R", "T")
    _bidirectional(net, "S", "L", cost=1)
    _bidirectional(net, "S", "R", cost=1)
    _bidirectional(net, "L", "T", cost=1)
    _bidirectional(net, "R", "T", cost=1)
    return net


# ─────────────────────────────────────────────────────────────────────────────
# Dijkstra — basic correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestDijkstraBasic:

    def test_direct_path_cost(self, linear_net):
        r = dijkstra(linear_net, "A", "B")
        assert r.reachable
        assert r.total_cost == pytest.approx(1.0)
        assert r.path == ["A", "B"]

    def test_two_hop_path(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        assert r.reachable
        assert r.total_cost == pytest.approx(3.0)
        assert r.path == ["A", "B", "C"]

    def test_source_equals_destination(self, linear_net):
        r = dijkstra(linear_net, "A", "A")
        assert r.reachable
        assert r.total_cost == pytest.approx(0.0)
        assert r.path == ["A"]

    def test_result_is_dijkstra_result_instance(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        assert isinstance(r, DijkstraResult)

    def test_path_starts_at_source_ends_at_dest(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        assert r.path[0]  == "A"
        assert r.path[-1] == "C"

    def test_prefers_lower_cost_route(self, triangle_net):
        """A→B→C (cost 2) is cheaper than A→C (cost 5)."""
        r = dijkstra(triangle_net, "A", "C")
        assert r.reachable
        assert r.total_cost == pytest.approx(2.0)
        assert r.path == ["A", "B", "C"]

    def test_reverse_direction(self, triangle_net):
        """Reverse route C→A should also pick the cheap path."""
        r = dijkstra(triangle_net, "C", "A")
        assert r.reachable
        assert r.total_cost == pytest.approx(2.0)
        assert r.path == ["C", "B", "A"]

    def test_unknown_source_raises(self, linear_net):
        with pytest.raises(KeyError):
            dijkstra(linear_net, "Z", "C")

    def test_unknown_destination_raises(self, linear_net):
        with pytest.raises(KeyError):
            dijkstra(linear_net, "A", "Z")

    def test_sample_net_ecc_to_shelter(self, sample_net):
        """ECC-01 → SHL-01 must be reachable with cost > 0."""
        r = dijkstra(sample_net, "ECC-01", "SHL-01")
        assert r.reachable
        assert r.total_cost > 0
        assert r.path[0] == "ECC-01"
        assert r.path[-1] == "SHL-01"

    def test_sample_net_ecc_to_ambulance(self, sample_net):
        r = dijkstra(sample_net, "ECC-01", "AMB-01")
        assert r.reachable
        assert r.path[-1] == "AMB-01"


# ─────────────────────────────────────────────────────────────────────────────
# Dijkstra — equal-cost paths
# ─────────────────────────────────────────────────────────────────────────────

class TestDijkstraEqualCost:

    def test_diamond_cost_is_optimal(self, diamond_net):
        """Both paths cost 2; result must have cost 2."""
        r = dijkstra(diamond_net, "S", "T")
        assert r.reachable
        assert r.total_cost == pytest.approx(2.0)

    def test_diamond_path_uses_valid_intermediate(self, diamond_net):
        """The path must go through exactly one intermediate node (L or R)."""
        r = dijkstra(diamond_net, "S", "T")
        assert len(r.path) == 3
        assert r.path[1] in ("L", "R")

    def test_diamond_path_is_consistent_hops(self, diamond_net):
        """Each consecutive pair in the path must have a direct link."""
        r = dijkstra(diamond_net, "S", "T")
        for i in range(len(r.path) - 1):
            valid, _ = diamond_net.validate_connection(r.path[i], r.path[i + 1])
            assert valid


# ─────────────────────────────────────────────────────────────────────────────
# Dijkstra — link failures
# ─────────────────────────────────────────────────────────────────────────────

class TestDijkstraLinkFailure:

    def test_unreachable_when_all_paths_fail(self, triangle_net):
        """Disable all edges out of A → C must be unreachable."""
        triangle_net.disable_link("A", "B")
        triangle_net.disable_link("A", "C")
        r = dijkstra(triangle_net, "A", "C")
        assert not r.reachable
        assert r.path == []
        assert r.total_cost == float("inf")

    def test_reroutes_when_primary_fails(self, triangle_net):
        """Disable A→B; algorithm must fall back to direct A→C (cost 5)."""
        triangle_net.disable_link("A", "B")
        r = dijkstra(triangle_net, "A", "C")
        assert r.reachable
        assert r.total_cost == pytest.approx(5.0)
        assert r.path == ["A", "C"]

    def test_failed_link_excluded_from_path(self, triangle_net):
        """The failed link must not appear in the returned path."""
        triangle_net.disable_link("A", "B")
        r = dijkstra(triangle_net, "A", "C")
        # 'B' must not appear as an intermediate node
        assert "B" not in r.path[1:-1]

    def test_sample_net_reroutes_around_rtr01(self, sample_net):
        """
        With ECC-01→RTR-01 disabled, the algorithm must still reach FS-01
        via the secondary path through PS-01.
        """
        sample_net.disable_link("ECC-01", "RTR-01")
        r = dijkstra(sample_net, "ECC-01", "FS-01")
        assert r.reachable
        assert "RTR-01" not in r.path[1:]   # RTR-01 not used as intermediate

    def test_isolation_makes_node_unreachable(self):
        """Isolating a node (no in/out edges) makes it unreachable."""
        net = _make_net("A", "B", "C")
        _bidirectional(net, "A", "B")
        # C has no edges at all
        r = dijkstra(net, "A", "C")
        assert not r.reachable


# ─────────────────────────────────────────────────────────────────────────────
# Dijkstra — link restoration
# ─────────────────────────────────────────────────────────────────────────────

class TestDijkstraLinkRestoration:

    def test_restore_brings_original_path_back(self, triangle_net):
        triangle_net.disable_link("A", "B")
        triangle_net.disable_link("B", "A")
        # Confirm the cheap path is gone
        r_fail = dijkstra(triangle_net, "A", "C")
        assert r_fail.total_cost == pytest.approx(5.0)

        # Restore both directions
        triangle_net.restore_link("A", "B")
        triangle_net.restore_link("B", "A")
        r_ok = dijkstra(triangle_net, "A", "C")
        assert r_ok.total_cost == pytest.approx(2.0)
        assert r_ok.path == ["A", "B", "C"]

    def test_restore_sample_net_link(self, sample_net):
        sample_net.disable_link("ECC-01", "RTR-01")
        sample_net.restore_link("ECC-01", "RTR-01")
        r = dijkstra(sample_net, "ECC-01", "FS-01")
        assert r.reachable
        assert "RTR-01" in r.path


# ─────────────────────────────────────────────────────────────────────────────
# Dijkstra — execution steps
# ─────────────────────────────────────────────────────────────────────────────

class TestDijkstraSteps:

    def test_steps_are_non_empty(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        assert len(r.steps) > 0

    def test_first_step_visits_source(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        assert r.steps[0].visited_node == "A"

    def test_steps_numbered_sequentially(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        for i, step in enumerate(r.steps, start=1):
            assert step.step_number == i

    def test_no_duplicate_visited_nodes(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        visited = [s.visited_node for s in r.steps]
        assert len(visited) == len(set(visited))

    def test_source_cost_in_first_snapshot_is_zero(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        assert r.steps[0].tentative_costs["A"] == pytest.approx(0.0)

    def test_to_dict_structure(self, linear_net):
        r = dijkstra(linear_net, "A", "C")
        d = r.to_dict()
        assert "source" in d
        assert "path" in d
        assert "total_cost" in d
        assert isinstance(d["steps"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Distance Vector — basic correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestDVBasic:

    def test_run_returns_convergence_report(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        report = router.run()
        assert report.converged

    def test_self_cost_is_zero(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        entry = router.get_route("A", "A")
        assert entry.cost == pytest.approx(0.0)
        assert entry.next_hop is None

    def test_direct_neighbour_cost(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        entry = router.get_route("A", "B")
        assert entry.cost == pytest.approx(1.0)
        assert entry.next_hop == "B"

    def test_two_hop_cost(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        entry = router.get_route("A", "C")
        assert entry.cost == pytest.approx(3.0)   # 1 + 2
        assert entry.next_hop == "B"

    def test_prefers_cheaper_route(self, triangle_net):
        router = DistanceVectorRouter(triangle_net)
        router.run()
        entry = router.get_route("A", "C")
        assert entry.cost == pytest.approx(2.0)
        assert entry.next_hop == "B"

    def test_all_nodes_have_routing_tables(self, sample_net):
        router = DistanceVectorRouter(sample_net)
        router.run()
        for node in sample_net.list_nodes():
            table = router.get_routing_table(node.node_id)
            assert isinstance(table, dict)

    def test_routing_table_covers_all_destinations(self, sample_net):
        router = DistanceVectorRouter(sample_net)
        router.run()
        all_ids = {n.node_id for n in sample_net.list_nodes()}
        for node in sample_net.list_nodes():
            table_ids = set(router.get_routing_table(node.node_id).keys())
            assert table_ids == all_ids

    def test_routing_entry_is_instance(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        entry = router.get_route("A", "B")
        assert isinstance(entry, RoutingEntry)

    def test_run_before_query_raises(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        with pytest.raises(RuntimeError, match="run()"):
            router.get_routing_table("A")


# ─────────────────────────────────────────────────────────────────────────────
# Distance Vector — unreachable destinations
# ─────────────────────────────────────────────────────────────────────────────

class TestDVUnreachable:

    def test_isolated_node_unreachable(self):
        net = _make_net("A", "B", "C")
        _bidirectional(net, "A", "B")
        # C is isolated
        router = DistanceVectorRouter(net)
        router.run()
        entry = router.get_route("A", "C")
        assert not entry.reachable
        assert entry.cost == float("inf")
        assert entry.next_hop is None

    def test_disconnected_graph_partial_reachability(self):
        """Two disconnected pairs: A↔B and C↔D."""
        net = _make_net("A", "B", "C", "D")
        _bidirectional(net, "A", "B")
        _bidirectional(net, "C", "D")
        router = DistanceVectorRouter(net)
        router.run()
        # Within same component
        assert router.get_route("A", "B").reachable
        assert router.get_route("C", "D").reachable
        # Cross-component
        assert not router.get_route("A", "C").reachable
        assert not router.get_route("A", "D").reachable
        assert not router.get_route("C", "A").reachable

    def test_all_edges_disabled_makes_all_unreachable(self, triangle_net):
        for src, tgt in [("A", "B"), ("B", "A"),
                         ("B", "C"), ("C", "B"),
                         ("A", "C"), ("C", "A")]:
            triangle_net.disable_link(src, tgt)
        router = DistanceVectorRouter(triangle_net)
        router.run()
        assert not router.get_route("A", "C").reachable
        assert not router.get_route("A", "B").reachable

    def test_unknown_source_raises(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        with pytest.raises(KeyError):
            router.get_routing_table("Z")

    def test_unknown_destination_raises(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        with pytest.raises(KeyError):
            router.get_route("A", "Z")


# ─────────────────────────────────────────────────────────────────────────────
# Distance Vector — convergence
# ─────────────────────────────────────────────────────────────────────────────

class TestDVConvergence:

    def test_linear_net_converges(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        report = router.run()
        assert report.converged

    def test_triangle_net_converges(self, triangle_net):
        router = DistanceVectorRouter(triangle_net)
        report = router.run()
        assert report.converged

    def test_sample_net_converges(self, sample_net):
        router = DistanceVectorRouter(sample_net)
        report = router.run()
        assert report.converged

    def test_iteration_log_is_non_empty(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        report = router.run()
        assert len(report.iteration_log) > 0

    def test_last_iteration_has_no_updates(self, linear_net):
        """The terminating pass must have zero updated nodes."""
        router = DistanceVectorRouter(linear_net)
        report = router.run()
        assert report.iteration_log[-1].updated_nodes == []

    def test_convergence_report_to_dict(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        report = router.run()
        d = report.to_dict()
        assert "converged" in d and "iterations" in d and "iteration_log" in d

    def test_single_node_converges_immediately(self):
        net = _make_net("SOLO")
        router = DistanceVectorRouter(net)
        report = router.run()
        assert report.converged
        assert report.iterations == 1

    def test_last_report_accessible(self, linear_net):
        router = DistanceVectorRouter(linear_net)
        router.run()
        assert router.last_report() is not None
        assert router.last_report().converged


# ─────────────────────────────────────────────────────────────────────────────
# Distance Vector — link failures
# ─────────────────────────────────────────────────────────────────────────────

class TestDVLinkFailure:

    def test_failure_makes_dest_unreachable(self, linear_net):
        """Disable all paths out of A → C must become unreachable."""
        linear_net.disable_link("A", "B")
        router = DistanceVectorRouter(linear_net)
        router.run()
        assert not router.get_route("A", "C").reachable

    def test_failure_reroutes_to_secondary(self, triangle_net):
        """Disable A→B; DV must find A→C directly (cost 5)."""
        triangle_net.disable_link("A", "B")
        triangle_net.disable_link("B", "A")
        router = DistanceVectorRouter(triangle_net)
        router.run()
        entry = router.get_route("A", "C")
        assert entry.reachable
        assert entry.cost == pytest.approx(5.0)
        assert entry.next_hop == "C"

    def test_failed_link_not_used_as_next_hop(self, triangle_net):
        """After disabling B, A's next_hop to C must not be B."""
        triangle_net.disable_link("A", "B")
        triangle_net.disable_link("B", "A")
        router = DistanceVectorRouter(triangle_net)
        router.run()
        entry = router.get_route("A", "C")
        assert entry.next_hop != "B"

    def test_sample_net_reroutes_after_rtr01_failure(self, sample_net):
        """Disable ECC-01→RTR-01; DV should still reach AMB-01 via PS-01."""
        sample_net.disable_link("ECC-01", "RTR-01")
        router = DistanceVectorRouter(sample_net)
        router.run()
        entry = router.get_route("ECC-01", "AMB-01")
        assert entry.reachable
        assert entry.next_hop != "RTR-01"

    def test_partial_failure_still_converges(self, sample_net):
        sample_net.disable_link("RTR-01", "RTR-02")
        router = DistanceVectorRouter(sample_net)
        report = router.run()
        assert report.converged


# ─────────────────────────────────────────────────────────────────────────────
# Distance Vector — link restoration
# ─────────────────────────────────────────────────────────────────────────────

class TestDVLinkRestoration:

    def test_restore_recovers_cheap_path(self, triangle_net):
        # Disable the cheap path
        triangle_net.disable_link("A", "B")
        triangle_net.disable_link("B", "A")
        router = DistanceVectorRouter(triangle_net)
        router.run()
        assert router.get_route("A", "C").cost == pytest.approx(5.0)

        # Restore
        triangle_net.restore_link("A", "B")
        triangle_net.restore_link("B", "A")
        router.run()
        entry = router.get_route("A", "C")
        assert entry.cost == pytest.approx(2.0)
        assert entry.next_hop == "B"

    def test_rerun_after_restore_is_idempotent(self, triangle_net):
        router = DistanceVectorRouter(triangle_net)
        router.run()
        cost1 = router.get_route("A", "C").cost
        router.run()
        cost2 = router.get_route("A", "C").cost
        assert cost1 == pytest.approx(cost2)

    def test_restoration_re_converges(self, sample_net):
        sample_net.disable_link("ECC-01", "RTR-01")
        router = DistanceVectorRouter(sample_net)
        router.run()
        sample_net.restore_link("ECC-01", "RTR-01")
        report = router.run()
        assert report.converged


# ─────────────────────────────────────────────────────────────────────────────
# Cross-algorithm consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossAlgorithmConsistency:
    """
    For any reachable (source, destination) pair, Dijkstra and DV must agree
    on the optimal total cost (they may differ on tie-broken paths).
    """

    @pytest.mark.parametrize("src,dst", [
        ("ECC-01", "FS-01"),
        ("ECC-01", "AMB-01"),
        ("ECC-01", "SHL-01"),
        ("PS-01",  "FT-01"),
        ("FS-01",  "ECC-01"),
        ("AMB-01", "SHL-01"),
    ])
    def test_costs_agree(self, sample_net, src, dst):
        dj     = dijkstra(sample_net, src, dst)
        router = DistanceVectorRouter(sample_net)
        router.run()
        dv_entry = router.get_route(src, dst)

        assert dj.reachable == dv_entry.reachable, (
            f"Reachability disagrees for {src}→{dst}: "
            f"Dijkstra={dj.reachable}, DV={dv_entry.reachable}"
        )
        if dj.reachable:
            assert dj.total_cost == pytest.approx(dv_entry.cost), (
                f"Cost disagrees for {src}→{dst}: "
                f"Dijkstra={dj.total_cost}, DV={dv_entry.cost}"
            )
