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
RSA-AES keys can be saved in KnownHosts; see the trust section below.
There is no certificate override.

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
Hextile inherited colors/subrectangles and partial tiles, ZRLE raw/solid,
packed palettes with row padding, plain/palette RLE and shared zlib history,
non-overlapping and overlapping CopyRect, RichCursor masks/hotspots,
XCursor, opaque CursorWithAlpha,
server cursor position, clipping, empty cursors, DesktopSize and
ExtendedDesktopSize.  Add --colors 8 for the eight-color renderer.
--server-format rgb565 or big-endian checks negotiation of the client's
requested 32-bit wire format; it does not force 16-bit decoding.

Add --fragment-updates to send the first 128 bytes of each update in
small writes with short delays.  Large payloads remain bounded in cost.
TCP may coalesce writes; packet or recv() boundaries are not assumed.
Reports include the negotiated format and update write count.

Run all 12 combinations (three ServerInit formats, 8/256 colors,
normal/fragmented updates), each with 49 lossless pixel comparisons:

  python3 vncsixel/tests/protocol-matrix.py /path/to/vncsixel \
      --report-dir /private/protocol-matrix --jobs 2

The runner uses at most three parallel private Xvfb/xterm instances.
It leaves per-case logs/JSON and writes summary.json only after every
case succeeds.  Reports contain fixture data and numeric measurements;
no live connection, credentials or screenshots are used.

Escape key timing
=================
-EscapeTimeout sets the idle wait for a standalone Escape in milliseconds
(default 50, range 1..1000).  Increase it when a terminal connection splits
Escape-prefixed Alt/function-key sequences across delayed reads.  Decrease
it for quicker standalone Escape delivery.  A following ordinary character
within the wait is interpreted as Alt+character.  The event loop checks
expiry at up to 20 ms intervals; this is not a real-time delivery promise.

  vncsixel -EscapeTimeout=150 host
  python3 vncsixel/tests/input-timing.py /path/to/vncsixel \
      --report /private/input-timing.json

Paced paste
===========
Bracketed paste is sent as key events at up to PasteRate characters per
second (default 200, range 1..10000).  This is an upper bound, not a target
throughput: rendering, terminal and network delays can make it slower.
Ordinary typing after a paste keeps its order.  Paste text temporarily
excludes latched modifiers; following typed keys retain their modifiers.
Only bracketed paste is paced; this does not rate-limit ordinary typing.

  vncsixel -PasteRate=100 host

Ctrl+] then u cancels pending input.  Local quit stays available while
paste drains.  Focus loss, suspension and geometry changes also cancel
pending keys rather than sending text to a changed context.  Cancellation
cannot retract characters already sent to the server.

At most 8192 key events are queued, including typing behind a paste.
Overflow clears the unsent queue, discards the rest of that paste and
shows an 'Input cancelled' notice in the status line.  Split a larger
paste into smaller pieces if it exceeds this limit.  ViewOnly suppresses
all pasted and typed remote input.  Pasted text never invokes local
commands or completes a previously typed Ctrl+] prefix.

  python3 vncsixel/tests/paste-smoke.py /path/to/vncsixel \
      --report /private/paste.json

The test uses an actual xterm selection insertion, verifies received key
order and timing, then checks modifier isolation, concurrent painting,
cancel, overflow recovery, quit and ViewOnly.  It uses a private RFB
fixture; it sends no paste to the live server.

Help during a connection
========================
Press Ctrl+] then h (or ?) to open local help.  Esc or Enter returns to
the latest remote image; Ctrl+] h also closes it.  Space/n advances a
page and p returns to the previous page.  Ctrl+] q quits from help.
The screen uses the actual terminal text area and paginates when small.

Opening help cancels queued paste and releases held remote input.
While help is open, typed keys, mouse and pasted text stay local.  The
viewer continues receiving framebuffer updates and redraws the latest
image on return.  Help works in ViewOnly, after resize and after suspend.
The local X11 pointer stays visible over help.  No server desktop name,
credentials or other remote text is inserted in the help screen.

  python3 vncsixel/tests/help-smoke.py /path/to/vncsixel \
      --report /private/help.json

Optional image-adaptive palette
===============================
-PhotoPalette generates a palette for each changed RGB image using
libsixel's high-quality histogram setting and averaged-pixel colors.
It targets photographs and smooth gradients poorly represented by RGB332.
It is opt-in: the default remains the fixed palette and sparse updates.
No error diffusion is enabled.  Color approximation can shift between
frames; improvement is not guaranteed for every image or photograph.

  vncsixel -PhotoPalette host

