#!/usr/bin/env python3
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

"""Interactive Dijkstra and hop-by-hop IP routing laboratory.

Run: python dijkstra_routing_demo.py
Headless example: python dijkstra_routing_demo.py --print-tables

Python 3.10+; the GUI uses only the standard library (Tkinter / Tcl-Tk).
Names, comments, documentation, and GUI labels are intentionally in English.
This is a teaching simulation, NOT an OSPF implementation or a packet sender.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field, replace
import heapq
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Iterator
import webbrowser

__author__ = "Ib Helmer Nielsen"
__copyright__ = "Copyright 2026 Ib Helmer Nielsen"
__license__ = "Apache-2.0"
__version__ = "1.4.0"

APP_NAME = "Dijkstra Routing Lab"
REPOSITORY_URL = "https://github.com/ibhelmer/routing"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
ABOUT_SECTIONS = (
    ("PURPOSE", "An interactive teaching application for understanding least-cost routing "
     "and the difference between calculating routes and forwarding packets."),
    ("01  CALCULATE ROUTES", "Follow Dijkstra's algorithm step by step. Inspect tentative "
     "distances, settled routers, predecessor chains and the shortest-path tree."),
    ("02  BUILD ROUTING TABLES", "Run a separate calculation at each router and see how "
     "destination prefixes, costs and next hops become installed routing entries."),
    ("03  FORWARD AND EXPERIMENT", "Watch each router look up a packet's destination, "
     "choose its next hop and reduce TTL. Add routers, edit links, simulate failures, "
     "and save or reload your classroom topologies."),
    ("SCOPE", "A self-contained simulation: no real packets are sent and no operating-system "
     "network settings are changed. This is not a full OSPF implementation; it omits "
     "LSA flooding, ECMP and Ethernet/ARP."),
)



# ---------------------------------------------------------------------------
# 1. Topology: routers advertise /32 loopbacks; link costs are positive integers.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Router:
    name: str
    address: str
    x: float
    y: float

    @property
    def prefix(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(f"{self.address}/32")


@dataclass
class Link:
    a: str
    b: str
    cost: int
    enabled: bool = True

    @property
    def key(self) -> tuple[str, str]:
        return tuple(sorted((self.a, self.b)))


class Network:
    """A small undirected link-state graph with a topology revision number."""

    def __init__(self, routers: list[Router], links: list[Link]) -> None:
        self.routers = {router.name: router for router in routers}
        if len(self.routers) != len(routers):
            raise ValueError("Router names must be unique.")
        addresses = [router.address for router in routers]
        if len(set(addresses)) != len(addresses):
            raise ValueError("Router loopback addresses must be unique.")
        for router in routers:
            self._validate_router(router)
        self.links: dict[tuple[str, str], Link] = {}
        for link in links:
            self._validate_cost(link.cost)
            if link.a == link.b or link.a not in self.routers or link.b not in self.routers:
                raise ValueError("Every link must join two different, known routers.")
            if link.key in self.links:
                raise ValueError("Parallel links are not supported by this example.")
            self.links[link.key] = Link(link.a, link.b, link.cost, link.enabled)
        self.revision = 1

    @staticmethod
    def _validate_router(router: Router) -> None:
        if not isinstance(router.name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,11}", router.name):
            raise ValueError("Name: use 1-12 letters, digits or underscores, starting with a letter.")
        try:
            address = ipaddress.IPv4Address(router.address)
        except (ValueError, TypeError) as error:
            raise ValueError("Enter a valid IPv4 loopback address, without /32.") from error
        if address.is_multicast or address.is_unspecified or int(address) == 0xFFFFFFFF:
            raise ValueError("Use a unicast IPv4 address, not multicast, unspecified or limited broadcast.")
        Network._validate_position(router.x, router.y)

    @staticmethod
    def _validate_position(x: float, y: float) -> None:
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
            raise ValueError("Router positions must be finite numbers between 0 and 1.")

    def add_router(self, router: Router, connect_to: str | None = None, cost: int = 1) -> None:
        """Add a router and optionally its first link as one validated edit."""
        self._validate_router(router)
        if router.name in self.routers:
            raise ValueError(f"Router {router.name} already exists; choose a unique name.")
        if any(ipaddress.IPv4Address(r.address) == ipaddress.IPv4Address(router.address)
               for r in self.routers.values()):
            raise ValueError(f"IP address {router.address} is already in use.")
        if connect_to is not None:
            if connect_to not in self.routers:
                raise ValueError("Choose an existing router for the first connection.")
            self._validate_cost(cost)
        # Validate everything before mutating either collection.
        self.routers[router.name] = router
        if connect_to is not None:
            link = Link(router.name, connect_to, cost)
            self.links[link.key] = link
        self.revision += 1

    def add_link(self, a: str, b: str, cost: int, enabled: bool = True) -> None:
        self._validate_cost(cost)
        if a == b or a not in self.routers or b not in self.routers:
            raise ValueError("Choose two different, existing routers.")
        link = Link(a, b, cost, bool(enabled))
        if link.key in self.links:
            raise ValueError("This link already exists. Use the link editor to change its cost or state.")
        self.links[link.key] = link
        self.revision += 1

    def move_router(self, name: str, x: float, y: float) -> None:
        """Move a drawing only: link costs, table versions and SPF stay unchanged."""
        self._validate_position(x, y)
        if name not in self.routers:
            raise ValueError(f"Unknown router: {name}")
        self.routers[name] = replace(self.routers[name], x=x, y=y)

    def suggest_router(self) -> Router:
        """Suggest unused identifiers and an open position; do not change the graph."""
        name = next((chr(code) for code in range(ord("A"), ord("Z") + 1)
                     if chr(code) not in self.routers), "")
        index = 1
        while not name:
            candidate = f"R{index}"
            if candidate not in self.routers:
                name = candidate
            index += 1
        used = {ipaddress.IPv4Address(r.address) for r in self.routers.values()}
        address = ipaddress.IPv4Address("10.0.0.1")
        while address in used:
            address += 1
        if not self.routers:
            return Router(name, str(address), 0.5, 0.5)
        # Choose the grid point furthest from existing routers.
        points = [(x / 10, y / 10) for x in range(1, 10) for y in range(1, 10)]
        x, y = max(points, key=lambda point: min(
            (point[0] - r.x) ** 2 + (point[1] - r.y) ** 2 for r in self.routers.values()))
        return Router(name, str(address), x, y)

    @staticmethod
    def _validate_cost(cost: int) -> None:
        # Strictly positive costs keep the forwarding example simple and loop-free
        # after full convergence. Dijkstra itself also permits zero-weight edges.
        if isinstance(cost, bool) or not isinstance(cost, int) or cost <= 0:
            raise ValueError("Link cost must be a positive integer.")

    def adjacency(self) -> dict[str, dict[str, int]]:
        graph: dict[str, dict[str, int]] = {name: {} for name in self.routers}
        for link in self.links.values():
            if link.enabled:
                graph[link.a][link.b] = link.cost
                graph[link.b][link.a] = link.cost
        return graph

    def update_link(self, a: str, b: str, cost: int, enabled: bool) -> bool:
        self._validate_cost(cost)
        link = self.links[tuple(sorted((a, b)))]
        if (link.cost, link.enabled) == (cost, bool(enabled)):
            return False
        link.cost, link.enabled = cost, bool(enabled)
        self.revision += 1
        return True


def make_default_network() -> Network:
    """The best A-to-F path costs 10, but uses more hops than another path."""
    routers = [
        Router("A", "10.0.0.1", 0.11, 0.50),
        Router("B", "10.0.0.2", 0.35, 0.20),
        Router("C", "10.0.0.3", 0.35, 0.80),
        Router("D", "10.0.0.4", 0.64, 0.20),
        Router("E", "10.0.0.5", 0.64, 0.80),
        Router("F", "10.0.0.6", 0.89, 0.50),
    ]
    links = [
        Link("A", "B", 7), Link("A", "C", 2), Link("B", "C", 3),
        Link("B", "D", 2), Link("C", "D", 8), Link("C", "E", 7),
        Link("D", "E", 1), Link("D", "F", 6), Link("E", "F", 2),
    ]
    return Network(routers, links)


# ---------------------------------------------------------------------------
# Graph persistence: JSON contains topology only, never executable/session state.
# ---------------------------------------------------------------------------

GRAPH_FORMAT = "dijkstra-routing-lab.graph"
GRAPH_VERSION = 1
MAX_GRAPH_BYTES = 2 * 1024 * 1024
MAX_GRAPH_ROUTERS = 256
MAX_GRAPH_LINKS = 16384
MAX_GRAPH_COST = 1_000_000_000


def graph_to_data(network: Network) -> dict:
    """Return a deterministic, independent snapshot including drawing positions."""
    return {
        "format": GRAPH_FORMAT,
        "version": GRAPH_VERSION,
        "routers": [{"name": r.name, "address": r.address, "x": r.x, "y": r.y}
                    for _, r in sorted(network.routers.items())],
        "links": [{"a": link.a, "b": link.b, "cost": link.cost, "enabled": link.enabled}
                  for _, link in sorted(network.links.items())],
    }


def graph_from_data(data: object) -> Network:
    """Validate a complete graph before constructing a fresh, independent network.

    Also read the original Export tables format (v1.0/v1.1). Its installed tables
    and revision counters are deliberately ignored. Exports without positions get
    a deterministic circular layout; saved positions are never silently repaired.
    """
    if not isinstance(data, dict):
        raise ValueError("The graph file must contain a JSON object.")
    if "format" in data:
        if data["format"] != GRAPH_FORMAT:
            raise ValueError("This is not a Dijkstra Routing Lab graph file.")
        if type(data.get("version")) is not int or data["version"] != GRAPH_VERSION:
            raise ValueError("Unsupported graph format version; this application reads version 1.")
        rows = data.get("routers")
    elif (data.get("model") == "Dijkstra teaching simulation; loopback destinations; no ECMP"
          and isinstance(data.get("routers"), dict)):
        # Migrate earlier exports without trusting their routing-table contents.
        addresses = data["routers"]
        if not 0 <= len(addresses) <= MAX_GRAPH_ROUTERS:
            raise ValueError(f"A graph must contain 0-{MAX_GRAPH_ROUTERS} routers.")
        if any(not isinstance(name, str) for name in addresses):
            raise ValueError("Router names must be strings.")
        positions = data.get("positions")
        if "positions" in data and (not isinstance(positions, dict) or set(positions) != set(addresses)):
            raise ValueError("Exported positions must contain exactly one entry per router.")
        rows = []
        for index, (name, address) in enumerate(sorted(addresses.items())):
            angle = 2 * math.pi * index / len(addresses)
            position = ({"x": 0.5 + 0.38 * math.cos(angle), "y": 0.5 + 0.38 * math.sin(angle)}
                        if positions is None else positions[name])
            if not isinstance(position, dict):
                raise ValueError(f"Invalid position for router {name}.")
            rows.append({"name": name, "address": address, "x": position.get("x"), "y": position.get("y")})
    else:
        raise ValueError("Choose a saved graph or a Dijkstra Routing Lab Export tables JSON file.")

    if not isinstance(rows, list) or not 0 <= len(rows) <= MAX_GRAPH_ROUTERS:
        raise ValueError(f"The routers field must be a list of 0-{MAX_GRAPH_ROUTERS} routers.")
    routers = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not {"name", "address", "x", "y"} <= row.keys():
            raise ValueError(f"Router entry {index + 1} needs name, address, x and y.")
        if not isinstance(row["name"], str) or not isinstance(row["address"], str):
            raise ValueError("Router names and IPv4 addresses must be strings.")
        router = Router(row["name"], row["address"], row["x"], row["y"])
        try:
            Network._validate_router(router)
        except (ValueError, OverflowError) as error:
            raise ValueError(f"Invalid router entry {index + 1}: {error}") from error
        routers.append(router)

    entries = data.get("links")
    if not isinstance(entries, list) or len(entries) > MAX_GRAPH_LINKS:
        raise ValueError(f"The links field must be a list with at most {MAX_GRAPH_LINKS} entries.")
    links = []
    for index, row in enumerate(entries):
        if not isinstance(row, dict) or not {"a", "b", "cost", "enabled"} <= row.keys():
            raise ValueError(f"Link entry {index + 1} needs a, b, cost and enabled.")
        if not isinstance(row["a"], str) or not isinstance(row["b"], str):
            raise ValueError("Link endpoints must be router names.")
        if type(row["enabled"]) is not bool:
            raise ValueError("Link enabled must be true or false, not a string or number.")
        if type(row["cost"]) is not int or not 1 <= row["cost"] <= MAX_GRAPH_COST:
            raise ValueError(f"Link cost must be an integer from 1 to {MAX_GRAPH_COST}.")
        links.append(Link(row["a"], row["b"], row["cost"], row["enabled"]))
    # Network checks duplicate names/IPs/links, self-links and unknown endpoints.
    return Network(routers, links)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is not allowed: {value}.")


def load_graph_file(filename: str | Path) -> Network:
    """Read bounded UTF-8 JSON; failure never modifies an existing network."""
    with Path(filename).open("rb") as stream:
        raw = stream.read(MAX_GRAPH_BYTES + 1)
    if len(raw) > MAX_GRAPH_BYTES:
        raise ValueError("The graph file is too large (maximum 2 MiB).")
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_json_object,
                          parse_constant=_reject_json_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"Cannot read this UTF-8 JSON graph: {error}") from error
    return graph_from_data(data)


def save_graph_file(network: Network, filename: str | Path) -> None:
    """Validate, then replace the destination via a temporary file in its directory.

    Close the temporary file BEFORE os.replace(), including on Windows. A failed
    write/replacement leaves an existing destination untouched. This is not a
    backup system and does not promise power-loss durability on every filesystem.
    """
    data = graph_to_data(network)
    graph_from_data(data)  # Never write a file that this version cannot load.
    raw = (json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_GRAPH_BYTES:
        raise ValueError("The graph is too large to save (maximum 2 MiB).")
    destination = Path(filename)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                         prefix=f".{destination.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. Control plane: an observable, real Dijkstra implementation.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DijkstraStep:
    source: str
    phase: str
    current: str | None
    neighbor: str | None
    distances: dict[str, float]
    previous: dict[str, str | None]
    settled: frozenset[str]
    message: str
    code_line: int

    def path_to(self, destination: str) -> tuple[str, ...]:
        if destination not in self.distances or math.isinf(self.distances[destination]):
            return ()
        path: list[str] = []
        node: str | None = destination
        while node is not None:
            path.append(node)
            node = self.previous[node]
        return tuple(reversed(path))

    def next_hop_to(self, destination: str) -> str | None:
        path = self.path_to(destination)
        return path[1] if len(path) > 1 else None


def metric(value: float) -> str:
    return "inf" if math.isinf(value) else str(int(value))


def dijkstra_steps(graph: dict[str, dict[str, int]], source: str) -> Iterator[DijkstraStep]:
    """Yield independent snapshots after each meaningful algorithm operation.

    Heap entries use (distance, router_name); neighbors are sorted. Equal-cost
    alternatives retain the first discovered route. ECMP is intentionally omitted.
    The generator is independent of Tkinter and does not modify the input graph.
    """
    if source not in graph:
        raise ValueError(f"Unknown source router: {source}")
    for neighbors in graph.values():
        for neighbor, cost in neighbors.items():
            if neighbor not in graph:
                raise ValueError(f"Unknown neighbor: {neighbor}")
            if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
                raise ValueError("Dijkstra requires finite, nonnegative edge weights.")

    distances = {node: math.inf for node in graph}
    previous: dict[str, str | None] = {node: None for node in graph}
    settled: set[str] = set()
    distances[source] = 0
    queue: list[tuple[float, str]] = [(0, source)]

    def snapshot(phase: str, current: str | None, neighbor: str | None,
                 message: str, line: int) -> DijkstraStep:
        # Copies are essential: later relaxations must not alter earlier frames.
        return DijkstraStep(source, phase, current, neighbor, distances.copy(),
                            previous.copy(), frozenset(settled), message, line)

    yield snapshot("initialize", None, None,
                   f"Root {source}: distance = 0. All other distances = infinity.", 0)
    while queue:
        distance, current = heapq.heappop(queue)
        if current in settled or distance != distances[current]:
            continue  # Ignore obsolete heap entries after a better route was found.
        settled.add(current)
        yield snapshot("settle", current, None,
                       f"Select {current}: smallest tentative cost {metric(distance)}. "
                       f"Its distance is now FINAL; stage its routing entry.", 2)
        for neighbor, cost in sorted(graph[current].items()):
            if neighbor in settled:
                yield snapshot("skip", current, neighbor,
                               f"Skip {current} -> {neighbor}: {neighbor} is already final.", 3)
                continue
            candidate = distance + cost
            old_distance = distances[neighbor]
            if candidate < old_distance:
                distances[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(queue, (candidate, neighbor))
                yield snapshot("relax", current, neighbor,
                               f"Improve {neighbor}: {metric(distance)} + {cost} = "
                               f"{metric(candidate)} < {metric(old_distance)}. "
                               f"Predecessor = {current}; update the tentative route.", 5)
            else:
                yield snapshot("keep", current, neighbor,
                               f"Keep {neighbor}: candidate {metric(distance)} + {cost} = "
                               f"{metric(candidate)} is not below {metric(old_distance)}.", 4)
    missing = sorted(set(graph) - settled)
    note = f" Unreachable: {', '.join(missing)}." if missing else " All routers are reachable."
    yield snapshot("finish", None, None,
                   f"SPF complete for {source}. Install the finalized routing table atomically." + note, 6)


@dataclass(frozen=True)
class Route:
    destination: str
    prefix: ipaddress.IPv4Network
    next_hop: str | None
    cost: int

    @property
    def interface(self) -> str:
        return "loopback" if self.next_hop is None else f"to-{self.next_hop}"


def routes_from_step(network: Network, step: DijkstraStep) -> dict[str, Route]:
    """Only finalized destinations can become installed routes."""
    return {
        destination: Route(destination, network.routers[destination].prefix,
                           step.next_hop_to(destination), int(step.distances[destination]))
        for destination in sorted(step.settled)
    }


class RoutingEngine:
    """Installed routing tables are distinct from the SPF working state."""

    def __init__(self, network: Network) -> None:
        self.network = network
        self.tables: dict[str, dict[str, Route]] = {
            name: {name: Route(name, router.prefix, None, 0)}
            for name, router in network.routers.items()
        }
        self.versions: dict[str, int | None] = {name: None for name in network.routers}
        self.results: dict[str, DijkstraStep] = {}
        self.spf_runs = 0

    def add_router(self, router: Router, connect_to: str | None = None, cost: int = 1) -> None:
        """Register the new router's local route without recalculating old tables."""
        self.network.add_router(router, connect_to, cost)
        self.tables[router.name] = {router.name: Route(router.name, router.prefix, None, 0)}
        self.versions[router.name] = None

    def install(self, step: DijkstraStep, revision: int) -> None:
        if step.phase != "finish":
            raise ValueError("Do not install an unfinished SPF calculation.")
        if revision != self.network.revision:
            raise ValueError("The topology changed during SPF. Start a new calculation.")
        self.tables[step.source] = routes_from_step(self.network, step)
        self.versions[step.source] = revision
        self.results[step.source] = step
        self.spf_runs += 1

    def calculate(self, source: str) -> DijkstraStep:
        revision = self.network.revision
        final: DijkstraStep | None = None
        for final in dijkstra_steps(self.network.adjacency(), source):
            pass
        assert final is not None
        self.install(final, revision)
        return final

    def calculate_all(self) -> None:
        # Real routers run SPF independently. Sequential execution here is only
        # an educational visualization, not a distributed convergence protocol.
        for source in sorted(self.network.routers):
            self.calculate(source)

    def table_status(self, router: str) -> str:
        version = self.versions[router]
        if version is None:
            return "local only"
        return "current" if version == self.network.revision else "STALE"

    def lookup(self, router: str, destination: ipaddress.IPv4Address) -> Route | None:
        """Longest-prefix match in THIS router's installed table, not in a path."""
        matches = [route for route in self.tables[router].values()
                   if destination in route.prefix]
        return max(matches, key=lambda route: route.prefix.prefixlen, default=None)

    def export_data(self) -> dict:
        return {
            "model": "Dijkstra teaching simulation; loopback destinations; no ECMP",
            "topology_revision": self.network.revision,
            "routers": {name: router.address for name, router in self.network.routers.items()},
            "positions": {name: {"x": router.x, "y": router.y}
                          for name, router in self.network.routers.items()},
            "links": [{"a": link.a, "b": link.b, "cost": link.cost, "enabled": link.enabled}
                      for link in self.network.links.values()],
            "tables": {
                name: {"status": self.table_status(name), "revision": self.versions[name],
                       "routes": [{"prefix": str(route.prefix), "next_hop": route.next_hop,
                                   "cost": route.cost, "interface": route.interface}
                                  for route in self.tables[name].values()]}
                for name in sorted(self.network.routers)
            },
        }


