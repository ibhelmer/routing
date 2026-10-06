# Validation record

Copyright 2026 Ib Helmer Nielsen. Licensed under Apache-2.0.

## Version 1.5.0 - delete routers and links

Validated on 6 October 2026 with CPython 3.13.5, Tkinter/Tk 8.6 on Linux, using
an Xvfb display at 1680 x 1050. The mounted v1.4.0 application was checked against
the connected GitHub repository at commit
`efa2867eb1c19a7d7c16f2fda11734a1d30d70bc`; its blob SHA was
`ed02aae50323905b7a5073990ba118699894c213`.

### Behavior and scope

Delete router is beside Inspect router in Live view. Delete link is beside
Apply change in LINK EDITOR. The Edit menu exposes both actions. Confirmation
identifies the selected item, explains the consequences and defaults to No.
Router deletion removes all incident links in one topology revision. Link
deletion keeps its endpoints. Deleting the last router returns an empty canvas.

RoutingEngine removal methods clear computed routes and old SPF snapshots;
surviving routers retain only their local /32 entries. No Dijkstra run is hidden
inside deletion. The completed-SPF counter keeps its historical value.
Confirmed deletion clears packet/trace state and cancels pending callbacks.
Cancelled deletion retains graph, tables, packet and unfinished SPF work,
with playback paused. Link up/down experiments continue to retain stale tables.

No saved file is changed by deletion itself. The filename association remains,
so a later explicit Save graph writes the edited topology. There is no Undo.
No manual deletion of an individual routing-table destination was added.

### Test results

```text
DISPLAY=:99 RUN_GUI_TESTS=1 python -m unittest -q
Ran 195 tests in 26.194s
OK

python -m unittest -q
Ran 195 tests in 0.907s
OK (skipped=92)
```

All prior test files are unchanged. There are 103 non-GUI and 92 GUI tests.
The new 15 model tests cover one-revision removal of incident links, reversed
link endpoints, invalid/repeated requests without partial mutations, route
invalidation without SPF, old-snapshot rejection, deleting the last router,
reusing names and IPs, isolated destinations, JSON round-trips and expected
alternative paths. Eight seeded deletion sequences compare every remaining
source and destination against independent Bellman-Ford distances after each
edit, continuing until the graph is empty.

The new 20 real-Tk checks cover both buttons and menu entries, the confirmation
wording/default, Yes/No behavior, selection versus a routing-table row, source/
root/target repair, preserved custom IP input, modal ownership, deleting during
SPF or packet animation, callbacks and trace cleanup, empty-state disabling,
recreating the first router, saved-file preservation until explicit Save,
save/load followed by forwarding, unsaved protection and compact layout.

`--version` reports 1.5.0. The unchanged console example delivers A-C-B-D-E-F
with cost 10 and remaining TTL 11. Every Python source parses with Python 3.10
grammar; older Python interpreters were not executed.

### Visual review and limitations

Actual running application windows were captured and visually inspected at
1440 x 960 and 1180 x 740. Delete link and Delete router are visible without
adding more buttons to the crowded topology toolbar. A separate capture shows
D and its attached links removed with the remaining local-only routing state.
Existing logos and other branding assets were not changed.

Tests exercise real Tk widgets and callback code, with confirmation answers
and file-chooser return values mocked. Native Windows/macOS execution, native
messageboxes/file dialogs and operating-system icon rendering were not tested.

## Version 1.4.0 - new empty topologies

Validated on 6 October 2026 using CPython 3.13.5, Tkinter/Tk 8.6 on Linux with
an Xvfb display at 1680 x 1050. The mounted v1.3.1 distribution was checked
against the connected repository at commit
`79914d3bf768f0064cfe5c1a6305e24f8cb3409d` before editing; application blob
`97bd4dc0f360a55fc29d492519195229f0b3ba02`. All 130 baseline tests passed first.

### Scope

Added New topology in the toolbar and File menu, with Ctrl+N. The action uses
Save / Discard / Cancel, installs an empty Network/RoutingEngine, detaches the
old filename and clears all SPF, packet, table and trace state. It never deletes
saved files. An explicitly requested save before clearing may update the current
file. Cancelled and failed saves abort the replacement.

The Network model now permits zero routers. Unknown link endpoints remain
invalid; empty graphs must have no links. The JSON format still uses version 1
and accepts zero-router native files and empty legacy Export tables reports.
Existing nonempty files remain compatible. Files containing zero routers
require this application version or later.

SPF and packet controls are disabled on an empty graph; Add link requires at
least two routers. Callbacks also guard against an empty graph. First-node
suggestions, drawing instructions, router selectors, table inspection,
status/TTL display and graph loading handle an empty workspace. The original
A-F startup example and Reset network behavior are preserved.

### Tests

