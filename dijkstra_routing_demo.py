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
from dataclasses import dataclass, field
import heapq
import ipaddress
import json
import math
from pathlib import Path
import sys
import time
from typing import Iterator

__author__ = "Ib Helmer Nielsen"
__copyright__ = "Copyright 2026 Ib Helmer Nielsen"
__license__ = "Apache-2.0"


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
        if not routers or len(self.routers) != len(routers):
            raise ValueError("Router names must be unique; at least one is required.")
        addresses = [router.address for router in routers]
        if len(set(addresses)) != len(addresses):
            raise ValueError("Router loopback addresses must be unique.")
        for router in routers:
            ipaddress.IPv4Address(router.address)
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
    path: list[str] = field(init=False)
    total_cost: int = 0
    done: bool = False
    outcome: str = "ready"

    def __post_init__(self) -> None:
        self.destination = ipaddress.IPv4Address(self.destination)
        if isinstance(self.ttl, bool) or not isinstance(self.ttl, int) or not 1 <= self.ttl <= 255:
            raise ValueError("TTL must be an integer from 1 to 255.")
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

    def stop(kind: str, message: str) -> ForwardDecision:
        packet.done, packet.outcome = True, kind
        return ForwardDecision(kind, router, prefix, None, ttl_before, packet.ttl, 0, message)

    if route is None:
        return stop("drop", f"DROP at {router}: no installed route to {packet.destination}.")
    if route.next_hop is None:
        return stop("deliver", f"DELIVER at {router}: {packet.destination} is this router's "
                    f"local loopback. TTL remains {packet.ttl}.")
    if packet.ttl <= 1:
        packet.ttl = 0
        return stop("drop", f"DROP at {router}: TTL expired before forwarding.")
    link = engine.network.links.get(tuple(sorted((router, route.next_hop))))
    if link is None or not link.enabled:
        return stop("drop", f"DROP at {router}: installed next hop {route.next_hop} uses "
                    "an unavailable link. Recalculate the routing tables.")
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
    BG = "#f1f5f9"
    INK = "#16263b"
    MUTED = "#526379"
    BLUE = "#1d4ed8"
    GREEN = "#087e66"
    AMBER = "#b45309"
    PURPLE = "#a21caf"
    RED = "#b91c1c"

    def __init__(self, root) -> None:
        self.root = root
        self.root.title("Dijkstra Routing Lab | Control plane -> Data plane")
        self.root.geometry(f"{min(1440, self.root.winfo_screenwidth() - 40)}x"
                           f"{min(900, max(740, self.root.winfo_screenheight() - 80))}")
        self.root.minsize(1180, 740)
        self.root.configure(background=self.BG)
        self.network = make_default_network()
        self.engine = RoutingEngine(self.network)
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
        self.step_count = 0
        self.event_count = 0

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
        self.packet_note = tk.StringVar(value="Build the routing tables, then create a packet.")
        self.table_note = tk.StringVar()
        self.work_title = tk.StringVar(value="DIJKSTRA WORKING STATE | no calculation yet")
        self.table_title = tk.StringVar()
        self._build_ui()
        self._refresh_all()
        self._log("Ready. Each router initially knows only its own /32 loopback.")
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
        style.map("Accent.TButton", background=[("active", "#1e40af")])

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(3, weight=1)
        outer.columnconfigure(0, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Dijkstra Routing Lab", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="01  Calculate shortest paths     02  Install next hops     03  Forward IP packets",
                  style="Small.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Button(header, text="Export tables", command=self.export_tables).grid(row=0, column=1, padx=5)
        ttk.Button(header, text="Reset network", command=self.reset_network).grid(row=0, column=2)

        controls = ttk.LabelFrame(outer, text="CONTROL PLANE  |  Dijkstra / shortest-path first", padding=(9, 6))
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(controls, text="Root").pack(side="left")
        self._combo(controls, self.spf_root, list(self.network.routers), 4).pack(side="left", padx=(4, 8))
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
        links.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(links, text="LINK EDITOR", style="Section.TLabel").pack(side="left", padx=(0, 8))
        selector = self._combo(links, self.link_name,
                               ["-".join(key) for key in sorted(self.network.links)], 6)
        selector.pack(side="left")
        selector.bind("<<ComboboxSelected>>", lambda event: self.select_link())
        ttk.Label(links, text="Cost").pack(side="left", padx=(10, 4))
        ttk.Spinbox(links, textvariable=self.link_cost, from_=1, to=9999, width=6).pack(side="left")
        ttk.Checkbutton(links, text="Link up", variable=self.link_up).pack(side="left", padx=8)
        ttk.Button(links, text="Apply change", command=self.apply_link).pack(side="left")
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
                                highlightbackground="#d7e0eb", width=710, height=370)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.canvas.bind("<Configure>", lambda event: self.draw_network())
        ttk.Label(left, text="Final / SPF tree: green   |   Comparing: amber   |   Packet: purple   |   Down: dashed",
                  style="Small.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(left, text="Click a router to inspect it. Click a cost to select a link; right-click a link to toggle it.",
                  style="Small.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 5))

        packet_box = ttk.LabelFrame(left, text="DATA PLANE  |  hop-by-hop forwarding", padding=8)
        packet_box.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(0, 5))
        row = ttk.Frame(packet_box)
        row.pack(fill="x")
        ttk.Label(row, text="Source").pack(side="left")
        self._combo(row, self.packet_source, list(self.network.routers), 3).pack(side="left", padx=(4, 10))
        ttk.Label(row, text="Target").pack(side="left")
        target = self._combo(row, self.packet_target, list(self.network.routers), 3)
        target.pack(side="left", padx=(4, 10))
        target.bind("<<ComboboxSelected>>", self.select_target)
        ttk.Label(row, text="Dest. IP").pack(side="left")
        ttk.Entry(row, textvariable=self.destination_ip, width=14).pack(side="left", padx=(4, 10))
        ttk.Label(row, text="TTL").pack(side="left")
        ttk.Spinbox(row, textvariable=self.ttl_value, from_=1, to=255, width=4).pack(side="left", padx=4)
        row = ttk.Frame(packet_box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="New packet", command=self.new_packet).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Next hop", command=self.step_packet).pack(side="left", padx=4)
        self.packet_play_button = ttk.Button(row, text="Play packet", command=self.toggle_packet,
                                             style="Accent.TButton")
        self.packet_play_button.pack(side="left", padx=4)
        ttk.Button(row, text="Stop packet", command=self.stop_packet).pack(side="left", padx=4)
        self.packet_label = ttk.Label(packet_box, textvariable=self.packet_note,
                                      wraplength=650, justify="left", style="Small.TLabel")
        self.packet_label.pack(fill="x", pady=(6, 0))
        self.trace_tree = self._tree(left,
            [("n", "#", 30), ("at", "At", 35), ("prefix", "Matched prefix", 135),
             ("action", "Decision", 220), ("ttl", "TTL", 70)], height=6)
        self.trace_tree.grid(row=4, column=0, sticky="ew", padx=(0, 8))
        self.trace_tree.tag_configure("drop", foreground=self.RED)
        self.trace_tree.tag_configure("deliver", foreground=self.GREEN)

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
        inspect = self._combo(row, self.inspector, list(self.network.routers), 4)
        inspect.pack(side="left", padx=6)
        inspect.bind("<<ComboboxSelected>>", lambda event: self.inspect_router(self.inspector.get()))
        ttk.Label(row, text="Double outline on the map", style="Small.TLabel").pack(side="left", padx=4)
        ttk.Label(live, textvariable=self.work_title, style="Section.TLabel").grid(row=1, column=0, sticky="w")
        self.work_tree = self._tree(live,
            [("router", "Node", 46), ("cost", "Cost", 55), ("parent", "Previous", 70),
             ("next", "Next hop", 75), ("state", "State", 105)], height=6)
        self.work_tree.grid(row=2, column=0, sticky="ew", pady=5)
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
        self.route_tree.tag_configure("staged", background="#fff3d1")
        self.route_tree.tag_configure("stale", foreground=self.RED)
        self.table_label = ttk.Label(live, textvariable=self.table_note, wraplength=510,
                                     justify="left", style="Small.TLabel")
        self.table_label.grid(row=6, column=0, sticky="ew", pady=(2, 8))
        ttk.Label(live, text="Previous = last router before the destination in the SPF tree.\n"
                  "Next hop = FIRST router after the root, used for forwarding.",
                  style="Small.TLabel").grid(row=7, column=0, sticky="w")
        live.bind("<Configure>", lambda event: self._wrap_live(event.width), add="+")
        left.bind("<Configure>", lambda event: self.packet_label.configure(wraplength=max(400, event.width - 40)))

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
        ttk.Label(outer, textvariable=self.status_text, style="Small.TLabel").grid(
            row=4, column=0, sticky="ew", pady=(8, 0))

    @staticmethod
    def _combo(parent, variable, values, width):
        return ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)

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
        compact = self.root.winfo_height() < 835
        self.compact = compact
        self.trace_tree.configure(height=3 if compact else 6)
        # Keep the editable packet controls usable on 1280/1366-pixel laptops.
        # Users may still drag the sash; the ratio resets only on window resize.
        if getattr(self, "_last_body_width", None) != event.width:
            self._last_body_width = event.width
            self.body.sashpos(0, int(event.width * 0.55))
        self.draw_network()

    def _wrap_live(self, width: int) -> None:
        for label in (self.spf_label, self.table_label):
            label.configure(wraplength=max(350, width - 25))

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
        self._stop_everything()
        self._clear_packet_display()
        self._begin_spf(self.spf_root.get())
        self.tabs.select(self.live_tab)

    def step_spf(self) -> None:
        self._pause_spf()
        self._cancel_packet(clear=True)
        if self.iterator is None or (self.step and self.step.source != self.spf_root.get()):
            self._begin_spf(self.spf_root.get())
        else:
            self._advance_spf()
        self.tabs.select(self.live_tab)

    def toggle_spf(self) -> None:
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
        self._pause_spf(clear_queue=True)
        self._cancel_packet(clear=True)
        if self.iterator is None or (self.step and self.step.source != self.spf_root.get()):
            self._begin_spf(self.spf_root.get())
        while self.iterator is not None:
            self._advance_spf()
        self._refresh_status()

    def animate_all(self) -> None:
        self._stop_everything()
        self._clear_packet_display()
        self.spf_queue = deque(sorted(self.network.routers))
        self._begin_spf(self.spf_queue.popleft())
        self.spf_auto = True
        self.spf_play_button.configure(text="Pause SPF")
        self.spf_job = self.root.after(self._delay(), self._spf_tick)
        self.tabs.select(self.live_tab)

    def build_all(self) -> None:
        self._stop_everything()
        self._clear_packet_display()
        self.engine.calculate_all()
        source = self.spf_root.get()
        self.step = self.engine.results[source]
        self.inspector.set(source)
        self.spf_note.set("All six routers ran their own SPF. All routing tables are now installed.")
        self._log("CONTROL PLANE: built and installed all six routing tables.")
        self._refresh_all()

    def select_link(self, key: tuple[str, str] | None = None) -> None:
        if key is not None:
            self.link_name.set("-".join(key))
        a, b = self.link_name.get().split("-")
        link = self.network.links[tuple(sorted((a, b)))]
        self.link_cost.set(str(link.cost))
        self.link_up.set(link.enabled)

    def apply_link(self) -> None:
        try:
            cost = int(self.link_cost.get())
            self.network._validate_cost(cost)
        except ValueError:
            messagebox.showerror("Invalid cost", "Enter a positive integer link cost.", parent=self.root)
            return
        a, b = self.link_name.get().split("-")
        if not self.network.update_link(a, b, cost, self.link_up.get()):
            return
        self._stop_everything()
        self._clear_packet_display()
        self.step = None
        self.spf_note.set("Topology changed. Old installed tables are retained and marked STALE. "
                          "Run SPF again to converge, or send a packet to test the old tables.")
        self._log(f"TOPOLOGY revision {self.network.revision}: {a}-{b}, cost {cost}, "
                  f"{'UP' if self.link_up.get() else 'DOWN'}. No automatic SPF.")
        self._refresh_all()

    def toggle_link(self, key: tuple[str, str]) -> None:
        self.select_link(key)
        self.link_up.set(not self.link_up.get())
        self.apply_link()

    def select_target(self, event=None) -> None:
        self.destination_ip.set(self.network.routers[self.packet_target.get()].address)

    def inspect_router(self, router: str) -> None:
        self.inspector.set(router)
        self._refresh_route_table()
        self.draw_network()
        self.tabs.select(self.live_tab)

    def new_packet(self) -> bool:
        try:
            destination = ipaddress.IPv4Address(self.destination_ip.get().strip())
            packet = Packet(self.packet_source.get(), destination, int(self.ttl_value.get()))
        except (ValueError, ipaddress.AddressValueError):
            messagebox.showerror("Invalid packet", "Enter a valid IPv4 address and TTL from 1 to 255.",
                                 parent=self.root)
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
        action = f"Forward -> {decision.next_hop} (+{decision.cost})" if decision.kind == "forward" else decision.kind.upper()
        self.trace_tree.insert("", "end", iid=str(self.trace_count), values=(
            self.trace_count, decision.router, decision.prefix, action,
            f"{decision.ttl_before} -> {decision.ttl_after}"), tags=(decision.kind,))
        self.trace_tree.see(str(self.trace_count))
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

    def _clear_packet_display(self) -> None:
        self.trace_tree.delete(*self.trace_tree.get_children())
        self.packet_note.set("Build the routing tables, then create a packet.")
        self.trace_count = 0

    def _delay(self) -> int:
        return int(self.speed.get() * 1000)

    def _refresh_all(self) -> None:
        self._refresh_work_table()
        self._refresh_route_table()
        self._refresh_all_tables()
        self._refresh_status()
        self.draw_network()

    def _refresh_work_table(self) -> None:
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
        self.code_text.configure(state="normal")
        self.code_text.tag_remove("active", "1.0", "end")
        if step is not None:
            # Pseudocode starts at text line 3.
            line = 3 + step.code_line
            self.code_text.tag_add("active", f"{line}.0", f"{line}.end")
        self.code_text.configure(state="disabled")

    def _refresh_route_table(self) -> None:
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
        current = sum(self.engine.table_status(name) == "current" for name in self.network.routers)
        activity = "SPF playing" if self.spf_auto else "packet playing" if self.packet_auto else "ready / paused"
        self.status_text.set(f"Topology revision {self.network.revision}  |  Current SPF tables {current}/6  |  "
                             f"Completed SPF runs {self.engine.spf_runs}  |  {activity}  |  "
                             "Simulation only: no real packets, no OSPF flooding; one next hop per prefix")

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
            length = math.hypot(x2 - x1, y2 - y1)
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
            canvas.create_text(x, y, text=name, fill=text, font=("Segoe UI", 17, "bold"), tags=(tag,))
            if not self.compact:
                canvas.create_text(x, y + 43, text=f"{router.address}/32", fill=self.MUTED,
                                   font=("Segoe UI", 9), tags=(tag,))
            if step and self.packet is None:
                dist = metric(step.distances[name])
                label = f"d={dist}" + (" [root]" if name == step.source else "")
                canvas.create_text(x, y - (35 if self.compact else 42), text=label,
                                   fill=self.GREEN if name in step.settled else self.AMBER,
                                   font=("Segoe UI", 10, "bold"))
            canvas.tag_bind(tag, "<Button-1>", lambda event, selected=name: self.inspect_router(selected))
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

    def reset_network(self) -> None:
        self._stop_everything()
        self.network = make_default_network()
        self.engine = RoutingEngine(self.network)
        self.step = None
        self.spf_root.set("A")
        self.inspector.set("A")
        self.packet_source.set("A")
        self.packet_target.set("F")
        self.destination_ip.set("10.0.0.6")
        self.ttl_value.set("16")
        self.select_link(("D", "E"))
        self._clear_packet_display()
        self.spf_note.set("Network reset. Press New SPF or Step SPF to begin at router A.")
        self._log("RESET: restored default topology; all routers have local routes only.")
        self._refresh_all()

    def close(self) -> None:
        self._stop_everything()
        self.root.destroy()