# ---------------------------------------------------------------------------
# 3. Data plane: look up the destination independently at EVERY hop.
# ---------------------------------------------------------------------------

@dataclass
class Packet:
    source: str
    destination: ipaddress.IPv4Address
    ttl: int = 16
    current: str = field(init=False)
    initial_ttl: int = field(init=False)
    path: list[str] = field(init=False)
    total_cost: int = 0
    done: bool = False
    outcome: str = "ready"

    def __post_init__(self) -> None:
        self.destination = ipaddress.IPv4Address(self.destination)
        if isinstance(self.ttl, bool) or not isinstance(self.ttl, int) or not 1 <= self.ttl <= 255:
            raise ValueError("TTL must be an integer from 1 to 255.")
        self.initial_ttl = self.ttl
        self.current = self.source
        self.path = [self.source]


@dataclass(frozen=True)
class ForwardDecision:
    kind: str
    router: str
    prefix: str
    next_hop: str | None
    ttl_before: int
    ttl_after: int
    cost: int
    message: str
    reason_code: str = ""


def forward_one_hop(engine: RoutingEngine, packet: Packet) -> ForwardDecision:
    """Make one forwarding decision WITHOUT running Dijkstra or reading an SPF path.

    The packet is addressed to a router loopback. Local delivery does not decrement
    TTL; each actual router-to-router forwarding operation does. This is why a
    packet with TTL 6 can traverse five links and arrive with TTL 1.
    """
    if packet.done:
        raise ValueError("This packet has already finished. Create a new packet.")
    if packet.current not in engine.network.routers:
        raise ValueError(f"Unknown injection router: {packet.current}")
    router, ttl_before = packet.current, packet.ttl
    route = engine.lookup(router, packet.destination)
    prefix = str(route.prefix) if route else "--"

    def stop(kind: str, message: str, reason_code: str = "") -> ForwardDecision:
        packet.done, packet.outcome = True, kind
        # A failed link still has an installed next hop worth showing in diagnostics.
        next_hop = route.next_hop if route else None
        return ForwardDecision(kind, router, prefix, next_hop, ttl_before,
                               packet.ttl, 0, message, reason_code)

    if route is None:
        status = engine.table_status(router)
        if status == "local only":
            reason = "NO_SPF"
            hint = (f"{router} has not completed SPF; it knows only its own loopback. "
                    "Build all now calculates tables at intermediate routers as well.")
        elif status == "STALE":
            reason = "STALE_NO_ROUTE"
            hint = "This table is from an older topology. Rebuild the routing tables."
        else:
            reason = "NO_ROUTE"
            hint = ("The table is current. Check the destination IP and enabled links; "
                    "rebuilding alone cannot connect an isolated destination.")
        return stop("drop", f"DROP at {router} [{reason}]: no installed route to "
                    f"{packet.destination}. TTL remains {packet.ttl} (not a TTL expiry). " + hint, reason)
    if route.next_hop is None:
        return stop("deliver", f"DELIVER at {router}: {packet.destination} is this router's "
                    f"local loopback. TTL remains {packet.ttl}.")
    if packet.ttl <= 1:
        packet.ttl = 0
        return stop("drop", f"DROP at {router} [TTL_EXPIRED]: TTL expired before forwarding "
                    f"to {route.next_hop} ({ttl_before} -> 0). Increase Initial TTL, then "
                    "create a NEW packet; changing the input does not change an existing packet.",
                    "TTL_EXPIRED")
    link = engine.network.links.get(tuple(sorted((router, route.next_hop))))
    if link is None or not link.enabled:
        reason = "INVALID_NEXT_HOP" if link is None else "LINK_DOWN"
        return stop("drop", f"DROP at {router} [{reason}]: installed next hop {route.next_hop} "
                    f"uses an unavailable link. TTL remains {packet.ttl} (not a TTL expiry). "
                    "Restore the link or rebuild the tables to use an available alternative.", reason)
    packet.ttl -= 1
    packet.current = route.next_hop
    packet.path.append(route.next_hop)
    packet.total_cost += link.cost
    packet.outcome = "forwarding"
    return ForwardDecision(
        "forward", router, prefix, route.next_hop, ttl_before, packet.ttl, link.cost,
        f"{router}: match {prefix}; next hop {route.next_hop}; interface {route.interface}; "
        f"TTL {ttl_before} -> {packet.ttl}. Link cost +{link.cost}.",
    )