Each adaptive frame redraws the whole image, including its palette.
RGB snapshots are compared before encoding; indices from different
palettes cannot safely be compared for damage.  Unchanged snapshots are
skipped.  SingleRect has no additional effect in this mode.  Eight-color
terminals retain the existing fixed eight-color path.  Help, resize and
cursor compositing continue to work.  Full-frame output can cost more
CPU and bandwidth and coalesce more intermediate updates than the
fixed-palette path.  RGB snapshot retention also uses three bytes per
pixel instead of one.  PerfLog palette_ms measures palette construction
as a component of encode_ms; do not add the two together.

  python3 vncsixel/tests/photo-palette.py /path/to/vncsixel \
      --report /private/photo.json
  python3 vncsixel/tests/regions-benchmark.py /path/to/vncsixel \
      --textured --photo-palette --report /private/photo-sparse.json

The quality fixture generates a smooth warm gradient and measures actual
xterm RGB error, CPU and encoded bytes against the default.  It checks
palette replacement, changes hidden by RGB332, resize erasure, unchanged
skips and eight-color fallback.  This synthetic fixture is not a measured
photograph corpus.  See DEVELOPMENT.txt for results and limitations.

RSA-AES host verification and TLS
================================
RA2 and RA2_256 verify the server key before sending credentials.  For a
new RSA-AES endpoint, compare the displayed SHA256 fingerprint with one
obtained through a trusted channel.  Type exactly yes to save the public
key, once to accept only this connection, or no/Enter to reject it.
Saved keys match the textual host and TCP port; aliases/address spellings
and different ports have separate entries.  A changed key is rejected
without an override prompt or replacement.  Existing sessions and files
are not silently migrated to a new key.

  vncsixel -SecurityTypes=RA2_256 host
  vncsixel -SecurityTypes=RA2_256 -StrictHostKeyChecking \
      -KnownHosts=/private/known_hosts host

StrictHostKeyChecking rejects unknown keys without prompting.  Matching
saved keys need no prompt.  The default file is vncsixel_rsa_known_hosts
in TigerVNC's data directory: $XDG_DATA_HOME/tigervnc, otherwise
$HOME/.local/share/tigervnc, with core::getvncdatadir()'s legacy ~/.vnc
fallback.  KnownHosts overrides the filename; its parent must already
exist.  Default directories are created only after an explicit yes.
New files use mode 0600.  Existing files must be regular, user-owned,
not writable by group/others, and at most 1 MiB.  Symlink files, malformed
records and duplicate entries for the endpoint are rejected.  Saving is
locked and rechecked; a failed write/sync rejects the connection.
The versioned text format stores hexadecimal endpoint and complete public
key data, not passwords or private keys.  After a legitimate rotation,
verify the new fingerprint independently and use a separately selected
KnownHosts file, or carefully update the verified record offline.

To compute the same fingerprint from the server's public key on a
trusted machine:

  openssl pkey -in server-private.pem -pubout -out server-public.pem
  python3 vncsixel/tests/host-key-fingerprint.py server-public.pem

The fingerprint hashes the RFB key blob (bit length, padded modulus and
exponent), not PEM text, SSH keys or SubjectPublicKeyInfo DER.  The helper
needs Python 3 and openssl; the port includes it with DOCS as
share/doc/vnc-sixel/host-key-fingerprint.py.  The viewer needs neither
Python nor openssl for host verification.

TLS continues to use TigerVNC/GnuTLS certificate and hostname checks.
-X509CA and -X509CRL select additional CA/CRL files.  Untrusted or
hostname-mismatched certificates are rejected; this RSA store does not
create X.509 exceptions.  TLSVnc uses anonymous TLS and does not verify
server identity.  Select X509Vnc or RA2/RA2_256 for authenticated encrypted
sessions.  RA2ne/RA2ne_256 protect authentication only, not later traffic.
SecurityTypes controls negotiation as in vncviewer; no global bypass for
certificate or changed-key checks is provided.

  python3 vncsixel/tests/security-smoke.py /path/to/vncsixel \
      --report /private/security.json

The test uses temporary Xvnc servers, generated keys/certificate and a
dummy password.  It verifies acceptance/rejection, persistence, key
changes, all four RSA-AES variants, anonymous TLS, trusted X.509,
untrusted certificates, hostname mismatch and terminal restoration.

