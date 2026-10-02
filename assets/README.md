# Branding assets

The application loads these local assets relative to `dijkstra_routing_demo.py`,
not relative to the terminal's current directory. There are no runtime image
libraries or asset downloads. Missing or unreadable assets produce text fallbacks
and an Event log entry; they do not prevent the routing laboratory from running.

## IHN

`ihn-logo.png` is the existing 48 x 48 IHN mark from Ib Helmer Nielsen's
`ibhelmer/ipam` project, `static/logo.png`. It is reused without alteration.
Its source Git blob SHA is `de32efd6300f4e9d0d652507904cd47993a129fc`.

`ihn-icon-16.png` and `ihn-icon-32.png` are reduced versions of that PNG.
`ihn.ico` contains 16, 24, 32 and 48 pixel versions for Windows windows and
shortcuts. No higher-resolution original was used or invented.

Copyright 2026 Ib Helmer Nielsen. The IHN mark identifies its owner; including
it here does not imply that a modified application is endorsed by its owner.

## UCN

`ucn-logo.svg` is the original UCN symbol already supplied in the user's
`ibhelmer/qr` project at `static/logo.svg`. The original source bytes are
preserved, with Git blob SHA `b6bf0814fac12bb77a083b5f7201f94770f346d1`.
`ucn-logo.png` is a transparent 104 x 62 raster rendering of the same SVG,
with its original `#004250` fill and preserved aspect ratio. No logo lettering
was re-created and no font files are redistributed.

UCN's name and logo remain UCN's marks. They are **not relicensed under the
project's Apache-2.0 software license**. Their display identifies the requested
teaching context and does not assert official UCN endorsement of this software.
For current institutional logo guidance, use
[UCN's press/design page](https://www.ucn.dk/om-ucn/presse/).

## Formats and platform behavior

Tk reads the supplied PNG files directly. `iconphoto` requests a window icon;
Windows additionally uses the multi-size ICO through `iconbitmap`. Actual title
bar, taskbar and Dock behavior depends on the platform, Tk version and window
manager. This is a desktop application, not a website: there is no browser tab
to which a favicon could be attached. The ICO may also be selected manually for
a Windows shortcut; the application does not change `.py` file associations.

Pillow and CairoSVG were used only to prepare these distributed image assets.
They are **not application or test dependencies**.

See the [Tk window-manager reference](https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm)
for `iconphoto` and `iconbitmap` behavior.