def trace_packet(engine: RoutingEngine, source: str, destination: str,
                 ttl: int = 16) -> tuple[Packet, list[ForwardDecision]]:
    """Headless packet tracing; the GUI uses exactly the same one-hop function."""
    packet = Packet(source, ipaddress.IPv4Address(destination), ttl)
    trace: list[ForwardDecision] = []
    while not packet.done:
        trace.append(forward_one_hop(engine, packet))
    return packet, trace


# Tkinter is optional for the MODEL. Tests and --print-tables do not need a display.
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:
    tk = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 4. GUI: responsive Canvas drawing and non-blocking after() animation.
# ---------------------------------------------------------------------------

class RoutingDemo:
    BG = "#f2f7f7"
    INK = "#123740"
    MUTED = "#536b73"
    BLUE = "#006877"
    BRAND = "#004250"
    BORDER = "#cedee1"
    GREEN = "#087e66"
    AMBER = "#b45309"
    PURPLE = "#a21caf"
    RED = "#b91c1c"

    def __init__(self, root) -> None:
        self.root = root
        self.root.title("Dijkstra Routing Lab | Control plane -> Data plane")
        self.root.geometry(f"{min(1440, self.root.winfo_screenwidth() - 40)}x"
                           f"{min(960, max(740, self.root.winfo_screenheight() - 80))}")
        self.root.minsize(1180, 740)
        self.root.configure(background=self.BG)
        self.network = make_default_network()
        self.engine = RoutingEngine(self.network)
        self.graph_file: Path | None = None
        self.saved_graph = graph_to_data(self.network)
        self.step: DijkstraStep | None = None
        self.iterator: Iterator[DijkstraStep] | None = None
        self.run_revision = self.network.revision
        self.spf_auto = False
        self.spf_queue: deque[str] = deque()
        self.spf_job = None
        self.packet_job = None
        self.frame_job = None
        self.packet: Packet | None = None
        self.packet_auto = False
        self.packet_animating = False
        self.packet_position: tuple[str, str, float] | None = None
        self.lookup_router: str | None = None
        self.highlight_prefix: str | None = None
        self.last_decision: ForwardDecision | None = None
        self.packet_sequence = 0
        self.trace_count = 0
        self.trace_decisions: dict[str, ForwardDecision] = {}
        self.step_count = 0
        self.event_count = 0
        self.router_selectors: list = []
        self.drag_router: str | None = None
        self.drag_offset = (0.0, 0.0)
        self.editor_window = None
        self.about_window = None
        # Keep PhotoImage objects alive for the lifetime of their widgets.
        self.brand_images: dict = {}
        self.asset_warnings: list[str] = []
        self._load_brand_assets()

        self.spf_root = tk.StringVar(value="A")
        self.inspector = tk.StringVar(value="A")
        self.packet_source = tk.StringVar(value="A")
        self.packet_target = tk.StringVar(value="F")
        self.destination_ip = tk.StringVar(value="10.0.0.6")
        self.ttl_value = tk.StringVar(value="16")
        self.speed = tk.DoubleVar(value=0.65)
        self.link_name = tk.StringVar(value="D-E")
        self.link_cost = tk.StringVar(value="1")
        self.link_up = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar()
        self.spf_note = tk.StringVar(value="Press New SPF or Step SPF to begin at router A.")
        self.packet_state = tk.StringVar(value="No packet | Initial TTL applies to the next new packet.")
        self.packet_note = tk.StringVar(value="Build the routing tables, then create a packet.")
        self.table_note = tk.StringVar()
        self.work_title = tk.StringVar(value="DIJKSTRA WORKING STATE | no calculation yet")
        self.table_title = tk.StringVar()
        self._build_ui()
        self._refresh_selectors()
        self._refresh_all()
        self._log("Ready. Each router initially knows only its own /32 loopback.")
        for warning in self.asset_warnings:
            self._log(warning)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, foreground=self.INK, font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(9, 5))
        style.configure("TCheckbutton", background=self.BG, font=("Segoe UI", 10))
        style.configure("TLabelframe", background=self.BG)
        style.configure("TLabelframe.Label", background=self.BG, foreground=self.INK,
                        font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=25,
                        background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=(4, 5))
        style.map("Treeview", background=[("selected", "#dbeafe")],
                  foreground=[("selected", self.INK)])
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground=self.MUTED)
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", foreground="white", background=self.BLUE)
        style.map("Accent.TButton", background=[("disabled", "#e3e9ea"),
                                                ("active", self.BRAND), ("pressed", self.BRAND)],
                  foreground=[("disabled", "#8a999d"), ("!disabled", "white")])
        style.configure("TButton", background="white", foreground=self.INK,
                        bordercolor=self.BORDER, lightcolor="white", darkcolor=self.BORDER)
        style.map("TButton", background=[("active", "#e2eeee"), ("pressed", "#d0e4e6")])
        style.configure("Brand.TFrame", background="white")
        style.configure("BrandTitle.TLabel", background="white", foreground=self.BRAND,
                        font=("Segoe UI", 22, "bold"))
        style.configure("BrandText.TLabel", background="white", foreground=self.MUTED,
                        font=("Segoe UI", 10))
        style.configure("BrandSmall.TLabel", background="white", foreground=self.MUTED,
                        font=("Segoe UI", 9))
        style.configure("BrandLogo.TLabel", background="white", foreground=self.BRAND,
                        font=("Segoe UI", 19, "bold"))
        style.configure("Treeview.Heading", background="#e4eff0", foreground=self.BRAND)
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(10, 6), background="#e1ebed", foreground=self.INK)
        style.map("TNotebook.Tab", background=[("selected", self.BRAND)],
                  foreground=[("selected", "white")])

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(3, weight=1)
        outer.columnconfigure(0, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self.brand_header = ttk.Frame(header, style="Brand.TFrame", padding=(16, 10))
        self.brand_header.grid(row=0, column=0, sticky="ew")
        self.brand_header.columnconfigure(1, weight=1)
        self.ihn_header = self._brand_logo(self.brand_header, "ihn", "IHN")
        self.ihn_header.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        ttk.Label(self.brand_header, text=APP_NAME, style="BrandTitle.TLabel").grid(
            row=0, column=1, sticky="w")
        ttk.Label(self.brand_header, text="Calculate shortest paths. Build tables. Follow every hop.",
                  style="BrandSmall.TLabel").grid(row=1, column=1, sticky="w", pady=(1, 0))
        self.ucn_header = self._brand_logo(self.brand_header, "ucn", "UCN")
        self.ucn_header.grid(row=0, column=2, rowspan=2, padx=(24, 18))
        self.about_button = ttk.Button(self.brand_header, text="About", command=self.show_about)
        self.about_button.grid(row=0, column=3, rowspan=2, padx=(0, 2))
        tk.Frame(header, background=self.BRAND, height=3).grid(row=1, column=0, sticky="ew")
        toolbar = ttk.Frame(header, padding=(0, 7, 0, 0))
        toolbar.grid(row=2, column=0, sticky="ew")
        ttk.Label(toolbar, text="TOPOLOGY", style="Section.TLabel").pack(side="left", padx=(0, 10))
        self.topology_buttons: dict = {}
        for label, command in (("New topology", self.new_topology),
                               ("Add router", self.add_router_dialog), ("Add link", self.add_link_dialog),
                               ("Save graph", self.save_graph), ("Load graph", self.load_graph),
                               ("Export tables", self.export_tables), ("Reset network", self.reset_network)):
            button = ttk.Button(toolbar, text=label, command=command)
            button.pack(side="left", padx=(0, 6))
            self.topology_buttons[label] = button
        menu = tk.Menu(self.root)
        files = tk.Menu(menu, tearoff=False)
        self.file_menu = files
        files.add_command(label="New topology", accelerator="Ctrl+N", command=self.new_topology)
        files.add_separator()
        files.add_command(label="Save graph", accelerator="Ctrl+S", command=self.save_graph)
        files.add_command(label="Save graph as...", accelerator="Ctrl+Shift+S",
                          command=lambda: self.save_graph(save_as=True))
        files.add_command(label="Load graph...", accelerator="Ctrl+O", command=self.load_graph)
        files.add_separator()
        files.add_command(label="Export tables...", command=self.export_tables)
        files.add_command(label="Reset network", command=self.reset_network)
        files.add_separator()
        files.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=files)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About Dijkstra Routing Lab...", accelerator="F1", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.menu = menu
        self.help_menu = help_menu
        self.root.configure(menu=menu)
        self.root.bind("<F1>", lambda event: (self.show_about(), "break")[1])
        for binding, command in (("<Control-n>", self.new_topology),
                                 ("<Control-s>", self.save_graph),
                                 ("<Control-Shift-S>", lambda: self.save_graph(save_as=True)),
                                 ("<Control-o>", self.load_graph)):
            self.root.bind(binding, lambda event, action=command: (action(), "break")[1])

        controls = ttk.LabelFrame(outer, text="CONTROL PLANE  |  Dijkstra / shortest-path first", padding=(9, 6))
        self.spf_controls = controls
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(controls, text="Root").pack(side="left")
        self._combo(controls, self.spf_root, list(self.network.routers), 8).pack(side="left", padx=(4, 8))
        for label, callback in [("New SPF", self.new_spf), ("Step SPF", self.step_spf)]:
            ttk.Button(controls, text=label, command=callback).pack(side="left", padx=2)
        self.spf_play_button = ttk.Button(controls, text="Play SPF", command=self.toggle_spf)
        self.spf_play_button.pack(side="left", padx=2)
        ttk.Button(controls, text="Finish router", command=self.finish_router).pack(side="left", padx=2)
        ttk.Button(controls, text="Animate all", command=self.animate_all).pack(side="left", padx=(10, 2))
        ttk.Button(controls, text="Build all now", command=self.build_all,
                   style="Accent.TButton").pack(side="left", padx=2)
        ttk.Label(controls, text="Delay").pack(side="left", padx=(14, 4))
        ttk.Scale(controls, variable=self.speed, from_=0.12, to=1.8, length=100).pack(side="left")
        ttk.Label(controls, text="fast  /  slow", style="Small.TLabel").pack(side="left", padx=4)

        links = ttk.Frame(outer)
        self.link_controls = links
        links.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(links, text="LINK EDITOR", style="Section.TLabel").pack(side="left", padx=(0, 8))
        selector = self._combo(links, self.link_name,
                               ["-".join(key) for key in sorted(self.network.links)], 15)
        self.link_selector = selector
        selector.pack(side="left")
        selector.bind("<<ComboboxSelected>>", lambda event: self.select_link())
        ttk.Label(links, text="Cost").pack(side="left", padx=(10, 4))
        ttk.Spinbox(links, textvariable=self.link_cost, from_=1, to=9999, width=6).pack(side="left")
        ttk.Checkbutton(links, text="Link up", variable=self.link_up).pack(side="left", padx=8)
        self.apply_link_button = ttk.Button(links, text="Apply change", command=self.apply_link)
        self.apply_link_button.pack(side="left")
        ttk.Label(links, text="Changes leave installed tables stale until SPF runs again.",
                  style="Small.TLabel").pack(side="left", padx=12)

        body = ttk.Panedwindow(outer, orient="horizontal")
        self.body = body
        self.compact = False
        body.grid(row=3, column=0, sticky="nsew")
        left, right = ttk.Frame(body), ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)
        body.bind("<Configure>", self._responsive_layout)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(left, background="white", highlightthickness=1,
                                highlightbackground=self.BORDER, width=710, height=370)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.canvas.bind("<Configure>", lambda event: self.draw_network())
        self.canvas.bind("<Double-Button-1>", self._add_router_at_click)
        self.canvas.bind("<B1-Motion>", self._drag_router)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)
        ttk.Label(left, text="Final / SPF tree: green   |   Comparing: amber   |   Packet: purple   |   Down: dashed",
                  style="Small.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.graph_hint = ttk.Label(left, text="Double-click empty space to add a router; drag to move. Click a cost to edit; right-click a link to toggle.",
                                    style="Small.TLabel")
        self.graph_hint.grid(row=2, column=0, sticky="w", pady=(0, 5))

        packet_box = ttk.LabelFrame(left, text="DATA PLANE  |  hop-by-hop forwarding", padding=6)
        self.packet_controls = packet_box
        packet_box.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(0, 5))
        row = ttk.Frame(packet_box)
        row.pack(fill="x")
        ttk.Label(row, text="Source").pack(side="left")
        self._combo(row, self.packet_source, list(self.network.routers), 7).pack(side="left", padx=(4, 10))
        ttk.Label(row, text="Target").pack(side="left")
        target = self._combo(row, self.packet_target, list(self.network.routers), 7)
        target.pack(side="left", padx=(4, 10))
        target.bind("<<ComboboxSelected>>", self.select_target)
        ttk.Label(row, text="Dest. IP").pack(side="left")
        ttk.Entry(row, textvariable=self.destination_ip, width=14).pack(side="left", padx=(4, 10))
        ttk.Label(row, text="Initial TTL").pack(side="left", padx=(10, 0))
        self.initial_ttl_spinbox = ttk.Spinbox(row, textvariable=self.ttl_value, from_=1, to=255, width=4)
        self.initial_ttl_spinbox.pack(side="left", padx=4)
        row = ttk.Frame(packet_box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="New packet", command=self.new_packet).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Next hop", command=self.step_packet).pack(side="left", padx=4)
        self.packet_play_button = ttk.Button(row, text="Play packet", command=self.toggle_packet,
                                             style="Accent.TButton")
        self.packet_play_button.pack(side="left", padx=4)
        ttk.Button(row, text="Stop packet", command=self.stop_packet).pack(side="left", padx=4)
        self.packet_state_label = ttk.Label(packet_box, textvariable=self.packet_state,
                                             style="Small.TLabel", wraplength=620)
        self.packet_state_label.pack(fill="x", pady=(2, 0))
        self.packet_label = ttk.Label(packet_box, textvariable=self.packet_note,
                                      wraplength=650, justify="left", style="Small.TLabel")
        self.packet_label.pack(fill="x", pady=(6, 0))
        self.trace_tree = self._tree(left,
            [("n", "#", 30), ("at", "At", 35), ("prefix", "Matched prefix", 135),
             ("action", "Decision / reason", 220), ("ttl", "TTL", 70)], height=6)
        self.trace_tree.grid(row=4, column=0, sticky="ew", padx=(0, 8))
        self.trace_tree.tag_configure("drop", foreground=self.RED)
        self.trace_tree.tag_configure("deliver", foreground=self.GREEN)
        self.trace_tree.bind("<<TreeviewSelect>>", self._show_trace_decision)
        self.trace_tree.bind("<Configure>", self._keep_trace_selection_visible)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        live, all_tables, algorithm, events, help_tab = [ttk.Frame(self.tabs, padding=9) for _ in range(5)]
        for panel, name in [(live, "Live view"), (all_tables, "All tables"), (algorithm, "Algorithm"),
                            (events, "Event log"), (help_tab, "Guide")]:
            self.tabs.add(panel, text=name)
        self.live_tab = live
        # The live panel scrolls on shorter laptop displays; no routing rows are
        # silently clipped when there is insufficient vertical space.
        live_canvas = tk.Canvas(live, background=self.BG, highlightthickness=0, width=500)
        live_bar = ttk.Scrollbar(live, orient="vertical", command=live_canvas.yview)
        live_bar.pack(side="right", fill="y")
        live_canvas.pack(side="left", fill="both", expand=True)
        live_canvas.configure(yscrollcommand=live_bar.set)
        live = ttk.Frame(live_canvas)
        live_window = live_canvas.create_window((0, 0), window=live, anchor="nw")
        live.bind("<Configure>", lambda event: live_canvas.configure(scrollregion=live_canvas.bbox("all")))
        live_canvas.bind("<Configure>", lambda event: live_canvas.itemconfigure(live_window, width=event.width))
        for panel in (live, all_tables, algorithm, events, help_tab):
            panel.columnconfigure(0, weight=1)
        row = ttk.Frame(live)
        row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(row, text="Inspect router").pack(side="left")
        inspect = self._combo(row, self.inspector, list(self.network.routers), 8)
        inspect.pack(side="left", padx=6)
        inspect.bind("<<ComboboxSelected>>", lambda event: self.inspect_router(self.inspector.get()))
        ttk.Label(row, text="Double outline on the map", style="Small.TLabel").pack(side="left", padx=4)
        ttk.Label(live, textvariable=self.work_title, style="Section.TLabel").grid(row=1, column=0, sticky="w")
        self.work_tree = self._tree(live,
            [("router", "Node", 46), ("cost", "Cost", 55), ("parent", "Previous", 70),
             ("next", "Next hop", 75), ("state", "State", 105)], height=6)
        self.work_tree.grid(row=2, column=0, sticky="ew", pady=5)
        work_bar = ttk.Scrollbar(live, orient="vertical", command=self.work_tree.yview)
        work_bar.grid(row=2, column=1, sticky="ns", pady=5)
        self.work_tree.configure(yscrollcommand=work_bar.set)
        for tag, color in [("final", "#d1fae5"), ("tentative", "#fff3d1"), ("active", "#fed7aa")]:
            self.work_tree.tag_configure(tag, background=color)
        self.spf_label = ttk.Label(live, textvariable=self.spf_note, wraplength=510,
                                   justify="left", style="Small.TLabel")
        self.spf_label.grid(row=3, column=0, sticky="ew", pady=(2, 14))
        ttk.Label(live, textvariable=self.table_title, style="Section.TLabel").grid(row=4, column=0, sticky="w")
        self.route_tree = self._tree(live,
            [("prefix", "Destination", 135), ("next", "Next hop", 75), ("cost", "Cost", 45),
             ("interface", "Interface", 75), ("state", "State", 100)], height=6)
        self.route_tree.grid(row=5, column=0, sticky="ew", pady=5)
        route_bar = ttk.Scrollbar(live, orient="vertical", command=self.route_tree.yview)
        route_bar.grid(row=5, column=1, sticky="ns", pady=5)
        self.route_tree.configure(yscrollcommand=route_bar.set)
        self.route_tree.tag_configure("staged", background="#fff3d1")
        self.route_tree.tag_configure("stale", foreground=self.RED)
        self.table_label = ttk.Label(live, textvariable=self.table_note, wraplength=510,
                                     justify="left", style="Small.TLabel")
        self.table_label.grid(row=6, column=0, sticky="ew", pady=(2, 8))
        ttk.Label(live, text="Previous = last router before the destination in the SPF tree.\n"
                  "Next hop = FIRST router after the root, used for forwarding.",
                  style="Small.TLabel").grid(row=7, column=0, sticky="w")
        live.bind("<Configure>", lambda event: self._wrap_live(event.width), add="+")
        left.bind("<Configure>", self._wrap_packet_labels)

        all_tables.rowconfigure(1, weight=1)
        ttk.Label(all_tables, text="INSTALLED TABLES | one independent SPF per router",
                  style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.all_tree = self._tree(all_tables,
            [("at", "Router", 52), ("prefix", "Destination", 126), ("next", "Next", 52),
             ("cost", "Cost", 45), ("state", "Status", 85)], height=18)
        self.all_tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(all_tables, orient="vertical", command=self.all_tree.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.all_tree.configure(yscrollcommand=bar.set)
        self.all_tree.tag_configure("alternate", background="#edf3fa")
        self.all_tree.tag_configure("stale", foreground=self.RED)

        self.code_text = ScrolledText(algorithm, font=("Consolas", 11), wrap="word", relief="flat",
                                      background="white", foreground=self.INK, padx=12, pady=12)
        self.code_text.pack(fill="both", expand=True)
        self.code_text.insert("1.0",
            "CONTROL PLANE: DIJKSTRA\n\n"
            "1  dist[root] = 0; others = infinity\n"
            "2  choose smallest tentative distance\n"
            "3  settle node; stage its route\n"
            "4  inspect each non-final neighbor\n"
            "5  candidate = dist[node] + link_cost\n"
            "6  if smaller: update distance + previous\n"
            "7  finish: install finalized table\n\n"
            "From a predecessor chain to a next hop:\n"
            "A -> C -> B -> D -> E -> F\n"
            "At root A, the next hop for F is C, NOT E.\n\n"
            "DATA PLANE: PACKET FORWARDING\n\n"
            "1  read the destination IP\n"
            "2  longest-prefix match in LOCAL table\n"
            "3  local loopback? deliver\n"
            "4  no route / TTL expired / link down? drop\n"
            "5  decrement TTL; forward to next hop\n"
            "6  repeat lookup at the receiving router\n\n"
            "No Dijkstra calculation is triggered by a packet.\n"
            "The complete SPF path is never used by the\n"
            "packet forwarding function.\n")
        self.code_text.tag_configure("active", background="#fef3c7")
        self.code_text.configure(state="disabled")
        self.log_text = ScrolledText(events, font=("Consolas", 10), wrap="word", relief="flat",
                                     background="white", padx=10, pady=10)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        help_text = ScrolledText(help_tab, font=("Segoe UI", 11), wrap="word", relief="flat",
                                  background="white", padx=12, pady=12)
        help_text.pack(fill="both", expand=True)
        help_text.insert("1.0", GUI_GUIDE)
        help_text.configure(state="disabled")
        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_text, style="Small.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(footer, text=f"{__copyright__}  |  v{__version__}",
                  style="Small.TLabel").grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _load_brand_assets(self) -> None:
        """Local, optional PNG assets; never download files while the application runs."""
        for key, filename in (("ihn", "ihn-logo.png"), ("ucn", "ucn-logo.png"),
                              ("icon16", "ihn-icon-16.png")):
            try:
                self.brand_images[key] = tk.PhotoImage(master=self.root, file=str(ASSET_DIR / filename))
            except (tk.TclError, OSError) as error:
                self.asset_warnings.append(f"Optional branding asset unavailable: {filename} ({error}).")
        images = [self.brand_images[key] for key in ("ihn", "icon16") if key in self.brand_images]
        if images:
            try:
                self.root.iconphoto(True, *images)
            except tk.TclError as error:
                self.asset_warnings.append(f"Window icon not supported by this Tk/window manager: {error}.")
        # On Windows, use the bundled multi-size ICO for main and future dialogs.
        # PNG iconphoto above is also a fallback if this optional ICO is missing.
        if sys.platform == "win32":
            try:
                self.root.iconbitmap(default=str(ASSET_DIR / "ihn.ico"))
            except (tk.TclError, OSError) as error:
                self.asset_warnings.append(f"Windows ICO unavailable; using PNG icon when supported ({error}).")

    def _brand_logo(self, parent, key: str, fallback: str):
        image = self.brand_images.get(key)
        if image is None:
            return ttk.Label(parent, text=fallback, style="BrandLogo.TLabel")
        return ttk.Label(parent, image=image, style="BrandLogo.TLabel")

    def show_about(self):
        """Show one modal About window. Keep topology, routes and simulation work intact."""
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            self.about_window.focus_set()
            return self.about_window
        if not self._pause_for_file_dialog():
            return None
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        self.about_window = dialog
        dialog.title(f"About {APP_NAME}")
        dialog.transient(self.root)
        dialog.configure(background="white")
        dialog.minsize(570, 440)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        banner = ttk.Frame(dialog, style="Brand.TFrame", padding=(22, 16))
        banner.grid(row=0, column=0, sticky="ew")
        banner.columnconfigure(1, weight=1)
        self._brand_logo(banner, "ihn", "IHN").grid(row=0, column=0, rowspan=2, padx=(0, 14))
        ttk.Label(banner, text=APP_NAME, style="BrandTitle.TLabel",
                  font=("Segoe UI", 19, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(banner, text=f"Version {__version__}  |  Interactive network laboratory",
                  style="BrandSmall.TLabel").grid(row=1, column=1, sticky="w")
        self._brand_logo(banner, "ucn", "UCN").grid(row=0, column=2, rowspan=2, padx=(22, 0))
        panel = ttk.Frame(dialog, style="Brand.TFrame", padding=(22, 0, 22, 10))
        panel.grid(row=1, column=0, sticky="nsew")
        text = ScrolledText(panel, wrap="word", font=("Segoe UI", 11), height=14,
                            background="white", foreground=self.INK, relief="flat",
                            borderwidth=0, highlightthickness=0, padx=0, pady=6,
                            spacing1=0, spacing3=4, selectbackground="#cee6ea")
        text.pack(fill="both", expand=True)
        text.tag_configure("heading", foreground=self.BRAND, font=("Segoe UI", 10, "bold"), spacing1=12)
        for heading, body in ABOUT_SECTIONS:
            text.insert("end", heading + "\n", "heading")
            text.insert("end", body + "\n")
        text.configure(state="disabled")
        self.about_text = text

        details = ttk.Frame(dialog, style="Brand.TFrame", padding=(22, 8, 22, 0))
        details.grid(row=2, column=0, sticky="ew")
        details.columnconfigure(0, weight=1)
        ttk.Label(details, text=__copyright__, style="BrandText.TLabel",
                  font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(details, text="Code and documentation: Apache License 2.0. See LICENSE and NOTICE.",
                  style="BrandSmall.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 3))
        ttk.Label(details, text="UCN's logo remains UCN's mark; its display does not imply endorsement.",
                  style="BrandSmall.TLabel", wraplength=620).grid(row=2, column=0, sticky="w")
        self.about_repo_value = tk.StringVar(master=dialog, value=REPOSITORY_URL)
        entry = ttk.Entry(details, textvariable=self.about_repo_value, state="readonly",
                          font=("Segoe UI", 10))
        entry.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.about_repo_entry = entry
        buttons = ttk.Frame(dialog, style="Brand.TFrame", padding=(22, 10, 22, 14))
        buttons.grid(row=3, column=0, sticky="ew")
        self.about_open_button = ttk.Button(buttons, text="Open GitHub", command=self.open_repository,
                                            style="Accent.TButton")
        self.about_open_button.pack(side="left")
        self.about_copy_button = ttk.Button(buttons, text="Copy link", command=self.copy_repository)
        self.about_copy_button.pack(side="left", padx=8)
        self.about_feedback = tk.StringVar(master=dialog)
        ttk.Label(buttons, textvariable=self.about_feedback, style="BrandSmall.TLabel").pack(side="left")
        self.about_close_button = ttk.Button(buttons, text="Close", command=self.close_about)
        self.about_close_button.pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", self.close_about)
        dialog.bind("<Escape>", lambda event: self.close_about())
        dialog.bind("<F1>", lambda event: "break")
        dialog.update_idletasks()
        width = min(760, max(570, self.root.winfo_screenwidth() - 60))
        height = min(700, max(440, self.root.winfo_screenheight() - 110))
        x = max(0, min(self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2,
                       self.root.winfo_screenwidth() - width))
        y = max(0, min(self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2,
                       self.root.winfo_screenheight() - height - 40))
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()
        dialog.grab_set()
        self.about_close_button.focus_set()
        return dialog

    def close_about(self) -> None:
        dialog = self.about_window
        self.about_window = None
        if dialog is not None and dialog.winfo_exists():
            if dialog.grab_current() == dialog:
                dialog.grab_release()
            dialog.destroy()
        self.root.focus_set()

    def open_repository(self) -> bool:
        """Open only the fixed project URL, and only following an explicit click."""
        try:
            opened = webbrowser.open(REPOSITORY_URL, new=2)
        except (webbrowser.Error, OSError):
            opened = False
        if not opened:
            messagebox.showwarning("Cannot open browser", "Open this address in your browser:\n" + REPOSITORY_URL,
                                   parent=self.about_window or self.root)
        return bool(opened)

    def copy_repository(self) -> bool:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(REPOSITORY_URL)
        except tk.TclError:
            messagebox.showwarning("Cannot copy link", "Select and copy the address shown in the About window.",
                                   parent=self.about_window or self.root)
            return False
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_feedback.set("Link copied")
        return True

    def _combo(self, parent, variable, values, width):
        selector = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        if any(variable is v for v in (self.spf_root, self.inspector, self.packet_source, self.packet_target)):
            self.router_selectors.append(selector)
        return selector

    @staticmethod
    def _tree(parent, columns, height=6):
        tree = ttk.Treeview(parent, columns=[col[0] for col in columns], show="headings",
                            height=height, selectmode="browse")
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=max(30, width - 30), anchor="w", stretch=True)
        return tree

    def _responsive_layout(self, event) -> None:
        if not hasattr(self, "trace_tree"):
            return
        compact = self.root.winfo_height() < 900
        self.compact = compact
        short = self.root.winfo_height() < 820
        self.trace_tree.configure(height=1 if short else 3 if compact else 4)
        # Preserve graph space on short screens; the same editing tips remain in Guide.
        if short:
            self.graph_hint.grid_remove()
        else:
            self.graph_hint.grid()
        self._show_trace_decision()
        # Keep the editable packet controls usable on 1280/1366-pixel laptops.
        # Users may still drag the sash; the ratio resets only on window resize.
        if getattr(self, "_last_body_width", None) != event.width:
            self._last_body_width = event.width
            self.body.sashpos(0, int(event.width * 0.55))
        self.draw_network()

    def _wrap_live(self, width: int) -> None:
        for label in (self.spf_label, self.table_label):
            label.configure(wraplength=max(350, width - 25))

    def _wrap_packet_labels(self, event) -> None:
        width = max(350, event.width - 40)
        self.packet_label.configure(wraplength=width)
        self.packet_state_label.configure(wraplength=width)

    def _log(self, message: str) -> None:
        self.event_count += 1
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{self.event_count:04d}  {message}\n")
        # Bound memory use in long classroom sessions.
        if int(self.log_text.index("end-1c").split(".")[0]) > 2500:
            self.log_text.delete("1.0", "501.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _cancel_job(self, name: str) -> None:
        job = getattr(self, name)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        setattr(self, name, None)

    def _pause_spf(self, clear_queue: bool = False) -> None:
        self.spf_auto = False
        if clear_queue:
            self.spf_queue.clear()
        self._cancel_job("spf_job")
        self.spf_play_button.configure(text="Play SPF")

    def _cancel_packet(self, clear: bool = False) -> None:
        self.packet_auto = False
        self.packet_animating = False
        self._cancel_job("packet_job")
        self._cancel_job("frame_job")
        self.packet_play_button.configure(text="Play packet")
        self.packet_position = None
        if clear:
            had_packet = self.packet is not None
            self.packet = None
            self.lookup_router = None
            self.highlight_prefix = None
            self.last_decision = None
            if had_packet:
                self._clear_packet_display()

    def _stop_everything(self) -> None:
        self._pause_spf(clear_queue=True)
        self._cancel_packet(clear=True)
        self.iterator = None

    def _begin_spf(self, source: str) -> None:
        self.spf_root.set(source)
        self.inspector.set(source)
        self.run_revision = self.network.revision
        self.iterator = dijkstra_steps(self.network.adjacency(), source)
        self.step_count = 0
        self._log(f"CONTROL PLANE: begin SPF at {source}, topology revision {self.run_revision}.")
        self._advance_spf()

    def _advance_spf(self) -> None:
        if self.iterator is None:
            return
        try:
            step = next(self.iterator)
        except StopIteration:
            self.iterator = None
            return
        self.step = step
        self.step_count += 1
        if step.phase == "finish":
            self.engine.install(step, self.run_revision)
            self.iterator = None
        self.spf_note.set(f"Step {self.step_count} | {step.message}")
        self._log(f"SPF {step.source}: {step.message}")
        self._refresh_all()

    def new_spf(self) -> None:
        if not self._require_router():
            return
        self._stop_everything()
        self._clear_packet_display()
        self._begin_spf(self.spf_root.get())
        self.tabs.select(self.live_tab)

    def step_spf(self) -> None:
        if not self._require_router():
            return
        self._pause_spf()
        self._cancel_packet(clear=True)
        if self.iterator is None or (self.step and self.step.source != self.spf_root.get()):
            self._begin_spf(self.spf_root.get())
        else:
            self._advance_spf()
        self.tabs.select(self.live_tab)

    def toggle_spf(self) -> None:
        if not self._require_router():
            return
        if self.spf_auto:
            self._pause_spf()
            self._refresh_status()
            return
        self._cancel_packet(clear=True)
        if self.iterator is None and self.spf_queue:
            self._begin_spf(self.spf_queue.popleft())
        elif self.iterator is None or (self.step and self.step.source != self.spf_root.get()):
            self._begin_spf(self.spf_root.get())
        self.spf_auto = True
        self.spf_play_button.configure(text="Pause SPF")
        self.spf_job = self.root.after(self._delay(), self._spf_tick)
        self._refresh_status()

    def _spf_tick(self) -> None:
        self.spf_job = None
        if not self.spf_auto:
            return
        if self.iterator is None:
            if self.spf_queue:
                self._begin_spf(self.spf_queue.popleft())
            else:
                self._pause_spf()
                self._refresh_status()
                return
        else:
            self._advance_spf()
        self.spf_job = self.root.after(self._delay(), self._spf_tick)

    def finish_router(self) -> None:
        if not self._require_router():
            return
        self._pause_spf(clear_queue=True)
        self._cancel_packet(clear=True)
        if self.iterator is None or (self.step and self.step.source != self.spf_root.get()):
            self._begin_spf(self.spf_root.get())
        while self.iterator is not None:
            self._advance_spf()
        self._refresh_status()

    def animate_all(self) -> None:
        if not self._require_router():
            return
        self._stop_everything()
        self._clear_packet_display()
        self.spf_queue = deque(sorted(self.network.routers))
        self._begin_spf(self.spf_queue.popleft())
        self.spf_auto = True
        self.spf_play_button.configure(text="Pause SPF")
        self.spf_job = self.root.after(self._delay(), self._spf_tick)
        self.tabs.select(self.live_tab)

    def build_all(self) -> None:
        if not self._require_router():
            return
        self._stop_everything()
        self._clear_packet_display()
        self.engine.calculate_all()
        source = self.spf_root.get()
        self.step = self.engine.results[source]
        self.inspector.set(source)
        count = len(self.network.routers)
        self.spf_note.set(f"All {count} routers ran their own SPF. All routing tables are now installed.")
        self._log(f"CONTROL PLANE: built and installed all {count} routing tables.")
        self._refresh_all()

    @staticmethod
    def _enable_controls(parent, enabled: bool) -> None:
        """Enable interactive children without changing labels or table contents."""
        for child in parent.winfo_children():
            if isinstance(child, ttk.Combobox):
                child.configure(state="readonly" if enabled else "disabled")
            elif isinstance(child, (ttk.Button, ttk.Entry, ttk.Checkbutton, ttk.Scale)):
                child.state(["!disabled"] if enabled else ["disabled"])
            RoutingDemo._enable_controls(child, enabled)

    def _require_router(self) -> bool:
        if self.network.routers:
            return True
        self.spf_note.set("Empty topology. Use Add router, or double-click the graph, to begin.")
        self.packet_note.set("Add routers and links, then build the routing tables before sending a packet.")
        return False

    def _refresh_selectors(self) -> None:
        names = sorted(self.network.routers)
        self._enable_controls(self.spf_controls, bool(names))
        self._enable_controls(self.packet_controls, bool(names))
        self._enable_controls(self.link_controls, bool(self.network.links))
        self.topology_buttons["Add link"].state(["!disabled"] if len(names) >= 2 else ["disabled"])
        for selector in self.router_selectors:
            selector.configure(values=names, state="readonly" if names else "disabled")
        for variable in (self.spf_root, self.inspector, self.packet_source, self.packet_target):
            if variable.get() not in self.network.routers:
                variable.set(names[0] if names else "")
        if not names:
            self.destination_ip.set("")
        links = ["-".join(key) for key in sorted(self.network.links)]
        self.link_selector.configure(values=links)
        if self.link_name.get() not in links:
            self.link_name.set(links[0] if links else "")
        if links:
            self.select_link()
        else:
            self.link_cost.set("1")
            self.link_up.set(False)

    def _topology_changed(self, message: str) -> None:
        self._stop_everything()
        self._clear_packet_display()
        self.step = None
        self.drag_router = None
        self._refresh_selectors()
        self.spf_note.set("Topology changed. Existing tables are STALE; new routers know only their own loopback. "
                          "Use Build all now or Animate all before forwarding to a new destination.")
        self._log(f"TOPOLOGY revision {self.network.revision}: {message} No automatic SPF.")
        self._refresh_all()

    def _show_editor(self, title: str, fields: list, submit, hint: str):
        """A small modal form. Errors stay in the form; Cancel never changes data."""
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            return None
        if self.editor_window is not None and self.editor_window.winfo_exists():
            self.editor_window.lift()
            return self.editor_window
        self._pause_spf()
        self._cancel_packet()
        self.draw_network()
        self._refresh_status()
        dialog = tk.Toplevel(self.root)
        self.editor_window = dialog
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        values = {}
        entries = []
        for row, (key, label, value, choices) in enumerate(fields):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            variable = tk.StringVar(master=dialog, value=value)
            values[key] = variable
            if choices is None:
                entry = ttk.Entry(panel, textvariable=variable, width=25)
            else:
                entry = ttk.Combobox(panel, textvariable=variable, values=choices, state="readonly", width=23)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            entries.append(entry)
        ttk.Label(panel, text=hint, wraplength=440, style="Small.TLabel").grid(
            row=len(fields), column=0, columnspan=2, sticky="w", pady=(10, 6))
        error = tk.StringVar(master=dialog)
        ttk.Label(panel, textvariable=error, foreground=self.RED, wraplength=440).grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky="w")

        def close(event=None):
            self.editor_window = None
            dialog.destroy()

        def accept(event=None):
            try:
                submit({key: var.get().strip() for key, var in values.items()})
            except ValueError as exc:
                error.set(str(exc))
                return
            close()

        buttons = ttk.Frame(panel)
        buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=close).pack(side="left", padx=4)
        ttk.Button(buttons, text=title, command=accept, style="Accent.TButton").pack(side="left", padx=4)
        dialog.bind("<Escape>", close)
        dialog.bind("<Return>", accept)
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.update_idletasks()
        dialog.geometry(f"+{self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)}"
                        f"+{self.root.winfo_rooty() + 100}")
        dialog.grab_set()
        entries[0].focus_set()
        # Expose form state to GUI smoke tests, without a nested event loop.
        dialog.form_values = values
        dialog.form_error = error
        dialog.submit_form = accept
        dialog.cancel_form = close
        return dialog

    def add_router_dialog(self, position: tuple[float, float] | None = None):
        suggested = self.network.suggest_router()
        x, y = position if position is not None else (suggested.x, suggested.y)

        def submit(values):
            neighbor = None if values["neighbor"] == "(none)" else values["neighbor"]
            try:
                cost = int(values["cost"]) if neighbor is not None else 1
            except ValueError as exc:
                raise ValueError("Link cost must be a positive integer.") from exc
            router = Router(values["name"], values["address"], x, y)
            self.engine.add_router(router, neighbor, cost)
            self.inspector.set(router.name)
            self.packet_target.set(router.name)
            self.destination_ip.set(router.address)
            self._topology_changed(f"Added router {router.name} ({router.address}/32).")
            if neighbor is not None:
                self.select_link(tuple(sorted((router.name, neighbor))))
            self.tabs.select(self.live_tab)

        return self._show_editor("Add router", [
            ("name", "Router name", suggested.name, None),
            ("address", "IPv4 loopback", suggested.address, None),
            ("neighbor", "Connect to (optional)", "(none)", ["(none)"] + sorted(self.network.routers)),
            ("cost", "First link cost", "1", None),
        ], submit, "Names: 1-12 letters, digits or underscores; start with a letter. IPs must be unique. "
           "Choose (none) for an isolated router, or add its first connection now.")

    def add_link_dialog(self):
        names = sorted(self.network.routers)
        if len(names) < 2:
            messagebox.showinfo("Add link", "Add another router first.", parent=self.root)
            return None
        a = self.inspector.get()
        b = next((name for name in names if name != a and tuple(sorted((a, name))) not in self.network.links),
                 next(name for name in names if name != a))

        def submit(values):
            try:
                cost = int(values["cost"])
            except ValueError as exc:
                raise ValueError("Link cost must be a positive integer.") from exc
            self.network.add_link(values["a"], values["b"], cost)
            self._topology_changed(f"Added link {values['a']}-{values['b']}, cost {cost}.")
            self.select_link(tuple(sorted((values["a"], values["b"]))))

        return self._show_editor("Add link", [
            ("a", "From router", a, names), ("b", "To router", b, names),
            ("cost", "Link cost", "1", None),
        ], submit, "Links are bidirectional. Choose two different routers and a positive integer cost. "
           "Use the existing link editor to update a link that is already present.")

    def _canvas_position(self, x: float, y: float) -> tuple[float, float]:
        width, height = max(self.canvas.winfo_width(), 300), max(self.canvas.winfo_height(), 170)
        bottom_margin = 55 if self.compact else 105
        return (min(0.98, max(0.02, (x - 40) / (width - 80))),
                min(0.98, max(0.02, (y - 42) / max(1, height - bottom_margin))))

    def _add_router_at_click(self, event) -> None:
        # A double click on an existing router/link must not create another router.
        for item in self.canvas.find_overlapping(event.x - 4, event.y - 4, event.x + 4, event.y + 4):
            if any(tag.startswith(("router_", "link_")) for tag in self.canvas.gettags(item)):
                return
        self.drag_router = None
        self.add_router_dialog(self._canvas_position(event.x, event.y))

    def _start_drag(self, event, name: str) -> None:
        self.drag_router = name
        x, y = self._positions()[name]
        self.drag_offset = (event.x - x, event.y - y)
        self.inspect_router(name)

    def _drag_router(self, event) -> None:
        if self.drag_router is None:
            return
        x, y = self._canvas_position(event.x - self.drag_offset[0], event.y - self.drag_offset[1])
        self.network.move_router(self.drag_router, x, y)
        self.draw_network()
        self._refresh_graph_title()

    def _end_drag(self, event=None) -> None:
        self.drag_router = None

    def select_link(self, key: tuple[str, str] | None = None) -> None:
        if not self.network.links:
            return
        if key is not None:
            self.link_name.set("-".join(key))
        a, b = self.link_name.get().split("-")
        link = self.network.links[tuple(sorted((a, b)))]
        self.link_cost.set(str(link.cost))
        self.link_up.set(link.enabled)

    def apply_link(self) -> None:
        if not self.link_name.get():
            return
        try:
            cost = int(self.link_cost.get())
            self.network._validate_cost(cost)
        except ValueError:
            messagebox.showerror("Invalid cost", "Enter a positive integer link cost.", parent=self.root)
            return
        a, b = self.link_name.get().split("-")
        if not self.network.update_link(a, b, cost, self.link_up.get()):
            return
        self._topology_changed(f"{a}-{b}, cost {cost}, {'UP' if self.link_up.get() else 'DOWN'}.")

    def toggle_link(self, key: tuple[str, str]) -> None:
        self.select_link(key)
        self.link_up.set(not self.link_up.get())
        self.apply_link()

    def select_target(self, event=None) -> None:
        router = self.network.routers.get(self.packet_target.get())
        self.destination_ip.set(router.address if router else "")

    def inspect_router(self, router: str) -> None:
        if router not in self.network.routers:
            return
        self.inspector.set(router)
        self._refresh_route_table()
        self.draw_network()
        self.tabs.select(self.live_tab)

    def _confirm_packet_tables(self, packet: Packet) -> bool:
        """Explicit setup choice BEFORE injection, never SPF inside forwarding.

        Do not silently repair stale tables: they are useful for failure lessons.
        Checking table metadata is not a shortest-path calculation or packet trace.
        """
        if str(packet.destination) == self.network.routers[packet.source].address:
            return True  # Local loopback delivery does not require network-wide SPF.
        missing = [name for name in sorted(self.network.routers)
                   if self.engine.table_status(name) == "local only"]
        stale = [name for name in sorted(self.network.routers)
                 if self.engine.table_status(name) == "STALE"]
        if not missing and not stale:
            return True

        def summarize(names):
            return ", ".join(names[:12]) + (f" ... ({len(names)} routers)" if len(names) > 12 else "")

        details = []
        if missing:
            details.append("SPF not completed at: " + summarize(missing))
        if stale:
            details.append("Out-of-date tables at: " + summarize(stale))
        # Native dialogs run a nested Tk loop, so pause jobs before asking.
        if not self._pause_for_file_dialog():
            return False
        answer = messagebox.askyesnocancel(
            "Routing tables not ready",
            "\n".join(details) + "\n\nA packet may be dropped even with TTL remaining. "
            "Each intermediate router needs its OWN installed routing table.\n\n"
            "Yes: build all routing tables BEFORE creating the packet.\n"
            "No: use current tables unchanged (intentional failure experiment).\n"
            "Cancel: return without creating a packet.\n\n"
            "Rebuilding cannot repair a disconnected graph or an unknown destination IP.",
            parent=self.root)
        if answer is None:
            return False
        if answer:
            self.build_all()
        else:
            self._log("PACKET SETUP: explicitly using incomplete/stale installed tables; no automatic SPF.")
        return True

    def new_packet(self) -> bool:
        if not self._require_router():
            return False
        if ((self.about_window is not None and self.about_window.winfo_exists()) or
                (self.editor_window is not None and self.editor_window.winfo_exists())):
            return False
        try:
            destination = ipaddress.IPv4Address(self.destination_ip.get().strip())
            packet = Packet(self.packet_source.get(), destination, int(self.ttl_value.get()))
        except (ValueError, ipaddress.AddressValueError):
            messagebox.showerror("Invalid packet", "Enter a valid IPv4 address and TTL from 1 to 255.",
                                 parent=self.root)
            return False
        if not self._confirm_packet_tables(packet):
            return False
        self._pause_spf(clear_queue=True)
        # Incomplete SPF work is abandoned, never silently installed.
        if self.iterator is not None:
            self._log("Incomplete SPF abandoned; packets use the previously installed tables.")
            self.spf_note.set("SPF paused/abandoned. Packet forwarding uses INSTALLED tables only.")
        self.iterator = None
        self._cancel_packet(clear=True)
        self.packet = packet
        self.packet_sequence += 1
        self.trace_count = 0
        self.trace_decisions.clear()
        self.trace_tree.delete(*self.trace_tree.get_children())
        self.inspector.set(packet.source)
        self.lookup_router = packet.source
        self.packet_note.set(f"Packet #{self.packet_sequence} ready at {packet.source}; destination "
                             f"{packet.destination}; TTL {packet.ttl}. Press Next hop or Play packet.")
        self._log(f"DATA PLANE: new packet at {packet.source}, destination {packet.destination}, TTL {packet.ttl}.")
        self.tabs.select(self.live_tab)
        self._refresh_all()
        return True

    def step_packet(self) -> None:
        if self.packet_animating:
            return
        self.packet_auto = False
        self._cancel_job("packet_job")
        self.packet_play_button.configure(text="Play packet")
        if self.packet is None or self.packet.done:
            if not self.new_packet():
                return
        self._packet_hop()

    def toggle_packet(self) -> None:
        if self.packet_auto:
            self.packet_auto = False
            self._cancel_job("packet_job")
            self.packet_play_button.configure(text="Play packet")
            self._refresh_status()
            return
        if self.packet is None or self.packet.done:
            if not self.new_packet():
                return
        self.packet_auto = True
        self.packet_play_button.configure(text="Pause packet")
        if not self.packet_animating:
            self.packet_job = self.root.after(20, self._packet_hop)
        self._refresh_status()

    def _packet_hop(self) -> None:
        self.packet_job = None
        if self.packet is None or self.packet.done or self.packet_animating:
            return
        decision = forward_one_hop(self.engine, self.packet)
        self.last_decision = decision
        self.lookup_router = decision.router
        self.inspector.set(decision.router)
        self.highlight_prefix = decision.prefix
        self.trace_count += 1
        action = (f"Forward -> {decision.next_hop} (+{decision.cost})" if decision.kind == "forward" else
                  f"DROP: {decision.reason_code}" if decision.kind == "drop" else "DELIVER")
        self.trace_decisions[str(self.trace_count)] = decision
        self.trace_tree.insert("", "end", iid=str(self.trace_count), values=(
            self.trace_count, decision.router, decision.prefix, action,
            f"{decision.ttl_before} -> {decision.ttl_after}"), tags=(decision.kind,))
        self.trace_tree.see(str(self.trace_count))
        self.trace_tree.selection_set(str(self.trace_count))
        self.packet_note.set(decision.message)
        self._log(f"PACKET #{self.packet_sequence}: {decision.message}")
        self._refresh_all()
        if decision.kind == "forward":
            self.packet_animating = True
            self.packet_position = (decision.router, decision.next_hop, 0.0)
            self._animate_edge(decision.router, decision.next_hop, time.monotonic(), max(0.16, self.speed.get()))
        else:
            self.packet_auto = False
            self.packet_play_button.configure(text="Play packet")
            path = " -> ".join(self.packet.path)
            self.packet_note.set(f"{decision.message}\nPath: {path} | "
                                 f"{len(self.packet.path) - 1} hops | total link cost {self.packet.total_cost}")
            self._refresh_status()

    def _animate_edge(self, a: str, b: str, start: float, duration: float) -> None:
        self.frame_job = None
        if not self.packet_animating or self.packet is None:
            return
        progress = min(1.0, (time.monotonic() - start) / duration)
        self.packet_position = (a, b, progress)
        self.draw_network()
        if progress < 1.0:
            self.frame_job = self.root.after(20, self._animate_edge, a, b, start, duration)
        else:
            self.packet_animating = False
            self.packet_position = None
            self.draw_network()
            if self.packet_auto:
                self.packet_job = self.root.after(self._delay(), self._packet_hop)
            self._refresh_status()

    def stop_packet(self) -> None:
        self._cancel_packet(clear=True)
        self.packet_note.set("Packet stopped. Create a new packet to restart from its source.")
        self._refresh_all()

    def _keep_trace_selection_visible(self, event=None) -> None:
        selection = self.trace_tree.selection()
        if selection:
            self.trace_tree.see(selection[0])

    def _show_trace_decision(self, event=None) -> None:
        selection = self.trace_tree.selection()
        decision = self.trace_decisions.get(selection[0]) if selection else None
        if decision is not None:
            # Store the original message instead of re-evaluating a historical hop.
            message = decision.message
            if (not self.compact and self.packet is not None and self.packet.done
                    and selection[0] == str(self.trace_count)):
                message += (f"\nPath: {' -> '.join(self.packet.path)} | "
                            f"{len(self.packet.path) - 1} hops | total link cost {self.packet.total_cost}")
            self.packet_note.set(message)

    def _refresh_packet_state(self) -> None:
        packet = self.packet
        if packet is None:
            self.packet_state.set("No packet | Initial TTL applies to the next new packet." if self.network.routers
                                  else "No packet | Add your first router to get started.")
        else:
            state = ("in transit" if self.packet_animating else packet.outcome.upper())
            self.packet_state.set(
                f"Packet #{self.packet_sequence}: {packet.source} -> {packet.destination} | "
                f"At {packet.current} | TTL now {packet.ttl} (initial {packet.initial_ttl}) | {state}")

    def _clear_packet_display(self) -> None:
        self.trace_decisions.clear()
        self._refresh_packet_state()
        self.trace_tree.delete(*self.trace_tree.get_children())
        self.packet_note.set("Build the routing tables, then create a packet." if self.network.routers
                             else "Add routers and links, then build the routing tables before sending a packet.")
        self.trace_count = 0

    def _delay(self) -> int:
        return int(self.speed.get() * 1000)

    def _refresh_all(self) -> None:
        self._refresh_graph_title()
        self._refresh_work_table()
        self._refresh_route_table()
        self._refresh_all_tables()
        self._refresh_status()
        self.draw_network()

    def _refresh_work_table(self) -> None:
        old_view = self.work_tree.yview()[0]
        self.work_tree.delete(*self.work_tree.get_children())
        step = self.step
        self.work_title.set(f"DIJKSTRA WORKING STATE | root {step.source}" if step else
                            "DIJKSTRA WORKING STATE | no calculation yet")
        for name in sorted(self.network.routers):
            if step is None:
                values, tags = (name, "--", "--", "--", "not started"), ()
            else:
                distance = step.distances[name]
                state = "FINAL" if name in step.settled else (
                    "unreachable" if step.phase == "finish" else
                    "unseen" if math.isinf(distance) else "tentative")
                tag = "active" if name == step.current else "final" if name in step.settled else (
                    "tentative" if not math.isinf(distance) else "")
                values = (name, metric(distance), step.previous[name] or "--",
                          "local" if name == step.source else step.next_hop_to(name) or "--", state)
                tags = (tag,)
            self.work_tree.insert("", "end", iid=name, values=values, tags=tags)
        self.work_tree.yview_moveto(old_view)
        self.code_text.configure(state="normal")
        self.code_text.tag_remove("active", "1.0", "end")
        if step is not None:
            # Pseudocode starts at text line 3.
            line = 3 + step.code_line
            self.code_text.tag_add("active", f"{line}.0", f"{line}.end")
        self.code_text.configure(state="disabled")

    def _refresh_route_table(self) -> None:
        if not self.network.routers:
            self.route_tree.delete(*self.route_tree.get_children())
            self.table_title.set("ROUTING TABLE | no routers")
            self.table_note.set("Create a router with Add router. Each new router starts with its local /32 route.")
            return
        old_view = self.route_tree.yview()[0]
        selected = None
        router = self.inspector.get()
        staging = (self.packet is None and self.iterator is not None and self.step is not None
                   and self.step.source == router)
        table = routes_from_step(self.network, self.step) if staging else self.engine.tables[router]
        status = self.engine.table_status(router)
        self.table_title.set(f"ROUTING TABLE AT {router} | {'STAGING' if staging else 'INSTALLED'}")
        self.route_tree.delete(*self.route_tree.get_children())
        for destination, route in sorted(table.items()):
            state = "staged" if staging else "local" if route.next_hop is None else status
            tag = "staged" if staging else "stale" if status == "STALE" and route.next_hop else ""
            iid = self.route_tree.insert("", "end", iid=destination, values=(
                str(route.prefix), route.next_hop or "local", route.cost, route.interface, state), tags=(tag,))
            if self.packet is not None and router == self.lookup_router and str(route.prefix) == self.highlight_prefix:
                self.route_tree.selection_set(iid)
                selected = iid
        self.route_tree.yview_moveto(old_view)
        if selected is not None:
            self.route_tree.see(selected)
        if staging:
            note = "Finalized entries appear here one by one. This is a STAGING table, not yet used by packets. "
            note += "The complete table is installed when SPF finishes."
        elif status == "local only":
            note = "Only the local loopback is installed. This router has not completed SPF yet."
        elif status == "STALE":
            note = "STALE: installed for an older topology. Packets still use this table; a next hop may now fail."
        else:
            note = f"Installed at topology revision {self.engine.versions[router]}. "
            note += "A packet uses destination IP -> matched prefix -> next hop."
        self.table_note.set(note)

    def _refresh_all_tables(self) -> None:
        yview = self.all_tree.yview()[0]
        self.all_tree.delete(*self.all_tree.get_children())
        for index, router in enumerate(sorted(self.network.routers)):
            status = self.engine.table_status(router)
            for route in self.engine.tables[router].values():
                tags = ("alternate",) if index % 2 else ()
                if status == "STALE" and route.next_hop:
                    tags += ("stale",)
                self.all_tree.insert("", "end", values=(router, str(route.prefix), route.next_hop or "local",
                                     route.cost, "local" if route.next_hop is None else status), tags=tags)
        self.all_tree.yview_moveto(yview)

    def _refresh_status(self) -> None:
        self._refresh_packet_state()
        current = sum(self.engine.table_status(name) == "current" for name in self.network.routers)
        activity = ("empty topology" if not self.network.routers else "SPF playing" if self.spf_auto
                    else "packet playing" if self.packet_auto else "ready / paused")
        self.status_text.set(f"Topology {self.network.revision}  |  SPF tables {current}/{len(self.network.routers)}  |  "
                             f"SPF runs {self.engine.spf_runs}  |  {activity}")

    def _positions(self) -> dict[str, tuple[float, float]]:
        width, height = max(self.canvas.winfo_width(), 300), max(self.canvas.winfo_height(), 170)
        # Reserve space above for the heading and below for the router IP labels.
        bottom_margin = 55 if self.compact else 105
        return {name: (40 + router.x * (width - 80), 42 + router.y * (height - bottom_margin))
                for name, router in self.network.routers.items()}

    def draw_network(self) -> None:
        if not hasattr(self, "canvas"):
            return
        canvas = self.canvas
        canvas.delete("all")
        positions = self._positions()
        canvas.create_text(17, 18, anchor="w", text="LINK-STATE TOPOLOGY", fill=self.INK,
                           font=("Segoe UI", 10, "bold"))
        canvas.create_text(canvas.winfo_width() - 16, 18, anchor="e", text="Link labels = cost, not hop count",
                           fill=self.MUTED, font=("Segoe UI", 9))
        if not self.network.routers:
            center_x = max(300, canvas.winfo_width()) / 2
            center_y = max(170, canvas.winfo_height()) / 2
            canvas.create_text(center_x, center_y - 12, text="Start your own topology", fill=self.BRAND,
                               font=("Segoe UI", 17, "bold"), tags=("empty_hint",))
            canvas.create_text(center_x, center_y + 25,
                               text="Click Add router or double-click here to add your first node.",
                               fill=self.MUTED, font=("Segoe UI", 10),
                               width=max(250, canvas.winfo_width() - 70), tags=("empty_hint",))
            return
        step = self.step
        tree_edges: set[tuple[str, str]] = set()
        if step and self.packet is None:
            tree_edges = {tuple(sorted((name, step.previous[name]))) for name in step.settled
                          if step.previous[name] is not None}
        trail: set[tuple[str, str]] = set()
        if self.packet:
            path = self.packet.path
            # Only completed links form the trail; the current link has its own arrow.
            end = len(path) - 2 if self.packet_position else len(path) - 1
            trail = {tuple(sorted((path[i], path[i + 1]))) for i in range(max(0, end))}
        for key, link in sorted(self.network.links.items()):
            x1, y1 = positions[link.a]
            x2, y2 = positions[link.b]
            color, width, dash = "#a0afc2", 2, ()
            if not link.enabled:
                color, dash = self.RED, (6, 5)
            elif key in tree_edges:
                color, width = self.GREEN, 4
            if step and self.packet is None and step.current and step.neighbor:
                if key == tuple(sorted((step.current, step.neighbor))):
                    color, width = self.AMBER, 5
            if key in trail:
                color, width = self.PURPLE, 5
            tag = f"link_{link.a}_{link.b}"
            canvas.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash, tags=(tag,))
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            # Put vertical and diagonal link labels beside, rather than on, a node.
            if abs(x1 - x2) < 2:
                mx += 17
            label = str(link.cost) if link.enabled else f"DOWN ({link.cost})"
            label_width = 13 + 3.6 * len(label)
            canvas.create_rectangle(mx - label_width, my - 12, mx + label_width, my + 12,
                                    fill="white", outline="#dce4ef", tags=(tag,))
            canvas.create_text(mx, my, text=label, fill=color if not link.enabled else self.INK,
                               font=("Segoe UI", 10, "bold"), tags=(tag,))
            canvas.tag_bind(tag, "<Button-1>", lambda event, selected=key: self.select_link(selected))
            canvas.tag_bind(tag, "<Button-3>", lambda event, selected=key: self.toggle_link(selected))
            canvas.tag_bind(tag, "<Control-Button-1>", lambda event, selected=key: self.toggle_link(selected))
        if self.packet_position:
            a, b, progress = self.packet_position
            x1, y1 = positions[a]
            x2, y2 = positions[b]
            length = max(1.0, math.hypot(x2 - x1, y2 - y1))
            dx, dy = (x2 - x1) / length, (y2 - y1) / length
            canvas.create_line(x1 + 28 * dx, y1 + 28 * dy, x2 - 32 * dx, y2 - 32 * dy,
                               fill=self.PURPLE, width=4, arrow="last", arrowshape=(12, 14, 5))
        for name, router in self.network.routers.items():
            x, y = positions[name]
            fill, outline, text = "#eef3fa", "#7b8da6", self.INK
            if step and self.packet is None:
                if name in step.settled:
                    fill, outline = "#d1fae5", self.GREEN
                elif not math.isinf(step.distances[name]):
                    fill, outline = "#fff3d1", self.AMBER
                if name == step.current:
                    fill, outline = "#fed7aa", self.AMBER
            if self.packet and name in self.packet.path:
                fill, outline = "#fae8ff", self.PURPLE
            tag = f"router_{name}"
            if name == self.inspector.get():
                canvas.create_oval(x - 32, y - 32, x + 32, y + 32, outline=self.BLUE, width=2)
            canvas.create_oval(x - 26, y - 26, x + 26, y + 26, fill=fill, outline=outline,
                               width=2, tags=(tag,))
            canvas.create_text(x, y, text=name, fill=text, font=("Segoe UI", max(7, min(17, 40 // len(name))), "bold"), tags=(tag,))
            if not self.compact:
                canvas.create_text(x, y + 43, text=f"{router.address}/32", fill=self.MUTED,
                                   font=("Segoe UI", 9), tags=(tag,))
            if step and self.packet is None:
                dist = metric(step.distances[name])
                label = f"d={dist}" + (" [root]" if name == step.source else "")
                canvas.create_text(x, y - (35 if self.compact else 42), text=label,
                                   fill=self.GREEN if name in step.settled else self.AMBER,
                                   font=("Segoe UI", 10, "bold"))
            canvas.tag_bind(tag, "<Button-1>", lambda event, selected=name: self._start_drag(event, selected))
        if self.packet:
            if self.packet_position:
                a, b, progress = self.packet_position
                x1, y1 = positions[a]
                x2, y2 = positions[b]
                x, y = x1 + progress * (x2 - x1), y1 + progress * (y2 - y1)
            else:
                x, y = positions[self.packet.current]
                y -= 48
            canvas.create_oval(x - 9, y - 9, x + 9, y + 9, fill=self.PURPLE, outline="white", width=2)
            canvas.create_text(x + 14, y - 13, anchor="w", text=f"IP #{self.packet_sequence}",
                               fill=self.PURPLE, font=("Segoe UI", 10, "bold"))

    def export_tables(self) -> None:
        filename = filedialog.asksaveasfilename(parent=self.root, title="Export installed routing tables",
                                               defaultextension=".json", initialfile="routing_tables.json",
                                               filetypes=[("JSON", "*.json")])
        if not filename:
            return
        try:
            Path(filename).write_text(json.dumps(self.engine.export_data(), indent=2), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Export failed", str(error), parent=self.root)
            return
        self._log(f"Exported installed tables to {filename}.")

    def _refresh_graph_title(self) -> None:
        marker = " *" if self.has_unsaved_graph() else ""
        filename = self.graph_file.name if self.graph_file else "Untitled graph"
        self.root.title(f"Dijkstra Routing Lab {__version__} | {filename}{marker}")

    def has_unsaved_graph(self) -> bool:
        # A drawing move does not increment the routing revision but IS a file edit.
        # SPF runs and packet movement do not alter this topology-only snapshot.
        return graph_to_data(self.network) != self.saved_graph

    def _pause_for_file_dialog(self) -> bool:
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            return False
        if self.editor_window is not None and self.editor_window.winfo_exists():
            self.editor_window.lift()
            return False
        self._pause_spf()
        self._cancel_packet()  # Retain the packet and installed tables, only pause.
        self.draw_network()
        self._refresh_status()
        return True

    def save_graph(self, save_as: bool = False) -> bool:
        """Return False on cancellation/failure, including before a destructive action."""
        if not self._pause_for_file_dialog():
            return False
        filename = self.graph_file
        if save_as or filename is None:
            options = {"initialdir": str(filename.parent)} if filename else {}
            chosen = filedialog.asksaveasfilename(
                parent=self.root, title="Save graph", defaultextension=".json",
                initialfile=filename.name if filename else "network.graph.json",
                filetypes=[("JSON graph", "*.json"), ("All files", "*")], **options)
            if not chosen:
                return False
            filename = Path(chosen)
        try:
            save_graph_file(self.network, filename)
        except (OSError, ValueError, OverflowError) as error:
            messagebox.showerror("Save graph failed", str(error), parent=self.root)
            return False
        self.graph_file = filename
        self.saved_graph = graph_to_data(self.network)
        self._refresh_graph_title()
        self._log(f"SAVED GRAPH: {filename} ({len(self.network.routers)} routers, "
                  f"{len(self.network.links)} links, including drawing positions).")
        return True

    def _confirm_replace_graph(self, action: str) -> bool:
        if not self.has_unsaved_graph():
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved graph", f"Save graph changes before {action}?\n\n"
            "Yes: save and continue. No: discard changes. Cancel: keep working.", parent=self.root)
        if answer is None:
            return False
        return self.save_graph() if answer else True

    def _install_graph(self, network: Network, filename: Path | None = None) -> None:
        """Swap validated topology and clear every state item referring to the old graph."""
        self._stop_everything()
        self.network = network
        self.engine = RoutingEngine(network)
        self.graph_file = filename
        self.saved_graph = graph_to_data(network)
        self.step = None
        self.run_revision = network.revision
        self.drag_router = None
        self.packet_sequence = 0
        self.step_count = 0
        names = sorted(network.routers)
        self.spf_root.set(names[0] if names else "")
        self.inspector.set(names[0] if names else "")
        self.packet_source.set(names[0] if names else "")
        self.packet_target.set(names[-1] if names else "")
        self.destination_ip.set(network.routers[names[-1]].address if names else "")
        self.ttl_value.set("16")
        self._refresh_selectors()
        self._clear_packet_display()
        self._refresh_all()
        self.tabs.select(self.live_tab)

    def load_graph(self) -> bool:
        if not self._pause_for_file_dialog():
            return False
        options = {"initialdir": str(self.graph_file.parent)} if self.graph_file else {}
        chosen = filedialog.askopenfilename(parent=self.root, title="Load graph",
                                           filetypes=[("JSON graph", "*.json"), ("All files", "*")], **options)
        if not chosen:
            return False
        # Validate FIRST, then ask to replace: an invalid file leaves the current
        # graph, file association, unsaved marker and installed routes untouched.
        try:
            network = load_graph_file(chosen)
        except (OSError, ValueError, OverflowError) as error:
            messagebox.showerror("Load graph failed", str(error), parent=self.root)
            return False
        if not self._confirm_replace_graph("loading another graph"):
            return False
        # Saving first may have overwritten the selected file (including Ctrl+O
        # on the current graph). Re-read so memory and disk cannot disagree.
        try:
            network = load_graph_file(chosen)
        except (OSError, ValueError, OverflowError) as error:
            messagebox.showerror("Load graph failed", str(error), parent=self.root)
            return False
        self._install_graph(network, Path(chosen))
        self.spf_note.set("Graph loaded. Only local routes are installed. "
                          "Use Build all now or Animate all to calculate the routing tables." if network.routers
                          else "Empty graph loaded. Use Add router or double-click the graph to begin.")
        self._log(f"LOADED GRAPH: {chosen}. {len(network.routers)} routers and "
                  f"{len(network.links)} links; previous SPF and packet state cleared.")
        return True

    def new_topology(self) -> bool:
        """Start an untitled empty graph after the usual Save / Discard / Cancel check."""
        if not self._pause_for_file_dialog() or not self._confirm_replace_graph("starting a new topology"):
            return False
        self._install_graph(Network([], []))
        self.spf_note.set("Empty topology. Use Add router, or double-click the graph, to begin.")
        self._log("NEW TOPOLOGY: started with zero routers and links. Saved graph files are not deleted.")
        return True

    def reset_network(self) -> None:
        if not self._pause_for_file_dialog() or not self._confirm_replace_graph("resetting the network"):
            return
        self._install_graph(make_default_network())
        self.select_link(("D", "E"))
        self.spf_note.set("Network reset. Press New SPF or Step SPF to begin at router A.")
        self._log("RESET: restored default topology; all routers have local routes only.")

    def close(self) -> None:
        if not self._pause_for_file_dialog() or not self._confirm_replace_graph("closing"):
            return
        self._stop_everything()
        self.root.destroy()


GUI_GUIDE = """BUILD YOUR OWN TOPOLOGY

Click New topology in the toolbar, choose File > New topology, or press Ctrl+N.
This clears the current workspace to zero routers and zero links. Save / Discard / Cancel protects unsaved edits. Previously saved graph files are not deleted; the next Save graph asks for a new filename.

Click Add router or double-click the blank canvas. The first suggestion is A (10.0.0.1), with no initial connection. Add more routers and connect them with Add link, or choose an existing neighbor while adding a router. Build all now then calculates each router's table; send packets as usual.

SPF, packet controls and Add link are disabled until enough routers exist. Empty topologies can also be saved and loaded in this version. Reset network still restores the original A-F example; Load graph opens your own saved topology. New topology does not change what is loaded at application startup.

A FIRST WALKTHROUGH

1. Keep root A. Click New SPF, then Step SPF repeatedly.

Watch the smallest tentative distance become FINAL. An amber link is being inspected. The explanation shows the actual comparison, for example 2 + 3 < 7. Finalized routing entries appear in the STAGING table. They become INSTALLED when the calculation finishes.

2. Click Build all now, or Animate all.

Each router runs Dijkstra with ITSELF as root. Click a router or open All tables to compare next hops. Computing a table only at A is not enough for intermediate routers to forward packets.

3. Keep source A and target F. Click New packet, then Next hop or Play packet.

The packet's destination stays 10.0.0.6. At every router, the matching /32 entry is selected in the installed table. The trace shows the next hop and TTL. No new Dijkstra calculation is made during forwarding.

The default path is A -> C -> B -> D -> E -> F.
Its cost is 2 + 3 + 2 + 1 + 2 = 10.
A -> C -> E -> F has fewer hops, but costs 11.

ADDING ROUTERS AND LINKS

Click Add router, or double-click empty space on the graph. Enter a unique name and IPv4 loopback address. The program suggests the next free name (G, H, ...) and address. Optionally connect the new router to an existing router and set the link cost. Choose (none) to start with an isolated router.

Use Add link to connect any two routers. New routers appear immediately in Root, Inspect router, Source and Target. Run Build all now or Animate all to calculate updated routing tables before sending packets to the new destinations.

Drag a router to change its drawing position. Moving a router does not change link costs or require SPF. Duplicate names/IPs, self-links and duplicate links are rejected.

Try adding G (10.0.0.7) connected to F with cost 3. Build all tables, then send A -> G: A -> C -> B -> D -> E -> F -> G, cost 13.

PACKET DROPS AND TTL

Initial TTL is used when you create a NEW packet. TTL now in the packet status is the remaining value; editing Initial TTL does not alter a packet already in progress.

Before creating a non-local packet, the program warns when any router has not completed SPF or has an out-of-date table. Yes builds all tables before injection. No explicitly uses the old tables for a failure experiment. Cancel returns without creating a packet. Forwarding itself never runs Dijkstra.

Drop reasons appear in the trace: NO_SPF (this router has not completed SPF), STALE_NO_ROUTE (old table has no entry), NO_ROUTE (current table has no entry), LINK_DOWN (installed next hop uses a failed link), INVALID_NEXT_HOP (no link to installed next hop), or TTL_EXPIRED. A positive TTL does not guarantee a route exists. Select a trace row to read its full explanation.

After loading or editing a graph, use Build all now. A disconnected destination or unknown IP still needs its topology/address corrected; increasing TTL cannot repair it.

SAVING AND LOADING GRAPHS

Save graph (Ctrl+S) writes routers, IPv4 addresses, positions, links, costs and up/down states to a JSON file. The first save asks for a filename. File > Save graph as... (Ctrl+Shift+S) saves another copy.

Load graph (Ctrl+O) restores a saved graph, replacing the current network. Routing tables and packet/algorithm progress are deliberately not restored. Click Build all now or Animate all after loading.

A * in the window title means the graph has unsaved changes, including moved nodes. Load, Reset and Exit offer Save / Discard / Cancel before losing edits. Cancelling a file dialog keeps the current graph; playback is paused.

Earlier Export tables JSON files can also be loaded. Positions from v1.1 are retained; older files without positions use a circular layout. Export tables remains a separate report, not a saved simulation session.

A LINK FAILURE

Build all tables. Select D-E, untick Link up, and Apply change. Send another packet BEFORE recalculating: the old tables send it toward the failed link, so it drops at D.

Now Build all now and send again. The new path is A -> C -> E -> F, cost 11.

OTHER EXPERIMENTS

- Set A-C cost to 9: after rebuilding, A -> F uses A -> B -> D -> E -> F, cost 12.
- Disable BOTH D-F and E-F, then rebuild: F is unreachable from A.
- Use TTL 3: the packet expires before it reaches F.
- Enter 10.99.0.1 as Dest. IP: no matching route exists.
- Compare Previous with Next hop. They are different concepts.
- Watch SPF runs stay unchanged during packet forwarding.

MODEL BOUNDARIES

All routers share a topology snapshot. The model omits OSPF neighbors, LSA flooding, areas, ECMP, interface addresses, Ethernet, ARP, checksums and ICMP replies. Link costs are symmetric positive integers, not measured latency. Animation time is unrelated to cost.

Destinations are router loopbacks (/32). TTL is decremented on forwarding, but not on local delivery. The model uses one installed table as a simplified RIB/FIB; it does not model separate hardware FIB programming.

Tables stay installed after link edits so you can observe stale routes. Recalculation is manual; the animation is not a realistic distributed convergence timing simulation.

Windows: py -3 dijkstra_routing_demo.py
Other systems: python3 dijkstra_routing_demo.py

ABOUT AND BRANDING

Click About in the header, use Help > About, or press F1. The About window explains the learning purpose and model boundaries, displays the application version, copyright and license, and lets you open or copy the project's GitHub address. Playback is paused while About is open; your graph, installed routes and unfinished SPF work are retained. Resume playback explicitly after closing it.

The IHN icon and UCN logo are loaded from the local assets folder. The application still runs with text labels if optional logo files are missing. The IHN ICO can also be used for a Windows shortcut. This desktop application has a window icon, not a browser tab. No network request is made to load the logos.

COPYRIGHT AND LICENSE

Copyright 2026 Ib Helmer Nielsen.
Licensed under the Apache License, Version 2.0.
See LICENSE and NOTICE in the repository.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--print-tables", action="store_true", help="Print tables and a sample packet trace without a GUI.")
    args = parser.parse_args()
    if args.print_tables:
        engine = RoutingEngine(make_default_network())
        engine.calculate_all()
        for router in sorted(engine.tables):
            print(f"\nROUTER {router} | destination       next hop  cost  interface")
            for route in engine.tables[router].values():
                print(f"           {str(route.prefix):18} {route.next_hop or 'local':8} "
                      f"{route.cost:5}  {route.interface}")
        packet, trace = trace_packet(engine, "A", "10.0.0.6")
        print("\nPACKET TRACE")
        for decision in trace:
            print(decision.message)
        print(f"Path: {' -> '.join(packet.path)}; cost: {packet.total_cost}; outcome: {packet.outcome}")
        return 0
    if tk is None:
        print("Tkinter is not available. Use a Python installation with Tcl/Tk support.\n"
              "On Ubuntu/Debian: sudo apt install python3-tk\n"
              "To run only the model: python dijkstra_routing_demo.py --print-tables", file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"Cannot open a Tk window: {error}\nRun on a desktop with a graphical display.\n"
              "For a console demonstration add --print-tables.", file=sys.stderr)
        return 1
    RoutingDemo(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
