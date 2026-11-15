#!/usr/bin/env python3
"""Measure XTEST key -> RFB key -> xterm image response on a private Xvfb.

The measurement ends at XGetImage observing the response pixel.  It does
not measure physical-monitor scanout, macOS application latency, or WAN RTT.
"""
import argparse
import ctypes as C
import ctypes.util
import importlib.util
import json
import os
from pathlib import Path
import random
import select
import signal
import statistics
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--samples', type=int, default=100)
parser.add_argument('--viewer-option', action='append', default=[])
args = parser.parse_args()
if args.samples < 5: parser.error('at least five samples are required')
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
replies = []
def key(server, down, keysym):
    if down and keysym == ord('a'):
        color = b'\0\0\xff\0' if len(replies) % 2 == 0 else b'\0\xff\0\0'
        server.update(96, 156, 96, 78, color * 96 * 78)
        replies.append(time.monotonic_ns())
server = fixture.Server(on_key=key)
x = C.CDLL(ctypes.util.find_library('X11'))
xt = C.CDLL(ctypes.util.find_library('Xtst'))
def function(library, name, result, *parameters):
    f = getattr(library, name); f.restype = result; f.argtypes = parameters
    return f
open_display = function(x, 'XOpenDisplay', C.c_void_p, C.c_char_p)
close_display = function(x, 'XCloseDisplay', C.c_int, C.c_void_p)
get_image = function(x, 'XGetImage', C.c_void_p, C.c_void_p, C.c_ulong,
    C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int)
get_pixel = function(x, 'XGetPixel', C.c_ulong, C.c_void_p, C.c_int, C.c_int)
destroy_image = function(x, 'XDestroyImage', C.c_int, C.c_void_p)
focus = function(x, 'XSetInputFocus', C.c_int, C.c_void_p, C.c_ulong, C.c_int, C.c_ulong)
flush = function(x, 'XFlush', C.c_int, C.c_void_p)
keycode = function(x, 'XKeysymToKeycode', C.c_ubyte, C.c_void_p, C.c_ulong)
press = function(xt, 'XTestFakeKeyEvent', C.c_int, C.c_void_p, C.c_uint, C.c_int, C.c_ulong)
processes, display = [], None
args.report.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
    try:
        r, w = os.pipe()
        process = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
            '1024x768x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,), stdout=null, stderr=null)
        processes.append(process); os.close(w)
        assert select.select([r], [], [], 10)[0]
        name = ':' + os.read(r, 80).decode().strip(); os.close(r)
        env = dict(os.environ, DISPLAY=name)
        for item in ('VNC_USERNAME', 'VNC_PASSWORD'): env.pop(item, None)
        pidfile = Path(directory) / 'pid'
        performance = Path(directory) / 'performance.json'
        wrapper = 'echo $$ > "$1"; shift; exec "$@"'
        terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', '100x36',
            '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false', '-e',
            '/bin/sh', '-c', wrapper, 'latency', str(pidfile), str(args.viewer.resolve()),
            '-PerfLog=' + str(performance), *args.viewer_option, '127.0.0.1::' + str(server.port)], env=env, stdout=null, stderr=null)
        processes.append(terminal)
        end = time.monotonic() + 10
        win = None
        while win is None:
            assert time.monotonic() < end
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'XTerm'],
                env=env, capture_output=True, text=True)
            if result.returncode == 0: win = int(result.stdout.splitlines()[-1])
            else: time.sleep(.01)
        display = open_display(name.encode()); assert display
        def pixels(px, py, width=1, height=1):
            image = get_image(display, win, px, py, width, height, C.c_ulong(-1).value, 2)
            assert image
            try:
                return [get_pixel(image, xx, yy) for yy in range(height) for xx in range(width)]
            finally: destroy_image(image)
        origin = None
        while origin is None:
            assert time.monotonic() < end, 'no initial framebuffer'
            patch = pixels(0, 0, 30, 30)
            blue = [i for i, color in enumerate(patch) if color == 0x0000ff]
            if len(blue) >= 100: origin = (blue[0] % 30, blue[0] // 30)
            else: time.sleep(.005)
        focus(display, win, 2, 0); flush(display)
        code = keycode(display, ord('a')); assert code
        samples, dispatch = [], []
        rng = random.Random(8675309)
        for index in range(args.samples + 2):
            # Vary phase relative to the viewer frame timer.  Two warmups
            # allow focus-triggered geometry negotiation to settle.
            time.sleep(rng.uniform(.01, .11))
            start = time.monotonic_ns()
            press(display, code, 1, 0); press(display, code, 0, 0); flush(display)
            expected = 0xff0000 if index % 2 == 0 else 0x00ff00
            end = time.monotonic() + 5
            while pixels(origin[0] + 100, origin[1] + 160)[0] != expected:
                if server.error: raise server.error
                assert time.monotonic() < end, 'key response did not paint'
                time.sleep(.001)
            observed = time.monotonic_ns()
            assert len(replies) == index + 1
            if index >= 2:
                samples.append((observed - start) / 1e6)
                dispatch.append((replies[index] - start) / 1e6)
        os.kill(int(pidfile.read_text()), signal.SIGTERM)
        terminal.wait(timeout=10)
        ordered = sorted(samples)
        result = {'samples': args.samples, 'median_ms': statistics.median(samples),
            'p95_ms': ordered[(len(ordered) * 95 + 99) // 100 - 1], 'max_ms': max(samples),
            'min_ms': min(samples), 'rfb_dispatch_median_ms': statistics.median(dispatch),
            'latencies_ms': samples, 'viewer': json.loads(performance.read_text()),
            'scope': 'XTEST to xterm XGetImage on local Xvfb, excluding physical scanout/WAN'}
        args.report.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: v for k, v in result.items() if k not in ('latencies_ms', 'viewer')}))
    finally:
        if display: close_display(display)
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        server.close()
