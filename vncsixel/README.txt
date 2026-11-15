vncsixel: terminal VNC viewer
===========================

Build on FreeBSD:

  python3 /home/hrs/projects/vnc-sixel/src/vncsixel/build-freebsd.py --test

The helper sets and checks nice 20, configures Ninja outside the source
checkout, and builds only vncsixel and its optional parser tests.
Requirements are documented by BUILDING.txt, plus libsixel (pkg-config
module libsixel), Ninja and Python 3.  The parser tests need GoogleTest.
Use BUILD_SIXEL_VIEWER=ON, BUILD_VIEWER=OFF and BUILD_X11=OFF to configure
without X11 development headers or FLTK.  BUILD_TESTING=OFF also omits
tests and performance tools from package builds.  The helper uses these
viewer/X11 settings and explicitly disables X11 package discovery.
The vncsixel binary does not link FLTK or Xlib.

Start in a fresh xterm:

  xterm -ti vt340 -geometry 120x40 \
      -xrm 'XTerm*allowSendEvents: false' \
      -xrm 'XTerm*maxGraphicSize: 4096x4096' \
      -xrm 'XTerm*privateColorRegisters: true' \
      -e /home/hrs/projects/vnc-sixel/obj/freebsd-sixel/vncsixel/vncsixel \
      localhost:1

Use host:display, host::port, or the bracketed IPv6 forms supported by
TigerVNC's network::getHostAndPort().  Passwords are prompted on the TTY
before entering raw mode.  Trusted TLS certificates are accepted; invalid
certificates and RSA-AES host keys without a trust decision are rejected.
There is no certificate override or host-key store yet.

xterm must support Sixel.  Pixel/cell-size queries are used unless
-PixelSize WxH and -CellSize WxH explicitly supply the missing dimensions.  A terminal
self-check is available with --terminal-check.  Avoid tmux/screen in this
initial version.  The allowSendEvents resource must be false: xterm
otherwise suppresses mouse reporting even if the mouse modes are set.
Changing that resource on the command line does not alter user settings.

Controls:

  Normal keys, Unicode text, arrows, editing keys and F1-F12: remote input
  Mouse: move, left/middle/right click, drag, vertical wheel
  Ctrl+] then q: quit
  Ctrl+] then r: redraw
  Ctrl+] then c/a/s: toggle Ctrl/Alt/Shift latch
  Ctrl+] then u: release all remote keys and buttons
  Ctrl+] twice: send Ctrl+] to the remote side

Latch state appears below the image.  For Ctrl+Alt+Delete, latch Ctrl and
Alt, send Delete, then release all with Ctrl+] u.  For Shift+drag, use the
Shift latch because xterm normally reserves physical Shift+mouse for its
own selection.  Physical key release cannot be inferred from ordinary
terminal input: character keys are sent as press/release pairs and key
repeat becomes repeated pairs.  Games requiring true held keys are not
supported.  Bracketed paste sends text without interpreting local command
prefixes; control characters other than formatting are discarded.

The display fits without enlargement, preserving aspect ratio.  It uses
nearest-neighbor sampling, a fixed 256-color RGB332 palette, and at most
ten redraws per second by default (-MaxFPS accepts 1..60).  Changed pixels use aligned rectangles selected by area and color-run
complexity.  Distant changes can use separate SIXEL images; unchanged output is skipped.
Use -FullFrame for the original full-screen fallback.  Cursor pixels are composited onto a
snapshot; the RFB framebuffer remains intact.  All RFB updates, including
CopyRect, are decoded even when terminal redraws are skipped.

SIGWINCH and focus return re-query geometry and redraw.  Mouse clicks are
ignored while new display dimensions are pending.  Focus loss and resize
release remote keys/buttons.  SIGTSTP restores the terminal before stopping;
SIGCONT resumes with fresh queries.  SIGINT/SIGTERM/SIGHUP/SIGQUIT and
connection failure restore terminal modes and termios.  SIGKILL cannot be
handled.  Terminal output is bounded and a partial DCS is cancelled on exit.
Do not run other programs writing to the same terminal during a session.

Integration tests (Xvfb, x11vnc, xterm, xdotool, xev, xwd, ImageMagick):

  python3 /home/hrs/projects/vnc-sixel/src/vncsixel/tests/xterm-smoke.py \
      /home/hrs/projects/vnc-sixel/obj/freebsd-sixel/vncsixel/vncsixel \
      --records /home/hrs/projects/vnc-sixel/records/smoke

Add --exit-mode signal or --exit-mode disconnect for the other cleanup
paths.  Tests run private Xvfb displays and a localhost-only VNC server,
check red Sixel pixels, remote keyboard/mouse events, suspend/resume,
terminal resize, and termios restoration.  No existing X session or VNC
server is used.  Existing package installations are not modified.