```text
DISPLAY=:99 RUN_GUI_TESTS=1 python -m unittest -v
Ran 160 tests
OK

python -m unittest -q
Ran 160 tests
OK (skipped=72)
```

There are 88 non-GUI tests and 72 GUI tests. All prior test files are unchanged.
The 10 new model tests check empty Network/RoutingEngine state, centered first
suggestions, JSON and file round-trips, legacy empty reports, dangling-link
rejection, invalid first connections without partial edits, custom routing,
local delivery at a single node and rejection of unknown Dijkstra roots.

The 20 new Tk tests check button/menu/shortcut entry points, clearing old data,
Yes/No/Cancel and save errors, retaining existing files, detaching filenames,
disabled controls and safe callbacks, adding the first node by form or canvas,
connecting a custom network and forwarding a packet, empty saves/loads,
reset/load recovery, cancellation of pending animations, preserved SPF on
Cancel, modal ownership, repeated New and compact-screen visibility.

### Visual and platform limits

Actual running application windows were reviewed at 1440 x 960 and 1180 x 740,
both with an empty topology and with a custom graph created from scratch.
The screenshots are application captures, not mockups. All toolbar buttons,
including New topology, remain visible at the compact size. The original
`--print-tables` demonstration still delivers A-C-B-D-E-F at cost 10, and
`--version` reports 1.4.0. All Python files parse with Python 3.10 grammar.

Tests use real Tk widgets and handlers, but native file-chooser return values
and messagebox answers are mocked. Windows/macOS execution, native icons and
native file dialogs were not tested; Python versions before 3.13.5 were not
executed. No network packets are sent. Copyright, licensing and branding
assets remain unchanged.

## Version 1.3.1 - non-TTL drop diagnostics and packet setup

Validated on 2 October 2026 with CPython 3.13.5, Linux, Tkinter/Tk 8.6 and Xvfb.
The mounted v1.3.0 archive was checked against the connected repository's current
main at commit `49ac4d6ca18dec3e4ed8ee4bcc31b1afbbbdf7d3` before editing. Its
application Git blob was `40d615e91e284e9286e0eb87d1ceb8f15811e57b`.

### Diagnosis and scope

The user's exact graph and drop message were not supplied. The following old
behavior was reproduced before editing:

| Setup | Outcome | Remaining TTL |
|---|---|---:|
| Default graph immediately after startup | No route at A | 16 |
| SPF finished only at A | A-C, then no route at C | 15 |
| SPF finished at all six routers | A-C-B-D-E-F delivered | 11 |
| Disable D-E, retain old tables | A-C-B-D, then failed link | 13 |
| Full tables, initial TTL 3 | A-C-B, TTL expiry | 0 |

All 106 previous tests passed before editing. These cases establish why a packet
may legitimately drop with TTL remaining; they do not establish the specific
cause of the user's report. No Dijkstra distance, next-hop selection, or TTL
forwarding rule was changed. The remedy is an explicit preflight choice and
unambiguous diagnostics, not silently suppressing real packet loss.

### Actual test results

```text
DISPLAY=:99 RUN_GUI_TESTS=1 python -m unittest -v
Ran 130 tests
OK

python -m unittest -q
Ran 130 tests
OK (skipped=52)
```

There are 78 non-GUI tests and 52 opt-in GUI tests. All previous test files remain
unchanged. The new 10 model tests cover startup and partial-SPF drops, all 36
default source/destination pairs without SPF during forwarding, stale no-route,
unknown/isolated destinations, link-down versus missing-next-hop diagnostics,
reconvergence, TTL 1 local delivery, initial TTL retention and usable stale routes.

The 14 new real-Tk tests cover Yes/No/Cancel preflight decisions, retaining old
packets and unfinished SPF, local/current-table cases without prompts, deliberate
stale-link failures, explicit rebuilding without re-enabling links, edited TTL
inputs versus in-flight TTL, save/load followed by setup, historical trace rows,
modal ownership, isolated destinations and compact-screen diagnostics.

Native prompt responses are mocked. Tests exercise actual Tk widgets and
callback code; no real packets are sent. Full-suite runtime was approximately
18 seconds in this environment. All Python sources are also checked using
Python 3.10 grammar parsing; older Python interpreters were not executed.

### Visual checks and limitations

The real running application was captured at 1440 x 960 and 1180 x 740 with the
partial-SPF drop at C. Initial TTL, live TTL 15, the NO_SPF explanation and selected
trace row remain visible. On short screens the packet trace shows one row and
can be scrolled; the supplementary graph-editing hint and terminal path summary
are omitted to retain graph space. The editing help remains in Guide.

Native Windows/macOS execution, window icons and native confirmation dialogs
were not tested. Existing graph persistence, branding and copyright are retained.

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
