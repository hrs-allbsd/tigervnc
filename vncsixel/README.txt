vncsixel: terminal VNC viewer
===========================

Build on FreeBSD:

  python3 /home/hrs/projects/vnc-sixel/src/vncsixel/build-freebsd.py --test

The helper sets and checks nice 20, configures Ninja outside the source
checkout, and builds only vncsixel and its optional parser tests.
Requirements are documented by BUILDING.txt, plus libsixel (pkg-config
module libsixel), Ninja and Python 3.  The parser tests need GoogleTest.
The current top-level configure still needs X11 development headers,
even with BUILD_VIEWER=OFF.  vncsixel itself does not link FLTK or Xlib.

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

xterm must support Sixel and answer pixel/cell-size queries.  A terminal
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
ten redraws per second.  Changed pixels are enclosed in a rectangle
aligned to character cells and SIXEL bands; unchanged output is skipped.
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

* Partial output uses one bounding rectangle of changes in the displayed
  fixed-palette snapshot.  Multiple independent tiles and adaptive palette
  remain follow-up work.  Forced redraw and resize always repaint in full.
* Framebuffers are limited to 64M pixels (256 MiB per 32-bit buffer),
  allowing 6K and 8K desktops.  Total memory usage can be higher, especially
  during resize when old and new buffers coexist.  Encoded output is limited
  to 32 MiB.
  The UI is single-threaded; encoding a large frame can delay input.
* Capability queries have a 250 ms response budget and require an xterm
  with pixel-size reports.  No manual geometry override is implemented.
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
