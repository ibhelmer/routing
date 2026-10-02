# Dijkstra Routing Lab

**Copyright 2026 Ib Helmer Nielsen** · [Apache License 2.0](LICENSE)

Repository: [ibhelmer/routing](https://github.com/ibhelmer/routing)

**Version 1.2.0:** save and load editable graphs, including node positions; keep multiple classroom topologies as JSON files. Adds unsaved-change protection and imports of earlier table exports.

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

**Persistence:** use **Save graph** and **Load graph** to keep editable topologies between sessions. The saved graph includes node positions and link up/down states. See the next section for the workflow, file format and compatibility with earlier table exports.

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

## Save and load graphs

### Save a classroom topology

Create or move routers, add connections, and adjust link costs or up/down states. Click **Save graph**, or press **Ctrl+S**. The first save opens a file chooser with the suggested filename `network.graph.json`. Select a folder and filename, such as `classroom_network.graph.json`.

Further saves update the same file. **File > Save graph as...** (**Ctrl+Shift+S**) writes a separate copy and makes it the current file. Use this to keep alternative exercises without overwriting the original. All files are ordinary UTF-8 JSON; the application uses no database, cloud account or additional package.

The graph file stores:

| Saved property | Details |
|---|---|
| Routers | Unique name and IPv4 loopback address |
| Layout | Each router's normalized `x` and `y` coordinates |
| Links | Both endpoints, the positive integer cost, and `enabled` (`true` or `false`) |
| File identity | `format` marker and integer schema `version` |

**Not saved:** installed or staged routing tables, SPF progress, topology revision history, packet traces, TTL, animation progress, selection state and event logs. Save graph is a topology document, not a suspended simulation session. Coordinates are relative to the drawing area, so the layout adapts to another window size.

### Reopen a graph

Click **Load graph**, or press **Ctrl+O**, and select the saved JSON file. Loading **replaces** the current graph; it does not merge networks. Nodes, IP addresses, positions, connections, costs and failed links are restored together. Selectors and the link editor are rebuilt even when the file uses no A-F router names or contains a single isolated router.

Each loaded router initially knows **only its local /32 route**. Previous packets and pending SPF callbacks are cleared. Click **Build all now** to calculate all routing tables, or **Animate all** to watch the calculation, and then send a new packet.

An example is included at [`examples/seven_router.graph.json`](examples/seven_router.graph.json). Load it, build all tables, then send **A -> G**. The route is **A-C-B-D-E-F-G**, cost **13**.

### Unsaved changes and failures

A **`*` in the window title** means that topology or drawing positions have changed since the last save or load. Running Dijkstra or forwarding a packet does not mark the graph as modified. Loading, resetting, or closing with unsaved changes prompts:

- **Yes:** save, then continue. Cancelling or failing that save cancels the pending operation.
- **No:** discard those edits and continue.
- **Cancel:** keep the current graph and return to it.

File operations pause automatic playback. Cancelling a file dialog or rejecting an invalid file keeps the current graph and installed tables. Playback remains paused and can be resumed. A loaded file is fully parsed and validated before it replaces the current network.

Saving validates and serializes the graph, writes a temporary file in the same directory, closes it, and then replaces the destination with `os.replace`. Failed writes/replacements do not intentionally truncate an existing graph. This is not a backup system or a guarantee against power loss on every filesystem. Keep separate copies of important classroom scenarios.

### Earlier Export tables files

**Load graph** also accepts JSON produced by the earlier **Export tables** button:

- v1.1 exports restore the recorded router positions.
- Older exports without positions use a deterministic circular layout.
- Exported routing tables and revision counters are ignored; routes are rebuilt from the imported graph.

**Export tables** remains a separate inspection report. Exporting does **not** clear the graph's unsaved marker. Saving after opening an older export rewrites the selected file in the new graph-only format; use **Save graph as...** to preserve the original report.

### JSON schema and Python API

The native format uses the marker `dijkstra-routing-lab.graph` and schema version `1`. Each router record requires `name`, `address`, `x`, `y`; each link requires `a`, `b`, `cost`, `enabled`. A compact example:

```json
{
  "format": "dijkstra-routing-lab.graph",
  "version": 1,
  "routers": [
    {"name": "R1", "address": "192.0.2.1", "x": 0.2, "y": 0.5},
    {"name": "R2", "address": "192.0.2.2", "x": 0.8, "y": 0.5}
  ],
  "links": [
    {"a": "R1", "b": "R2", "cost": 5, "enabled": true}
  ]
}
```

Import enforces the same router name/address/position and topology constraints as the editor, including unique names/IPs, known endpoints, no self-links and no parallel links. The file reader additionally requires actual JSON booleans, rejects duplicate JSON fields, non-finite values in graph coordinates, and unknown format versions. Input is bounded to **2 MiB**, **256 routers**, **16,384 links** and link costs from **1 to 1,000,000,000**. These are persistence limits, not a performance guarantee for dense classroom graphs. Graph files are parsed as data; no `pickle`, `eval` or imported code is used.

```python
from dijkstra_routing_demo import (
    RoutingEngine, load_graph_file, make_default_network, save_graph_file,
)

save_graph_file(make_default_network(), "my_network.graph.json")
network = load_graph_file("my_network.graph.json")
engine = RoutingEngine(network)
engine.calculate_all()  # Rebuild, rather than trust saved forwarding state.
```

`graph_to_data(network)` and `graph_from_data(data)` expose serialization and validation without filesystem access. `load_graph_file` returns a fresh `Network`; attach it to a new `RoutingEngine`. Replacing only `engine.network` would leave old table state behind and is not supported.

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
| `graph_to_data()`, `graph_from_data()` | Versioned topology serialization and validation; legacy export migration |
| `save_graph_file()`, `load_graph_file()` | Bounded JSON file I/O and temporary-file replacement |
| `RoutingDemo` | Tkinter interface, file actions, unsaved-change protection, and non-blocking `after()` animations |

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

There are **86 tests**: **63 model/storage tests** and **23 opt-in Tk GUI tests**. The original 27 routing-model tests are unchanged; the topology-editor tests now exercise the new Save / Discard / Cancel reset prompt. `test_graph_storage.py` adds 21 storage tests and 13 GUI tests.

```bash
# No graphical display required: 63 pass, 23 GUI checks are skipped.
python -m unittest -v

# With a working graphical desktop:
RUN_GUI_TESTS=1 python -m unittest -v

# A headless Linux machine with Xvfb installed:
RUN_GUI_TESTS=1 xvfb-run -a python -m unittest -v
```

On PowerShell, set `$env:RUN_GUI_TESTS = "1"` before invoking unittest to opt in to GUI tests. Native file-chooser return values and confirmation answers are mocked for repeatability; the Tk application, widgets, callbacks and routing model are real.

New checks cover full save/load round-trips, 10 randomized 10-router networks and 1,000 before/after packet-route comparisons, malformed JSON, strict field validation, legacy imports, failed save cleanup, single-node/zero-link loading, state reset, pending-animation cancellation, Save As, dirty tracking, and cancellation/failure before replacing a graph. Loading the current file after saving pending edits is checked to keep disk and memory consistent.

See `VALIDATION.md` for the actual environment and limits of verification. Native Windows and macOS execution were not available for this update.

## Primary references

The implementation is an original teaching example based on the principles below, not code copied from these documents.

- [RFC 2328, section 16.1: calculating the shortest-path tree](https://www.rfc-editor.org/rfc/rfc2328.html#section-16.1).
- [RFC 2328, section 16.1.1: next-hop calculation](https://www.rfc-editor.org/rfc/rfc2328.html#section-16.1.1).
- [RFC 1812: IPv4 forwarding, longest-prefix matching, and TTL](https://www.rfc-editor.org/info/rfc1812/).
- [Python Tkinter documentation](https://docs.python.org/3/library/tkinter.html).
- [Python JSON documentation](https://docs.python.org/3/library/json.html), [temporary files](https://docs.python.org/3/library/tempfile.html), and [`os.replace`](https://docs.python.org/3/library/os.html#os.replace).
- [Ubuntu python3-tk package](https://packages.ubuntu.com/questing/python3-tk) and [Debian python3-tk package](https://packages.debian.org/sid/python3-tk).


## Repository contents

| File | Purpose |
|---|---|
| `dijkstra_routing_demo.py` | Complete GUI and independently usable routing model |
| `test_dijkstra_routing_demo.py` | Original 27 model tests, including randomized reference comparisons |
| `test_topology_editor.py` | 15 additional model tests and 10 opt-in graphical tests |
| `test_graph_storage.py` | 21 storage/model tests and 13 opt-in graphical tests |
| `examples/seven_router.graph.json` | Loadable example with G connected to F at cost 3 |
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
