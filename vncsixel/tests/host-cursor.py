#!/usr/bin/env python3
"""Verify host-pointer visibility in xterm using Xvfb's cursor-bearing fbdir.

XGetImage excludes the native pointer; Xvfb's mapped XWD framebuffer includes
it.  Comparing the two observes actual pointer pixels, not just API calls.
"""
import argparse
import ctypes as C
import ctypes.util
import importlib.util
import json
import mmap
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--exit-mode', choices=['signal', 'disconnect', 'kill'], default='signal')
parser.add_argument('--disabled', action='store_true')
parser.add_argument('--expect-visible', action='store_true')
parser.add_argument('--no-remote-cursor', action='store_true')
parser.add_argument('--view-only', action='store_true')
parser.add_argument('--no-windowid', action='store_true')
parser.add_argument('--scrollbar', choices=['none', 'left', 'right'], default='none')
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
server = fixture.Server(on_key=lambda *unused: None, cursor=not args.no_remote_cursor)
x = C.CDLL(ctypes.util.find_library('X11'))
xt = C.CDLL(ctypes.util.find_library('Xtst'))
def function(lib, name, result, *parameters):
    f = getattr(lib, name); f.restype = result; f.argtypes = parameters; return f
open_display = function(x, 'XOpenDisplay', C.c_void_p, C.c_char_p)
close_display = function(x, 'XCloseDisplay', C.c_int, C.c_void_p)
root_window = function(x, 'XDefaultRootWindow', C.c_ulong, C.c_void_p)
get_image = function(x, 'XGetImage', C.c_void_p, C.c_void_p, C.c_ulong,
    C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int)
get_pixel = function(x, 'XGetPixel', C.c_ulong, C.c_void_p, C.c_int, C.c_int)
destroy_image = function(x, 'XDestroyImage', C.c_int, C.c_void_p)
focus = function(x, 'XSetInputFocus', C.c_int, C.c_void_p, C.c_ulong, C.c_int, C.c_ulong)
sync = function(x, 'XSync', C.c_int, C.c_void_p, C.c_int)
move = function(xt, 'XTestFakeMotionEvent', C.c_int, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong)
create = function(x, 'XCreateSimpleWindow', C.c_ulong, C.c_void_p, C.c_ulong,
    C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_uint, C.c_ulong, C.c_ulong)
map_window = function(x, 'XMapWindow', C.c_int, C.c_void_p, C.c_ulong)
processes, display, framebuffer = [], None, None
checks = []

def wait_for(check, label):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        if server.error: raise server.error
        if check(): return
        time.sleep(.02)
    raise AssertionError(label)