Explicit X.509 trust files
-------------------------
With X509 security types, a nonempty -X509CA or -X509CRL option requires
GnuTLS to load at least one CA certificate or CRL from that PEM file.
Missing, malformed and empty files abort authentication.  This checks the
actual TLS credential load, rather than a separate preflight file read.
Unspecified default files remain optional.  An explicit empty value
clears the requirement; repeated options use the last value.  Normal
TigerVNC case-insensitive and split/equals option forms are supported.
A CRL only covers its issuer and contents; it does not enable automatic
CRL downloading or OCSP.  Keep locally supplied CRLs current.

X.509 verification also requires serverAuth when the leaf certificate
restricts Extended Key Usage.  A clientAuth-only certificate is rejected.
Certificates without an EKU restriction retain GnuTLS's normal behavior.
The existing chain, hostname, validity and revocation checks still apply.

Explicit CRL freshness
----------------------
Every CRL in a nonempty explicit -X509CRL PEM file must include a valid
thisUpdate/nextUpdate interval.  Reject future thisUpdate, expired
nextUpdate, missing/unreadable dates and reversed/empty intervals.
A bundle is rejected if any entry fails, independent of entry order.
The timestamps are checked when importing the file and again when the
TLS handshake completes.  The clock must therefore be set correctly.
Validation and credential installation use the same loaded PEM bytes.

This local-file policy does not fetch CRLs or query OCSP responders.
It does not add issuer coverage or signature verification beyond the
existing GnuTLS trusted-CRL handling.  Supply verified CRLs from your
CA.  Optional default files and the final explicit empty override retain
the previous behavior.  TLS security types without X.509 do not use CRLs.

Tight compression and JPEG hints
--------------------------------
-QualityLevel accepts -1..9.  The default -1 omits the Tight JPEG quality
hint, preserving the previous lossless Tight behavior.  Values 0..9
allow Tight JPEG, from low to high quality, using vncviewer's hint values.
-CompressLevel accepts -1..9.  The default -1 leaves compression to the
server; 0..9 requests low through high compression.  These are server
hints and do not force a particular encoding or measured image quality.
-NoJPEG suppresses both standalone JPEG capability and Tight JPEG
quality hints, even when QualityLevel is set.  It retains lossless Tight.
PhotoPalette independently controls terminal color quantization.

Example: vncsixel -QualityLevel=8 -CompressLevel=2 host:display

Tight lossless tests include Copy, Fill, Palette and Gradient filters,
four persistent zlib streams, resets, row padding, the 12-byte threshold
and compact lengths.  Add --jpeg to protocol-smoke.py or protocol-matrix.py
to enable QualityLevel=8 and a 50th displayed state: Tight JPEG blocks.
This optional fixture requires cjpeg/djpeg (libjpeg-turbo tools).  It
checks JPEG transport, RGB ordering and terminal placement with primary
color blocks.  It is not a photograph/video quality measurement or an
independent JPEG codec test; both codec paths use libjpeg.

  python3 vncsixel/tests/encoding-options.py /path/to/vncsixel \
      --report /private/encoding-options.json
  python3 vncsixel/tests/protocol-matrix.py /path/to/vncsixel --jpeg \
      --report-dir /private/tight-matrix --jobs 2

Semitransparent cursor composition
----------------------------------
Cursor With Alpha uses premultiplied RGBA on the wire; TigerVNC supplies
straight RGBA to the renderer.  The viewer blends this with the sampled
remote background, then quantizes the result for terminal colors.
The compositor now visits only display samples covered by the cursor.
Ceiling bounds preserve nearest-neighbor sampling at fractional scales,
including clipped edges and cursor shapes too small to hit any sample.

PerfLog cursor_samples counts cursor-covered samples considered across
all snapshots, including snapshots whose unchanged image is skipped.
Transparent pixels are counted but do not change the background.
It is not an encoded pixel count or a measure of server input latency.
The protocol fixture includes alpha endpoints/intermediate values,
background changes, movement, clipping, replacement and cursor resize.

Controlled-delay and sustained input checks
------------------------------------------
The loopback-only delayed-link fixture adds fixed delay independently in
each direction.  Its bounded FIFO queues apply TCP backpressure rather
than dropping data.  This models neither a real WAN's congestion/loss nor
physical display scanout; a small queue window can also limit throughput.
The synthetic application's callback delay is measured separately.

  python3 vncsixel/tests/delayed-link-test.py
  python3 vncsixel/tests/latency-matrix.py /path/to/vncsixel \
      --report-dir /private/delayed-latency --samples 30

