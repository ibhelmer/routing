# Validation record

Copyright 2026 Ib Helmer Nielsen. Licensed under Apache-2.0.

## Version 1.1.0 - dynamic topology editor

Validated on 2 October 2026 using CPython 3.13.5, Linux, Tkinter/Tcl-Tk and an Xvfb display. The application and its real dialogs were exercised; screenshots are captures of the running application, not mockups. Native Windows and macOS execution and older Python versions were not available. The source targets Python 3.10+.

The previous repository's source and original test file were reconstructed from the conversation distribution and checked against their exact Git blob SHA values before editing:

- `dijkstra_routing_demo.py`: `10b7479f0084d2b37d88337a493d544a9b257767`.
- `test_dijkstra_routing_demo.py`: `92b5e064ff676043df7eae9108b261abafbd4787`.

### Test results

```text
DISPLAY=:99 RUN_GUI_TESTS=1 python -m unittest -v
Ran 52 tests
OK
```

Without RUN_GUI_TESTS, 42 model tests pass and the 10 GUI checks are deliberately skipped. This is not a GUI validation on the user's operating system.

The unchanged 27 original model tests cover Dijkstra snapshots and route construction, hop-by-hop lookups, longest-prefix matching, TTL, link failures, stale tables, convergence, invalid input and forwarding without SPF. The original randomized comparison covers 40 graphs and 1,440 packet traces.

The 15 added model tests cover:

- New local routes, retained stale tables, isolated nodes, and routes after connecting and rebuilding.
- Adding a router with its first link as one atomic revision.
- Shortcuts affecting forwarding only after table installation.
- Rejection of duplicate names/IPs, invalid names/addresses/coordinates, unknown endpoints, self-links, duplicate links and invalid costs without partial edits.
- Moving a drawing without invalidating tables or interrupting a valid SPF snapshot.
- Unique name/address suggestions, including after Z.
- Exported positions and newly added topology elements.
- Five 15-router graphs built through the editing API, checked against independent Bellman-Ford distances, with 1,125 additional source/destination packet traces.

The 10 opt-in GUI tests cover:

- Adding G, refreshing all four router selectors and the link selector, updating the destination IP and displaying 7/7 tables.
- Connecting an isolated router through the Add link form.
- Invalid/cancelled router input and duplicate links leaving the graph unchanged.
- Adding at a canvas position and dragging with generated Tk mouse events; no route invalidation on movement.
- Stopping pending SPF/packet callbacks when the topology changes.
- Reset confirmation, cancellation and cleanup of dynamic selector entries.
- 18-router routing-table scrolling with the lookup destination selected and visible.
- Successful animated delivery A-C-B-D-E-F-G, cost 13, with seven completed SPF runs and no SPF during forwarding.
- Overlapping router positions without a division-by-zero error in the packet arrow.

### Additional checks and boundaries

`python dijkstra_routing_demo.py --print-tables` still produces the original six-router example and an A-to-F trace of cost 10. Syntax compilation and the complete test suite were rerun after changes.

Layout was inspected at 1440x960 and 1180x740. The tables scroll, and the graph remains editable on the compact layout. Dense graphs may require dragging nodes apart or enlarging the window. There is no automatic layout, zoom, node removal or topology import.

Topology edits and positions are session-local. JSON export records them, but closing or resetting the application does not persist an editable project for reopening. Reset asks for confirmation when additional routers are present.

The demonstration remains a teaching simulation with shared topology, symmetric positive link costs, loopback /32 destinations and a single next hop per prefix. It does not implement OSPF flooding, ECMP, Ethernet or real packet transmission.