GUI_GUIDE = """A FIRST WALKTHROUGH

1. Keep root A. Click New SPF, then Step SPF repeatedly.

Watch the smallest tentative distance become FINAL. An amber link is being inspected. The explanation shows the actual comparison, for example 2 + 3 < 7. Finalized routing entries appear in the STAGING table. They become INSTALLED when the calculation finishes.

2. Click Build all now, or Animate all.

Each of the six routers runs Dijkstra with ITSELF as root. Click a router or open All tables to compare next hops. Computing a table only at A is not enough for intermediate routers to forward packets.

3. Keep source A and target F. Click New packet, then Next hop or Play packet.

The packet's destination stays 10.0.0.6. At every router, the matching /32 entry is selected in the installed table. The trace shows the next hop and TTL. No new Dijkstra calculation is made during forwarding.

The default path is A -> C -> B -> D -> E -> F.
Its cost is 2 + 3 + 2 + 1 + 2 = 10.
A -> C -> E -> F has fewer hops, but costs 11.

A LINK FAILURE

Build all tables. Select D-E, untick Link up, and Apply change. Send another packet BEFORE recalculating: the old tables send it toward the failed link, so it drops at D.

Now Build all now and send again. The new path is A -> C -> E -> F, cost 11.

OTHER EXPERIMENTS

- Set A-C cost to 9: after rebuilding, A -> F uses A -> B -> D -> E -> F, cost 12.
- Disable BOTH D-F and E-F, then rebuild: F is unreachable from A.
- Use TTL 3: the packet expires before it reaches F.
- Enter 10.99.0.1 as Dest. IP: no matching route exists.
- Compare Previous with Next hop. They are different concepts.
- Watch Completed SPF runs stay unchanged during packet forwarding.

MODEL BOUNDARIES

All routers share a topology snapshot. The model omits OSPF neighbors, LSA flooding, areas, ECMP, interface addresses, Ethernet, ARP, checksums and ICMP replies. Link costs are symmetric positive integers, not measured latency. Animation time is unrelated to cost.

Destinations are router loopbacks (/32). TTL is decremented on forwarding, but not on local delivery. The model uses one installed table as a simplified RIB/FIB; it does not model separate hardware FIB programming.

Tables stay installed after link edits so you can observe stale routes. Recalculation is manual; the animation is not a realistic distributed convergence timing simulation.

Windows: py -3 dijkstra_routing_demo.py
Other systems: python3 dijkstra_routing_demo.py

COPYRIGHT AND LICENSE

Copyright 2026 Ib Helmer Nielsen.
Licensed under the Apache License, Version 2.0.
See LICENSE and NOTICE in the repository.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
