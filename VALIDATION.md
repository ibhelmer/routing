# Validation record

Copyright 2026 Ib Helmer Nielsen. Licensed under Apache-2.0.

## Version 1.3.0 - About dialog, IHN icon and UCN branding

Validated on 2 October 2026 with CPython 3.13.5, Tkinter/Tk 8.6 on Linux and an
Xvfb display at 1680 x 1050. The v1.2.0 archive's application was checked against
GitHub commit `dcc588b9b93793f12a749eb0a9bd114787827552` before editing:
application blob `d5c3faa6468da5b4085ea563838a7a25cfdc6432`.

```text
DISPLAY=:99 RUN_GUI_TESTS=1 python -m unittest -v
Ran 106 tests
OK
```

Without GUI opt-in, **68 tests pass and 38 GUI tests are skipped**. The existing
86 tests and routing/storage behavior are preserved. All Python files parse
with Python 3.10's grammar. `--version` works without a display, and the
`--print-tables` example still delivers A-C-B-D-E-F at cost 10.

### New checks

Five non-GUI tests check metadata and educational purpose, PNG dimensions,
exact original IHN/UCN source hashes, the four ICO sizes and the version command.
Fifteen real-Tk tests cover both header logos, About's content, the About button,
Help menu, F1/Escape, singleton/modal handling, browser launch and failure,
clipboard success/failure, topology/route/packet/SPF preservation, file/editor
shortcuts while a modal is open, a compact layout, missing/corrupt logo files,
and launch from another working directory.

Browser launch is mocked: tests do not open a real external browser. Clipboard
copy uses the Xvfb clipboard; the clipboard failure path is injected. Existing
file choosers and confirmations remain mocked in the persistence tests.
The IHN/UCN assets are loaded by real Tk PhotoImage objects.

### Visual review

Actual running windows were captured and inspected at **1440 x 960** and
**1180 x 740**. Both logos, the About button, topology controls and packet
controls remain visible. At the smaller size the Live view and tables scroll,
router IP captions are omitted, and the packet trace is shorter. The About
window is scrollable; its repository/copyright/actions stay outside the scroll
region. A 600 x 480 About layout is checked by the GUI tests.

### Limits

Native Windows/macOS execution, Windows taskbar grouping, Explorer shortcuts,
and a real browser launch were **not tested**. Tk accepted the icon request on
Linux, but Xvfb has no normal desktop window manager: no claim is made about a
rendered native title-bar/taskbar icon there. Python versions earlier than
3.13.5 were not executed. Screenshots are real application captures, not mockups.

The UCN source SVG and IHN source PNG are byte-identical to the user's existing
project assets. PNG/ICO derivatives were prepared ahead of time; no Pillow or
CairoSVG dependency was added to the application or tests. Trademark provenance
is recorded separately from the software license in `assets/README.md`.

## Version 1.2.0 - saved and loadable graphs

Validated on 2 October 2026 using CPython 3.13.5 on Linux with Tkinter/Tcl-Tk and an Xvfb display. The v1.1.0 source archive was checked against the current GitHub tree at commit `b9d8a57d7593e026eb9eb731125b9d6e7e8e355a` before editing; its application blob was `fb03bbb5ef3627962f93de6a46872d875dabcf40`.

```text
DISPLAY=:99 RUN_GUI_TESTS=1 python -m unittest -v
Ran 86 tests
OK
```

Without `RUN_GUI_TESTS=1`, 63 tests pass and 23 opt-in GUI tests are skipped. The original 27 routing tests remain unchanged. The prior 25 topology tests still pass; their reset and cleanup confirmations were adapted to Save / Discard / Cancel.

### Added storage checks (21 tests)

- Full round-trip of custom routers, IPv4 addresses, fractional coordinates, changed costs and disabled links.
- Fresh local-only routing engines after load, followed by the expected A-to-G path of cost 13 after recalculation.
- A one-router graph without links.
- Earlier Export tables formats, with and without recorded positions; exported route state is ignored.
- Malformed JSON/UTF-8, duplicate JSON keys, unknown schema versions, incorrect field types, non-finite or out-of-range coordinates, duplicate names/IPs/links and invalid endpoints.
- Input size and router-count bounds.
- Successful repeated saves and temporary-file cleanup.
- Injected fsync/replace failures leaving an existing destination unchanged.
- Missing directories/files and validation failures.
- Ten seeded ten-router graph round-trips, matching tables after recalculation and 1,000 source/destination packet comparisons before and after persistence.

### Added Tk checks (13 tests)

- Real application save/load handlers, widget updates, restored positions and rebuilt routing state.
- Loading a graph with neither default router names nor links, then returning to the default graph.
- Invalid or cancelled loads preserving the current graph and routing tables.
- Cancel, failed save and cancelled save all aborting a pending replacement.
- Saving then reopening the same file retaining the newly saved content in memory.
- Dirty markers for node movement, but not SPF/packet actions.
- Save As preserving the original and selecting the new file.
- Loading cancelling old SPF, packet, frame and selection state.
- Save / Discard / Cancel for reset and exit.
- File shortcuts blocked while a router editor dialog is active.

Native file-chooser results and messagebox answers are mocked for deterministic automation. Tests use real Tk widgets and callback code. Native Windows/macOS dialogs and execution were not tested. Python versions earlier than 3.13.5 were not executed; syntax compatibility with Python 3.10 is checked separately.

### Manual layout and smoke checks

The running application was inspected at 1440x960 and 1180x740, including the Save graph / Load graph buttons, File menu, filename/dirty marker and a reloaded seven-router graph. Screenshots are actual captures, not mockups. The headless six-router demonstration still produces A-C-B-D-E-F, cost 10.

The graph format does not save installed tables, packet state or a suspended simulation. It stores topology and positions only. Power-loss behavior and network-filesystem atomicity were not tested. The application still does not implement OSPF flooding, ECMP, real network traffic, automatic layout, node removal or zoom.

## Historical version 1.1.0 record

The following record describes the previous version. Its session-only storage limitation is superseded by v1.2.0.

### Version 1.1.0 - dynamic topology editor

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
