# Validation record

Copyright 2026 Ib Helmer Nielsen. Licensed under Apache-2.0.

## Actual environment

- CPython 3.13.5 on Linux.
- Standard-library Tkinter with a real Tk window on an Xvfb display.
- GUI screenshots captured from the running application, not mockups.
- No native Windows or macOS execution was available. The source targets Python 3.10+; older Python versions were not executed here.

## Automated model tests

Command:

```text
python -m unittest -v
```

Result: **27 tests passed**.

The randomized test includes 40 seeded topologies, six roots per topology, comparison against an independent Bellman-Ford implementation, and 1,440 source/destination packet traces. It covers connected and disconnected graphs.

## GUI smoke checks performed

- Create the application and process Tk events without callback errors.
- Step through SPF and observe the tentative improvement of E through D.
- Finish one router; verify that exactly one SPF table is installed.
- Build all tables; verify the additional six independent SPF calculations.
- Animate successive local forwarding lookups along A-C-B-D-E-F.
- Verify successful delivery, cost 10, and unchanged SPF-run count during packet forwarding.
- Disable D-E without rebuilding; verify a packet drop at D using stale tables.
- Rebuild all tables; verify recovery over A-C-E-F with cost 11.
- Animate all router calculations using the same scheduled tick handler.
- Resize the application from 1440 x 900 to 1180 x 740 and check the compact graph and scrollable Live view.
- Pause and resume the all-router queue without discarding remaining routers.

## Original distribution screenshots

The screenshot files below are part of the original Dijkstra Routing Lab ZIP distributed with the demonstration, not this source-only repository. They are not required to run the application.

`preview_spf.png` shows an intermediate SPF calculation with staged entries.

`preview_forwarding.png` shows a packet traversing D-E while D's installed entry for 10.0.0.6/32 is selected. The completed-SPF counter is 7 because this session first calculated A alone and then built all six tables.


## Repository packaging verification — 2 October 2026

Copyright and Apache-2.0 headers, module attribution metadata, and an in-application
Guide notice were added. The routing algorithm and forwarding implementation
were preserved. The 27 unit tests and `--print-tables` console demonstration
were rerun on CPython 3.13.5 / Linux. Both completed successfully.