Current limits and follow-up work:

* Partial output merges changed tile runs into at most 32 regions, using
  a single bounding rectangle when estimated compression/palette costs
  favor it.  Adaptive palette remains follow-up work.  Forced redraw and
  resize always repaint in full.
* Framebuffers are limited to 64M pixels (256 MiB per 32-bit buffer),
  allowing 6K and 8K desktops.  Total memory usage can be higher, especially
  during resize when old and new buffers coexist.  Encoded output is limited
  to 32 MiB.
  The UI is single-threaded; encoding a large frame can delay input.
* Capability queries finish on a complete reply, with a 250 ms response
  deadline.  Manual PixelSize/CellSize overrides support missing reports.
* The initial palette is deliberately simple; photograph quality is limited.
* Clipboard synchronization, audio, H.264 and terminal multiplexers are
  outside this version.  Long paste is streamed as character key pairs.
* Tests cover FreeBSD 15.1-STABLE/aarch64 and XTerm 410.  TLS and RSA-AES
  interoperability have not been exercised by the localhost smoke test.

Authentication
==============
Username input is echoed; interactive passwords are not echoed.
As in vncviewer/CConn.cxx, VNC_USERNAME and VNC_PASSWORD supply credentials
for authentication requiring both username and password.  Both variables
must be set; otherwise both values are prompted for.  For password-only
authentication, VNC_PASSWORD alone suffices.  Empty values count as set.

  export VNC_USERNAME=alice
  export VNC_PASSWORD
  vncsixel mac.example.org

Set VNC_PASSWORD in your shell before running this example.
For password-only VNC authentication, a file made with vncpasswd can be
selected using the same parameter names and syntax as vncviewer:

  vncsixel -passwd ~/.vnc/passwd host.example.org
  vncsixel -PasswordFile ~/.vnc/passwd host.example.org
  vncsixel -PasswordFile="$HOME/.vnc/passwd" host.example.org

VNC_PASSWORD takes precedence over the password file.  Password files
contain the VNC-obfuscated eight-byte password, not plaintext, and are
not used for authentication that requires a username.  This matches
vncviewer.  Passwords are not accepted as command-line arguments.

Performance measurement
=======================
-PerfLog FILE writes a numeric JSON summary on exit: wall/CPU seconds,
peak RSS (KiB on FreeBSD), decoded update count, rendered frame count,
SIXEL bytes, actual TTY bytes, peak pending output, blocked writes, and
snapshot/encoding times.  No hostnames, credentials or pixels are logged.
Times cover client processing, not end-to-end remote input latency.
Use -ViewOnly to suppress remote input, including cleanup pointer events.
Sessions are shared by default; -Shared=0 requests exclusive access.

For a passive real-server sample in a private Xvfb/xterm:

  python3 vncsixel/tests/real-server-perf.py /path/to/vncsixel \
      --credentials /private/CREDENTIALS.txt --report /private/perf.json \
      --seconds 20

The credential file contains vnc user:, vnc pass:, and vnc host: lines.
Do not add it to Git.  The harness saves statistics without screenshots.
An idle server sample does not measure interactive workload performance.

The fixed RGB332 palette is quantized once per displayed pixel and passed
to libsixel as PAL8, avoiding repeated RGB-to-palette searches inside the
encoder.  This preserves the fixed palette and disables diffusion.

Partial update verification:

  python3 vncsixel/tests/damage-smoke.py /path/to/vncsixel \
      --records /private/damage-test

A deterministic raw-RFB server checks partial/full pixel equality in xterm
for black-text erasure, adjacent colors, and the final lower-right band.
The vertical origin uses lcm(cell height, 6), including 13-pixel cells.
Every DCS includes its palette.  Only the last queued snapshot is cached;
new snapshots wait until the current output queue is completely drained.

Terminal capabilities
=====================
XTSMGRAPHICS queries check available color registers and graphics bounds.
The renderer uses 256 colors when available, or an explicit eight-color
RGB palette when the terminal reports 8..255 registers.  Fewer than eight
registers are rejected.  If the optional color query is unsupported, the
original 256-color baseline is retained.  Graphics bounds cap the drawing
area without guessing a cell size.  Completed replies return immediately.

  vncsixel -PixelSize=960x650 -CellSize=6x13 host
  vncsixel --terminal-check

For automated negotiation/restore tests without X11:

  python3 vncsixel/tests/terminal-probe.py /path/to/vncsixel

Add --colors 8 to damage-smoke.py to verify the eight-color path in xterm.