with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
    try:
        r, w = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
            '1200x900x24', '-noreset', '-nolisten', 'tcp', '-fbdir', directory],
            pass_fds=(w,), stdout=null, stderr=null)
        processes.append(xvfb); os.close(w)
        assert select.select([r], [], [], 10)[0]
        address = ':' + os.read(r, 80).decode().strip(); os.close(r)
        env = dict(os.environ, DISPLAY=address)
        for key in ('VNC_USERNAME', 'VNC_PASSWORD'): env.pop(key, None)
        display = open_display(address.encode()); assert display
        root = root_window(display)
        move(display, -1, 1100, 800, 0); sync(display, 0)
        pidfile, done = Path(directory) / 'pid', Path(directory) / 'done'
        wrapper = 'pidfile=$1; done=$2; shift 2; "$@" & p=$!; echo $p > "$pidfile"; wait $p; echo $? > "$done"; read ignored'
        if args.no_windowid: wrapper = 'unset WINDOWID; ' + wrapper
        flags = ['-MaxFPS=30']
        if args.disabled: flags += ['-HideLocalCursor=0']
        if args.view_only: flags += ['-ViewOnly']
        options = []
        if args.scrollbar != 'none': options += ['-sb', '-xrm', 'XTerm*rightScrollBar: ' + str(args.scrollbar == 'right').lower()]
        terminal = subprocess.Popen(['xterm', *options, '-ti', 'vt340', '-geometry', '100x36+0+0',
            '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false', '-e', '/bin/sh', '-c', wrapper,
            'cursor-test', str(pidfile), str(done), str(args.viewer.resolve()), *flags,
            '127.0.0.1::' + str(server.port)], env=env, stdout=null, stderr=null)
        processes.append(terminal)
        window = []
        def find_window():
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'XTerm'], env=env, capture_output=True, text=True)
            if result.returncode == 0: window[:] = [int(result.stdout.splitlines()[-1])]; return True
            return False
        wait_for(find_window, 'xterm window missing'); win = window[0]
        focus(display, win, 2, 0); sync(display, 0)
        wait_for(pidfile.exists, 'viewer PID missing'); pid = int(pidfile.read_text())
        image_file = open(Path(directory) / 'Xvfb_screen0', 'rb')
        framebuffer = mmap.mmap(image_file.fileno(), 0, access=mmap.ACCESS_READ)
        header = struct.unpack('!25I', framebuffer[:100])
        offset, stride = header[0] + header[19] * 12, header[12]
        assert header[11] == 32
        byteorder = 'little' if header[7] == 0 else 'big'
        def image(px, py, width, height):
            data = get_image(display, root, px, py, width, height, C.c_ulong(-1).value, 2)
            assert data
            try: return [get_pixel(data, xx, yy) & 0xffffff for yy in range(height) for xx in range(width)]
            finally: destroy_image(data)
        origin = []
        def painted():
            # Scrollbars alter the text origin, so discover the blue marker.
            patch = image(0, 0, 50, 40)
            blue = [i for i, color in enumerate(patch) if color == 0x0000ff]
            if len(blue) >= 64:
                origin[:] = [min(i % 50 for i in blue), min(i // 50 for i in blue)]
                return True
            return False
        wait_for(painted, 'SIXEL framebuffer missing')
        def visible(px, py):
            left, top, size = px - 16, py - 16, 48
            clean = image(left, top, size, size)
            sync(display, 0)
            native = []
            for yy in range(top, top + size):
                base = offset + yy * stride + left * 4
                row = framebuffer[base:base + size * 4]
                native += [int.from_bytes(row[i:i+4], byteorder) & 0xffffff for i in range(0, len(row), 4)]
            return native != clean
        def check_visible(px, py, expected, label):
            move(display, -1, px, py, 0); sync(display, 0)
            matches = [0]
            def settled():
                matches[0] = matches[0] + 1 if visible(px, py) == expected else 0
                return matches[0] >= 5
            wait_for(settled, label); checks.append(label)
        inside = (origin[0] + 100, origin[1] + 100)
        hiding = not (args.disabled or args.view_only or args.no_windowid or args.expect_visible or args.no_remote_cursor)
        check_visible(*inside, not hiding, 'inside image')
        if not args.view_only and not args.no_remote_cursor:
            wait_for(lambda: 0xff00ff in image(inside[0] - 12, inside[1] - 12, 32, 32), 'remote software cursor missing')
            checks.append('remote cursor composited')
        subprocess.run(['xdotool','key','ctrl+bracketright','h'],env=env,check=True)
        check_visible(*inside, True, 'local help shows pointer')
        subprocess.run(['xdotool','key','Escape'],env=env,check=True)
        check_visible(*inside, not hiding, 'return from help')
        check_visible(origin[0] + 700, origin[1] + 500, True, 'image margin')
        check_visible(*inside, not hiding, 'return from margin')
        check_visible(1100, 800, True, 'outside xterm')
        check_visible(*inside, not hiding, 're-enter xterm')
        other = create(display, root, 1000, 700, 100, 50, 0, 0, 0)
        map_window(display, other); focus(display, other, 2, 0); sync(display, 0)
        check_visible(*inside, True, 'focus loss')
        focus(display, win, 2, 0); sync(display, 0)
        check_visible(*inside, not hiding, 'focus return')
        os.kill(pid, signal.SIGTSTP)
        wait_for(lambda: 'T' in subprocess.check_output(['ps', '-o', 'state=', '-p', str(pid)], text=True), 'viewer did not suspend')
        check_visible(*inside, True, 'suspend')
        os.kill(pid, signal.SIGCONT)
        check_visible(*inside, not hiding, 'resume')
        if args.exit_mode == 'disconnect': server.close()
        else: os.kill(pid, signal.SIGKILL if args.exit_mode == 'kill' else signal.SIGTERM)
        wait_for(done.exists, 'viewer did not exit')
        check_visible(*inside, True, 'exit restores pointer')
        result = {'checks': checks, 'exit_mode': args.exit_mode, 'hiding_expected': hiding,
                  'scrollbar': args.scrollbar, 'measurement': 'Xvfb fbdir cursor pixels vs cursor-free XGetImage'}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n')
        print('PASS: ' + ', '.join(checks))
    finally:
        if framebuffer is not None: framebuffer.close()
        if display: close_display(display)
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        server.close()
