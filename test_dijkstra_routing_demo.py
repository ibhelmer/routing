# Copyright 2026 Ib Helmer Nielsen
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the GUI-independent routing model.

Run: python -m unittest -v
The randomized checks use an independent Bellman-Ford implementation.
"""
import ipaddress
import math
import random
import unittest
from unittest.mock import patch

from dijkstra_routing_demo import (
    Link, Network, Packet, Route, RoutingEngine, dijkstra_steps,
    forward_one_hop, make_default_network, routes_from_step, trace_packet,
)


class RoutingModelTests(unittest.TestCase):
    def setUp(self):
        self.network = make_default_network()
        self.engine = RoutingEngine(self.network)

    def test_local_routes_exist_before_spf(self):
        for name, table in self.engine.tables.items():
            self.assertEqual(list(table), [name])
            self.assertIsNone(table[name].next_hop)
            self.assertEqual(self.engine.table_status(name), "local only")

    def test_default_distances(self):
        result = self.engine.calculate("A")
        self.assertEqual(result.distances, {"A": 0, "B": 5, "C": 2, "D": 7, "E": 8, "F": 10})
        self.assertEqual(result.path_to("F"), ("A", "C", "B", "D", "E", "F"))
        self.assertEqual(result.next_hop_to("F"), "C")
        self.assertEqual(result.previous["F"], "E")

    def test_snapshots_are_independent(self):
        steps = list(dijkstra_steps(self.network.adjacency(), "A"))
        first = steps[0]
        self.assertTrue(math.isinf(first.distances["F"]))
        self.assertIsNone(first.previous["F"])
        self.assertEqual(first.settled, frozenset())
        self.assertEqual(steps[-1].distances["F"], 10)

    def test_distances_finalize_in_nondecreasing_order(self):
        steps = list(dijkstra_steps(self.network.adjacency(), "A"))
        settled = [step.distances[step.current] for step in steps if step.phase == "settle"]
        self.assertEqual(settled, sorted(settled))
        self.assertEqual(len(settled), 6)

    def test_relaxation_improves_b_via_c(self):
        updates = [step for step in dijkstra_steps(self.network.adjacency(), "A")
                   if step.phase == "relax" and step.neighbor == "B"]
        self.assertEqual([step.distances["B"] for step in updates], [7, 5])
        self.assertEqual(updates[-1].previous["B"], "C")

    def test_staged_routes_are_not_installed(self):
        first_settle = next(step for step in dijkstra_steps(self.network.adjacency(), "A")
                            if step.phase == "settle")
        self.assertEqual(list(routes_from_step(self.network, first_settle)), ["A"])
        with self.assertRaises(ValueError):
            self.engine.install(first_settle, self.network.revision)
        self.assertEqual(list(self.engine.tables["A"]), ["A"])

    def test_cannot_install_from_an_old_topology(self):
        final = list(dijkstra_steps(self.network.adjacency(), "A"))[-1]
        previous_revision = self.network.revision
        self.network.update_link("A", "C", 9, True)
        with self.assertRaises(ValueError):
            self.engine.install(final, previous_revision)

    def test_every_router_uses_its_own_root(self):
        self.engine.calculate_all()
        hops = {router: self.engine.tables[router]["F"].next_hop for router in "ACBDEF"}
        self.assertEqual(hops, {"A": "C", "C": "B", "B": "D", "D": "E", "E": "F", "F": None})
        self.assertEqual(self.engine.spf_runs, 6)

    def test_packet_uses_installed_tables_without_running_dijkstra(self):
        self.engine.calculate_all()
        with patch("dijkstra_routing_demo.dijkstra_steps", side_effect=AssertionError("SPF during forwarding")):
            packet, trace = trace_packet(self.engine, "A", "10.0.0.6")
        self.assertEqual(packet.path, list("ACBDEF"))
        self.assertEqual(packet.total_cost, 10)
        self.assertEqual(packet.ttl, 11)
        self.assertEqual(packet.outcome, "deliver")
        self.assertEqual(self.engine.spf_runs, 6)
        self.assertEqual([decision.router for decision in trace], list("ACBDEF"))
        self.assertTrue(all(decision.prefix == "10.0.0.6/32" for decision in trace))

    def test_a_table_alone_is_not_enough(self):
        self.engine.calculate("A")
        packet, trace = trace_packet(self.engine, "A", "10.0.0.6")
        self.assertEqual(packet.path, ["A", "C"])
        self.assertEqual(packet.outcome, "drop")
        self.assertIn("no installed route", trace[-1].message)

    def test_loopback_delivery_preserves_ttl(self):
        packet, trace = trace_packet(self.engine, "A", "10.0.0.1", ttl=1)
        self.assertEqual(packet.outcome, "deliver")
        self.assertEqual(packet.ttl, 1)
        self.assertEqual(packet.total_cost, 0)
        self.assertEqual(len(trace), 1)

    def test_ttl_expires_before_forwarding(self):
        self.engine.calculate_all()
        packet, trace = trace_packet(self.engine, "A", "10.0.0.6", ttl=3)
        self.assertEqual(packet.path, list("ACB"))
        self.assertEqual(packet.outcome, "drop")
        self.assertEqual(packet.ttl, 0)
        self.assertIn("TTL expired", trace[-1].message)

    def test_minimum_ttl_for_five_links_is_six(self):
        self.engine.calculate_all()
        failed, _ = trace_packet(self.engine, "A", "10.0.0.6", ttl=5)
        passed, _ = trace_packet(self.engine, "A", "10.0.0.6", ttl=6)
        self.assertEqual(failed.outcome, "drop")
        self.assertEqual(passed.outcome, "deliver")
        self.assertEqual(passed.ttl, 1)

    def test_no_route_to_unknown_destination(self):
        self.engine.calculate_all()
        packet, trace = trace_packet(self.engine, "A", "10.99.0.1")
        self.assertEqual(packet.path, ["A"])
        self.assertEqual(packet.outcome, "drop")
        self.assertEqual(trace[-1].prefix, "--")

    def test_link_failure_and_reconvergence(self):
        self.engine.calculate_all()
        self.network.update_link("D", "E", 1, False)
        self.assertEqual(self.engine.table_status("A"), "STALE")
        failed, trace = trace_packet(self.engine, "A", "10.0.0.6")
        self.assertEqual(failed.path, list("ACBD"))
        self.assertEqual(failed.outcome, "drop")
        self.assertIn("unavailable link", trace[-1].message)
        self.engine.calculate_all()
        recovered, _ = trace_packet(self.engine, "A", "10.0.0.6")
        self.assertEqual(recovered.path, list("ACEF"))
        self.assertEqual(recovered.total_cost, 11)
        self.assertEqual(recovered.outcome, "deliver")

    def test_increasing_cost_changes_next_hop(self):
        self.network.update_link("A", "C", 9, True)
        self.engine.calculate_all()
        packet, _ = trace_packet(self.engine, "A", "10.0.0.6")
        self.assertEqual(packet.path, list("ABDEF"))
        self.assertEqual(packet.total_cost, 12)

    def test_disconnected_router_has_no_remote_routes(self):
        self.network.update_link("D", "F", 6, False)
        self.network.update_link("E", "F", 2, False)
        self.engine.calculate_all()
        self.assertNotIn("F", self.engine.tables["A"])
        self.assertTrue(math.isinf(self.engine.results["A"].distances["F"]))
        self.assertEqual(self.engine.results["A"].path_to("F"), ())
        self.assertEqual(list(self.engine.tables["F"]), ["F"])
        packet, _ = trace_packet(self.engine, "A", "10.0.0.6")
        self.assertEqual(packet.outcome, "drop")

    def test_unchanged_link_does_not_invalidate_tables(self):
        self.engine.calculate_all()
        revision = self.network.revision
        self.assertFalse(self.network.update_link("A", "C", 2, True))
        self.assertEqual(self.network.revision, revision)
        self.assertEqual(self.engine.table_status("A"), "current")

    def test_longest_prefix_matching(self):
        # Although the GUI advertises /32s, the lookup also works with other prefixes.
        self.engine.tables["A"]["default"] = Route("default", ipaddress.IPv4Network("0.0.0.0/0"), "B", 99)
        self.engine.tables["A"]["specific"] = Route("specific", ipaddress.IPv4Network("10.0.0.0/24"), "C", 5)
        self.assertEqual(self.engine.lookup("A", ipaddress.IPv4Address("10.0.0.80")).next_hop, "C")
        self.assertEqual(self.engine.lookup("A", ipaddress.IPv4Address("192.0.2.8")).next_hop, "B")
        self.assertIsNone(self.engine.lookup("A", ipaddress.IPv4Address("10.0.0.1")).next_hop)

    def test_invalid_costs(self):
        for cost in (-1, 0, 1.5, True):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                self.network.update_link("A", "C", cost, True)
        with self.assertRaises(ValueError):
            list(dijkstra_steps({"A": {"B": -1}, "B": {}}, "A"))
        with self.assertRaises(ValueError):
            list(dijkstra_steps({"A": {"B": math.nan}, "B": {}}, "A"))

    def test_invalid_topologies_and_sources(self):
        routers = list(self.network.routers.values())
        for links in ([Link("A", "A", 1)], [Link("A", "Z", 1)], [Link("A", "B", 1), Link("B", "A", 2)]):
            with self.subTest(links=links), self.assertRaises(ValueError):
                Network(routers, links)
        with self.assertRaises(ValueError):
            list(dijkstra_steps(self.network.adjacency(), "Z"))
        with self.assertRaises(ValueError):
            forward_one_hop(self.engine, Packet("Z", ipaddress.IPv4Address("10.0.0.6")))

    def test_invalid_ttl(self):
        for ttl in (0, 256, -1, 1.5, True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                Packet("A", ipaddress.IPv4Address("10.0.0.6"), ttl)

    def test_equal_cost_tie_is_deterministic(self):
        graph = {"A": {"C": 1, "B": 1}, "B": {"D": 1}, "C": {"D": 1}, "D": {}}
        final = list(dijkstra_steps(graph, "A"))[-1]
        self.assertEqual(final.path_to("D"), ("A", "B", "D"))

    def test_forwarding_loop_is_stopped_by_ttl(self):
        prefix = ipaddress.IPv4Network("10.0.0.6/32")
        self.engine.tables["A"]["F"] = Route("F", prefix, "C", 1)
        self.engine.tables["C"]["F"] = Route("F", prefix, "A", 1)
        packet, trace = trace_packet(self.engine, "A", "10.0.0.6", ttl=5)
        self.assertEqual(packet.path, list("ACACA"))
        self.assertEqual(packet.outcome, "drop")
        self.assertIn("TTL expired", trace[-1].message)

    def test_cannot_forward_a_finished_packet(self):
        packet, _ = trace_packet(self.engine, "A", "10.0.0.1")
        with self.assertRaises(ValueError):
            forward_one_hop(self.engine, packet)

    def test_export_contains_installed_versions_and_routes(self):
        self.engine.calculate_all()
        data = self.engine.export_data()
        self.assertEqual(len(data["tables"]), 6)
        self.assertEqual(data["tables"]["A"]["status"], "current")
        self.assertEqual(len(data["tables"]["A"]["routes"]), 6)

    def test_random_graphs_against_bellman_ford(self):
        """40 graphs x 6 roots; all 1,440 source/destination cases are forwarded."""
        routers = list(self.network.routers.values())
        names = sorted(self.network.routers)
        for seed in range(40):
            rng = random.Random(seed)
            links = [Link(a, b, rng.randint(1, 15))
                     for i, a in enumerate(names) for b in names[i + 1:]
                     if rng.random() < 0.43]
            network = Network(routers, links)
            engine = RoutingEngine(network)
            engine.calculate_all()
            graph = network.adjacency()
            for source in names:
                expected = {name: math.inf for name in names}
                expected[source] = 0
                # An independent relaxation-based reference, not heap Dijkstra.
                for _ in range(len(names) - 1):
                    for a in names:
                        for b, weight in graph[a].items():
                            expected[b] = min(expected[b], expected[a] + weight)
                with self.subTest(seed=seed, source=source):
                    self.assertEqual(engine.results[source].distances, expected)
                    for destination in names:
                        packet, _ = trace_packet(engine, source, network.routers[destination].address, ttl=64)
                        if math.isinf(expected[destination]):
                            self.assertEqual(packet.outcome, "drop")
                        else:
                            self.assertEqual(packet.outcome, "deliver")
                            self.assertEqual(packet.total_cost, expected[destination])
                            self.assertEqual(packet.current, destination)


if __name__ == "__main__":
    unittest.main()