Add --slow-pty to damage-smoke.py to pause xterm's PTY reader while the
server sends further updates.  The test verifies bounded queued output,
continued RFB decoding, and correct latest-frame display after resume.

See DEVELOPMENT.txt for implementation status, measured results, and
remaining work.

Input response latency
======================
-MaxFPS sets the maximum redraw rate (default 10, range 1..60).  The
rate timer advances only when a frame is actually queued.  Idle or blocked
attempts do not postpone the next changed frame.  Poll wakes at a pending
frame deadline instead of adding a fixed 20 ms delay.  A higher rate can
improve interactive response at the cost of CPU and terminal bandwidth.

  vncsixel -MaxFPS=30 host
  python3 vncsixel/tests/input-latency.py /path/to/vncsixel \
      --viewer-option=-MaxFPS=30 --report /private/input-latency.json

The benchmark injects keys with XTEST, records receipt by a local RFB
server, and detects the response pixel with XGetImage in the actual xterm
window.  It reports local input-to-image latency, not physical display
scanout, remote application processing, or WAN latency.  The default is
100 samples after two warmups, with seeded variation of the input phase.

Sparse output regions
======================
Changed tiles use 16 character columns by lcm(cell height, 6) pixels.
Adjacent horizontal runs and matching vertical runs are merged.  Excessive
fragmentation falls back to a bounding rectangle.  Palette overhead and
horizontal color transitions are estimated before selecting multiple
regions, so compressible blank areas are kept in one image.  The estimate
is heuristic; it cannot guarantee the smallest possible encoded stream.
Each region carries its own palette and the whole frame stays below the
32 MiB output limit.  -SingleRect restores the previous bounding-rectangle
path; -FullFrame still forces complete redraws.

  python3 vncsixel/tests/regions-benchmark.py /path/to/vncsixel \
      --textured --report /private/sparse.json
  python3 vncsixel/tests/regions-benchmark.py /path/to/vncsixel \
      --textured --single-rect --report /private/single.json

Both modes receive the same initial image and 40 paired distant updates.
Slow output may coalesce displayed frames while all RFB updates are decoded.
Compare frame counts as well as bytes, CPU, and encoded pixels.  Omit
--textured to verify the compressible blank-background case.  PerfLog now
also records the number of separately encoded regions.

Local pointer in xterm
======================
Like Xsixel's hw/kdrive/sixel/hostcursor.c, vncsixel uses XFixes 4 to hide
the native X11 pointer while the remote cursor is drawn in the image.
The pointer is shown in image margins, outside xterm, on focus loss,
during suspension, and on exit.  X server cleanup also removes the hide
request after SIGKILL; SIGKILL cannot restore terminal modes.

The optional backend needs DISPLAY and xterm's WINDOWID to refer to the
same accessible X server, and libX11.so.6 / libXfixes.so.3 at runtime.
It loads these libraries dynamically; there is no direct Xlib linkage.
ViewOnly sessions and servers without a received cursor shape keep the
native pointer visible.  An explicitly empty remote cursor is respected.
Missing libraries, XFixes support, or window information leave it visible.
SSH sessions without access to the terminal's X server need this setup
before automatic hiding can work.  No xterm pointerMode resource is changed.

  vncsixel -HideLocalCursor=0 host
  python3 vncsixel/build-freebsd.py --without-host-cursor

ENABLE_HOST_CURSOR defaults to ON; its backend is compiled only when
pkg-config finds x11 and xfixes development headers.  Set it OFF for a
build without these headers.  The FreeBSD port exposes option HOSTCURSOR.

  python3 vncsixel/tests/host-cursor.py /path/to/vncsixel \
      --report /private/host-cursor.json

The test compares Xvfb's cursor-bearing framebuffer with XGetImage,
which excludes the native pointer.  It checks real pointer visibility,
remote cursor pixels, margins, focus, suspension, and exit restoration.
Options cover left/right scrollbars, disconnect, SIGKILL, disabled hiding,
ViewOnly, missing WINDOWID, and missing remote cursor shape.

RFB interoperability regression
===============================
  python3 vncsixel/tests/protocol-smoke.py /path/to/vncsixel \
      --report /private/protocol.json

The private fixture compares actual xterm pixels with an independent RGB
model, including the area outside a resized image.  Cases cover Raw,
Hextile raw tiles, ZRLE solid tiles, non-overlapping and overlapping
CopyRect, RichCursor masks/hotspots, XCursor, opaque CursorWithAlpha,
server cursor position, clipping, empty cursors, DesktopSize and
ExtendedDesktopSize.  Add --colors 8 for the eight-color renderer.
--server-format rgb565 or big-endian checks negotiation of the client's
requested 32-bit wire format; it does not force 16-bit decoding.
