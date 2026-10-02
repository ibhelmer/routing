# Dijkstra Routing Lab

**Copyright 2026 Ib Helmer Nielsen** · [Apache License 2.0](LICENSE)

Repository: [ibhelmer/routing](https://github.com/ibhelmer/routing)

**Version 1.1.0:** add routers and links interactively; drag nodes to arrange the graph.

An interactive Python teaching example that makes two different activities visible:

**Control plane:** calculate least-cost paths, derive next hops, and install each router's routing table.

**Data plane:** forward a simulated IP packet using a fresh lookup in the current router's installed table at every hop.

The forwarding code does **not** run Dijkstra and does **not** consume a precomputed end-to-end path. The demonstration is self-contained; it sends no real packets and changes no operating-system network settings.

## Start the application

The application requires **Python 3.10 or newer**, Tkinter/Tcl-Tk, and a graphical desktop. No third-party Python packages, `pip install`, administrator rights, or Internet connection are required to run it.

### Windows

Clone the repository (or download and extract its ZIP), then double-click `run_demo.bat`, or open a terminal in the extracted folder:

```powershell
py -3 dijkstra_routing_demo.py
```

When your Python command is `python`, use:

```powershell
python dijkstra_routing_demo.py
```

Check Tkinter separately with `python -m tkinter`. It should open a small test window. If Tkinter is missing, modify/reinstall your Python distribution with Tcl/Tk support. Do not try `pip install tkinter`.

### Linux / macOS

```bash
python3 dijkstra_routing_demo.py
```

For a Debian/Ubuntu system Python that lacks Tkinter:

```bash
sudo apt install python3-tk
python3 -m tkinter
```

The application needs a desktop display; it is not a browser application or a MicroPython program. A 1440 x 960 application window is comfortable for teaching. On smaller screens the packet trace becomes shorter and the Live view can be scrolled. The divider between the network and the tables is draggable.

### Headless example

The model, console output, and unit tests do not need a graphical display:

```bash
python dijkstra_routing_demo.py --print-tables
python -m unittest -v
```

## First classroom walkthrough

### 1. Calculate a routing table at A

Keep **Root = A** and click **New SPF**. Click **Step SPF** repeatedly, or **Play SPF** for automatic playback.

The working table shows `Cost`, `Previous`, `Next hop`, and `State`. `inf` means that no finite distance has been found. A node is tentative until the algorithm selects its smallest distance and marks it **FINAL**. The explanatory line displays the actual arithmetic for each comparison.

Observe B: the initial candidate path A -> B costs 7. After visiting C, the algorithm finds 2 + 3 = 5 and changes B's predecessor to C.

The lower routing table fills with **staged** entries as destinations become final. They are deliberately not used by packets yet. The entire table is installed when this SPF calculation finishes. Previously installed entries remain separate from the work in progress.

**Finish router** skips the remaining animation for the selected root. **Play SPF** also pauses and resumes playback. Pausing **Animate all** preserves the remaining router queue.

### 2. Calculate every router's table

Click **Animate all** to watch the six independent calculations, or **Build all now** to calculate them immediately.

Each router uses **itself** as the root. Calculating a table only at A does not give C, B, D, or E a routing table. Open **All tables**, select an **Inspect router**, or click a router on the map to compare tables.

For the default graph, A's installed table is:

| Destination | Router | Next hop | Cost | Simulated interface |
|---|---|---|---:|---|
| 10.0.0.1/32 | A | local | 0 | loopback |
| 10.0.0.2/32 | B | C | 5 | to-C |
| 10.0.0.3/32 | C | C | 2 | to-C |
| 10.0.0.4/32 | D | C | 7 | to-C |
| 10.0.0.5/32 | E | C | 8 | to-C |
| 10.0.0.6/32 | F | C | 10 | to-C |

A next hop is the **first neighbor after the root**, not the destination's predecessor. For F, A's predecessor chain ends `... E -> F`, but A's next hop is **C**, not E.

### 3. Forward a packet

Keep **Source = A**, **Target = F**, **Dest. IP = 10.0.0.6**, and **TTL = 16**.

Click **New packet**, then **Next hop** or **Play packet**. Each forwarding decision highlights the matching entry in the current router's installed table. The graph animates the packet over the selected link. The trace records the current router, matched prefix, next hop, link cost, and TTL transition.

The destination address remains `10.0.0.6` at every hop:

| Current router | Matched prefix | Local forwarding decision | TTL |
|---|---|---|---|
| A | 10.0.0.6/32 | Forward to C | 16 -> 15 |
| C | 10.0.0.6/32 | Forward to B | 15 -> 14 |
| B | 10.0.0.6/32 | Forward to D | 14 -> 13 |
| D | 10.0.0.6/32 | Forward to E | 13 -> 12 |
| E | 10.0.0.6/32 | Forward to F | 12 -> 11 |
| F | 10.0.0.6/32 | Deliver to local loopback | 11 -> 11 |

The resulting path is:

```text
A --2--> C --3--> B --2--> D --1--> E --2--> F

Total cost: 2 + 3 + 2 + 1 + 2 = 10
Router-to-router hops: 5
```

The alternative A -> C -> E -> F uses only three hops but costs 2 + 7 + 2 = 11. The example minimizes the sum of link costs, not the hop count.

Watch **Completed SPF runs** in the status bar: its value does not increase as the packet travels. A packet with TTL 6 can traverse the five links and arrive at F with TTL 1. Local loopback delivery does not consume another hop.

## Add routers and links

Click **Add router** at the top of the window, or **double-click empty space on the graph** to place a new router there.

The dialog suggests the next unused name and IPv4 address, initially **G** and **10.0.0.7**. Enter a unique name (1-12 letters, digits or underscores, starting with a letter) and a unique IPv4 loopback address **without `/32`**. Names are case-sensitive. Multicast, unspecified and limited-broadcast addresses are rejected.

**Connect to (optional)** can add the first connection at the same time. Select an existing router and enter a positive integer **First link cost**. Keep **(none)** to create an isolated router; its unused cost field is ignored. Cancel and invalid input leave the topology unchanged. The application rejects duplicate names/IPs before creating anything.

To add another connection, click **Add link**, select two different routers, and enter its cost. Links are bidirectional. Duplicate links, self-links and non-positive costs are rejected. Change an existing link using the original **LINK EDITOR** instead.

New routers immediately appear in **Root**, **Inspect router**, **Source** and **Target**. **Target** switches to the newly added router and fills in its destination IP. Each new router initially has only its local route; existing installed tables are retained and marked **STALE**. Run **Build all now** or **Animate all** to install updated tables before sending packets to the new destination.

### Example: add G behind F

1. Click **Add router** and keep **G**, **10.0.0.7**.
2. Set **Connect to (optional) = F**, **First link cost = 3**, then click **Add router**.
3. Click **Build all now**. The status bar now shows **7/7** current tables.
4. Set **Source = A**, **Target = G**, then **New packet** and **Play packet**.

```text
A --2--> C --3--> B --2--> D --1--> E --2--> F --3--> G
Total cost: 13; router-to-router hops: 6
```

Adding G without a connection is also valid: it stays unreachable from other routers until a link is added and tables are recalculated.

### Arrange the graph and inspect larger tables

**Drag a router** with the left mouse button to move it. A drawing move does not change link costs, invalidate tables, or run Dijkstra. Link arrows follow the new positions, including during packet animation. A double-click on an existing router or link does not create another node.

The working and routing tables have scrollbars; the forwarding lookup scrolls the selected route into view. Router counts, selector contents and the all-router SPF queue are dynamic rather than fixed at six. Suggested names continue with R1, R2, and so on after Z. A crowded graph may need manual rearrangement or a larger window; automatic graph layout and zoom are not implemented.

**Session storage:** additions and positions are kept in memory. **Export tables** saves a JSON record of all routers, links, installed routes, versions and positions, but there is currently no topology-import command. **Reset network** asks for confirmation when custom routers exist, then restores the original A-F example. Closing the program also discards the edited topology.

### Use the editor model from Python

```python
from dijkstra_routing_demo import Router, RoutingEngine, make_default_network, trace_packet

engine = RoutingEngine(make_default_network())
engine.add_router(Router("G", "10.0.0.7", 0.5, 0.9), connect_to="F", cost=3)
# Optional additional connection: engine.network.add_link("A", "G", 20)
engine.calculate_all()
packet, _ = trace_packet(engine, "A", "10.0.0.7")
assert packet.path == ["A", "C", "B", "D", "E", "F", "G"]
assert packet.total_cost == 13
```

Use **`engine.add_router(...)`** when a routing engine already exists: this registers the new local route as well as the node. `Network.add_router(...)` is the lower-level topology operation for use before constructing an engine. A topology edit stops current GUI animations and abandons incomplete SPF work; simply opening and cancelling a dialog pauses playback without changing the graph or installed routes.

## Link editor and failure experiments

Click a link cost to select that link in the editor. Change its cost or **Link up** state and press **Apply change**. Right-clicking a link toggles it immediately; Control-click also works. Edits stop the current animation but retain installed routing tables. Those tables are marked **STALE** until recalculated.

### Failed D-E link, before and after convergence

Start with the default topology and build all tables. Disable D-E, then send A -> F **before** recalculating. The old entries send the packet A -> C -> B -> D. At D it is dropped because its installed next hop E uses a failed link.

Now click **Build all now** and send again. The new route is A -> C -> E -> F, cost **11**.

### Additional exercises

| Experiment | Expected result |
|---|---|
| Reset; change A-C cost from 2 to 9; build all | A -> B -> D -> E -> F, cost 12 |
| Reset; disable D-F and E-F; build all | F is unreachable from A; no route to F is installed at A |
| Reset; build all; use TTL 3 for A -> F | Packet reaches B and is dropped before the next forwarding hop |
| Enter destination 10.99.0.1 | No matching route; packet is dropped |
| Reset; finish SPF only at A; send A -> F | A forwards to C; C drops because it has not learned a route to F |
| Compare A and C's entries for F | A uses next hop C; C uses next hop B |

## Other interface features

**Algorithm** displays annotated pseudocode and highlights the current SPF operation. **Event log** records calculations, topology changes, and forwarding decisions. **Guide** provides an in-application walkthrough. **Export tables** writes the current topology and installed tables as JSON, including topology revisions and stale/current status. It does not export staged entries as installed routes. **Reset network** restores the original link costs and removes calculated routes.

Link cost is not animation duration. Use the **Delay** slider to slow down or speed up the presentation. On a short display the Live view has its own vertical scrollbar; the packet trace also supports normal Treeview scrolling.

## Code map

All application code is in `dijkstra_routing_demo.py` so that a single file is sufficient to run the example.

| Code | Responsibility |
|---|---|
| `Network`, `Router`, `Link` | Topology, loopbacks, active links, positive integer costs |
| `dijkstra_steps()` | Heap-based Dijkstra with independent snapshots after each operation |
| `DijkstraStep.path_to()` | Explain the predecessor chain during route calculation |
| `routes_from_step()` | Translate finalized paths into destination/next-hop entries |
| `RoutingEngine.install()` | Atomically replace a router's installed table |
| `RoutingEngine.lookup()` | Longest-prefix matching in one router's installed table |
| `forward_one_hop()` | One table lookup and one forwarding/delivery/drop decision |
| `trace_packet()` | Headless end-to-end trace using repeated one-hop decisions |
| `RoutingDemo` | Tkinter interface and non-blocking `after()` animations |

For example, use the same model without the GUI:

```python
from dijkstra_routing_demo import (
    RoutingEngine,
    make_default_network,
    trace_packet,
)

engine = RoutingEngine(make_default_network())
engine.calculate_all()
packet, decisions = trace_packet(engine, "A", "10.0.0.6", ttl=16)

for decision in decisions:
    print(decision.message)

print(" -> ".join(packet.path))
print("Total cost:", packet.total_cost)
```

## Deliberate simplifications

This is **not an OSPF implementation**. The demonstration starts with a shared, complete topology snapshot and omits neighbor discovery, LSA flooding, areas, authentication, timers, and realistic distributed convergence timing. Serial animation of six calculations is a presentation choice, not how routers coordinate their SPF execution.

Destinations are the routers' **IPv4 loopbacks advertised as /32 prefixes**, rather than attached client LANs. Next hops are neighbor router names; `to-C` is a simulated interface name, not a real NIC or IP next-hop address. The model uses one installed table as a simplified RIB/FIB and does not simulate hardware FIB programming.

Link costs are symmetric positive integers. Dijkstra can handle zero-weight edges, but this network editor deliberately requires positive costs. Equal-cost alternatives keep the first discovered route using deterministic processing order. **ECMP is not implemented.**

TTL decreases on forwarding and not on local delivery. Drops are logged, but no ICMP error packet is generated. Ethernet, ARP, checksums, queues, bandwidth, latency, congestion, TCP, and application payloads are outside the model. The GUI runs on desktop CPython, not MicroPython.

## Verification

The test suite now contains **52 tests: 42 model tests and 10 opt-in GUI tests**. All 52 passed during the Linux/Xvfb validation of version 1.1.0.

`test_dijkstra_routing_demo.py` preserves the original 27 tests, including 40 random graphs checked against an independent Bellman-Ford reference and 1,440 source/destination packet traces. `test_topology_editor.py` adds 15 model tests and 10 GUI checks. Its larger-graph reference test checks another 1,125 source/destination pairs across five 15-router graphs built with the editing API.

Normal, display-independent test run (42 pass; 10 GUI checks are deliberately skipped):

```bash
python -m unittest -v
```

To include the real Tk window checks, run on a graphical desktop:

```powershell
# Windows PowerShell
$env:RUN_GUI_TESTS = "1"
python -m unittest -v
```

```bash
# Linux / macOS with a graphical display
RUN_GUI_TESTS=1 python -m unittest -v
# A headless Linux machine with Xvfb installed
RUN_GUI_TESTS=1 xvfb-run -a python -m unittest -v
```

The new GUI checks cover both editor forms, cancelled/invalid edits, dynamic dropdowns, isolated nodes, node dragging, interruption of animations, reset confirmation, larger-table scrolling, overlapping node positions, and an animated A-to-G delivery without further SPF runs.

See `VALIDATION.md` for the actual environment and limitations. Native Windows and macOS execution were not available for this update.

## Primary references

The implementation is an original teaching example based on the principles below, not code copied from these documents.

- [RFC 2328, section 16.1: calculating the shortest-path tree](https://www.rfc-editor.org/rfc/rfc2328.html#section-16.1).
- [RFC 2328, section 16.1.1: next-hop calculation](https://www.rfc-editor.org/rfc/rfc2328.html#section-16.1.1).
- [RFC 1812: IPv4 forwarding, longest-prefix matching, and TTL](https://www.rfc-editor.org/info/rfc1812/).
- [Python Tkinter documentation](https://docs.python.org/3/library/tkinter.html).
- [Ubuntu python3-tk package](https://packages.ubuntu.com/questing/python3-tk) and [Debian python3-tk package](https://packages.debian.org/sid/python3-tk).


## Repository contents

| File | Purpose |
|---|---|
| `dijkstra_routing_demo.py` | Complete GUI and independently usable routing model |
| `test_dijkstra_routing_demo.py` | Original 27 model tests, including randomized reference comparisons |
| `test_topology_editor.py` | 15 additional model tests and 10 opt-in graphical tests |
| `run_demo.bat` | Windows launcher |
| `README.md` | Installation, classroom walkthrough, experiments, and design notes |
| `VALIDATION.md` | Validation environment, performed checks, and limitations |
| `LICENSE` | Full Apache License 2.0 text |
| `NOTICE` | Project attribution and copyright notice |

## Copyright and license

Copyright 2026 Ib Helmer Nielsen.

The source code and documentation are licensed under the
[Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for project
attribution. Source files also carry the `SPDX-License-Identifier: Apache-2.0`
identifier.
