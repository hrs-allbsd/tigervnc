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
ten full-screen redraws per second.  Cursor pixels are composited onto a
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

* Full-screen output is the correctness baseline.  Dirty-tile output and
  adaptive palette/performance optimization remain follow-up work.
* Framebuffers are limited to 16M pixels and encoded output to 32 MiB.
  The UI is single-threaded; encoding a large frame can delay input.
* Capability queries have a 250 ms response budget and require an xterm
  with pixel-size reports.  No manual geometry override is implemented.
* The initial palette is deliberately simple; photograph quality is limited.
* Clipboard synchronization, audio, H.264 and terminal multiplexers are
  outside this version.  Long paste is streamed as character key pairs.
* Tests cover FreeBSD 15.1-STABLE/aarch64 and XTerm 410.  TLS and RSA-AES
  interoperability have not been exercised by the localhost smoke test.