The matrix runs sequentially at 0/50 ms one-way delay and MaxFPS 10/30,
with a default 25 ms application delay.  Reports separate XTEST-to-RFB
receipt (rfb_dispatch_median_ms), receipt-to-response queueing and
response-to-xterm paint.  Timing ends at XGetImage, before physical scanout.
The two initial inputs are warmups; every key-down/release is checked.

Run a minimum-duration local input regression with optional RSS sampling:

  python3 vncsixel/tests/input-latency.py /path/to/vncsixel \
      --samples 5 --seconds 180 --rss-interval 1 \
      --one-way-ms 50 --application-ms 25 --viewer-option=-MaxFPS=30 \
      --report /private/delayed-soak.json

--samples remains a minimum when --seconds is set.  The duration includes
the two warmups, which are excluded from latency statistics.  RSS samples
contain elapsed seconds and KiB, and are disabled by default in the local
latency test to avoid adding sampling overhead to short benchmarks.

real-server-perf.py also records numeric RSS samples after a five-second
warmup (default interval one second, adjustable with --rss-interval).
It retains shared/ViewOnly operation in its private xterm.  Synthetic keys are
injected only into the private local fixture.  Short regressions
do not establish multi-hour memory stability or remote-application latency.

Optional allocator diagnostics (FreeBSD)
---------------------------------------
Use -MemoryLog=/private/memory.jsonl to write numeric JSON lines at startup,
every MemoryLogInterval seconds (default 5, range 1..3600), and shutdown.
It works independently of PerfLog and is disabled by default.  Sampling
runs at connection-processing boundaries; busy work can delay a sample.
FreeBSD jemalloc statistics are refreshed through mallctl("epoch").
allocated_bytes measures live allocations; active_bytes measures active
pages.  resident_bytes, mapped_bytes and retained_bytes describe allocator
storage, not process RSS.  allocator_error is zero on success; unavailable
statistics produce an error number and omit byte counters.  Other systems
report ENOTSUP.  No addresses, screen pixels or credentials are recorded.
A requested destination that cannot be opened aborts startup.

For real-server-perf.py or input-latency.py, add:
  --viewer-option=-MemoryLog=/private/memory.jsonl \
  --viewer-option=-MemoryLogInterval=5

Exclude startup and the final teardown sample from steady-state analysis.
Short samples cannot prove absence of leaks; compare allocator samples
with RSS and repeat under controlled workloads before changing allocation.

Decoder buffer diagnostics
--------------------------
MemoryLog also records decoder_buffer_bytes: summed capacities of the
TigerVNC rectangle staging pool, including queued, active and partially
received rectangles.  It excludes the framebuffer, socket/decompressor
buffers and frontend rendering storage.  Sample from the protocol producer
thread between processMsg calls; a queue lock protects worker transitions.
Partially filled buffers remain on the free list and are counted once.
Startup is zero before the connection is available; the shutdown entry
repeats the most recent sampled capacity.  Logging disabled incurs no pool
traversal or additional queue lock.

  python3 vncsixel/tests/decoder-memory.py /path/to/vncsixel \
      --report /private/decoder-memory.json

This private xterm regression cycles large, small and repeated large Raw
updates through all pool buffers.  Capacities must plateau after warmup.
It tests retention, not the absence of leaks in other components.

Compressed decoder retention matrix
-----------------------------------
decoder-memory.py accepts --encoding raw|tight|zrle and --content
solid|noise.  --repeat-cycles 1..100 (default 3) repeats the large-update
phase after one large and one small phase.  Each phase has 16 updates;
including the initial image, the default run processes 81 updates.
Tight rotates through all four persistent streams; --reset-streams resets
all streams before each rectangle.  The initial image uses the selected
encoding too, avoiding an unrelated Raw buffer high-water mark.

  python3 vncsixel/tests/decoder-memory-matrix.py /path/to/vncsixel \
      --report-dir /private/compressed-memory

The runner executes seven cases serially: Raw/Tight/ZRLE with solid and
fixed-seed noise data, plus Tight noise with stream resets.  All update
prefixes are fragmented.  It checks plateaued staging capacity and an
upper bound derived from the largest wire payload and the pool's maximum
eight buffers.  JSON reports retain allocator samples when available.
These are capacity tests, not pixel comparisons or general leak tests;
the separate protocol matrix performs xterm pixel comparisons.
