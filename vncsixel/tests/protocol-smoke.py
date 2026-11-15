#!/usr/bin/env python3
"""Compare decoded RFB updates with an independent pixel model in xterm."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import tempfile
import time
import zlib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', required=True, type=Path)
parser.add_argument('--server-format', choices=['rgb888', 'rgb565', 'big-endian'], default='rgb888')
parser.add_argument('--colors', type=int, choices=[8, 256], default=256)
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
formats = {'rgb888': None, 'rgb565': (16, 16, 0, 1, 31, 63, 31, 11, 5, 0),
           'big-endian': (32, 24, 1, 1, 255, 255, 255, 0, 8, 16)}
server = fixture.Server(server_format=formats[args.server_format])
processes, checks = [], []
width, height = 599, 431
pixels = bytearray(b'\xff\xff\xff' * width * height)
for y in range(12): pixels[y * width * 3:(y * width + 12) * 3] = b'\0\0\xff' * 12
cursor, cursor_size, hotspot, position = b'', (0, 0), (0, 0), (0, 0)

def wait_for(check, label):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.error: raise server.error
        if check(): return
        time.sleep(.03)
    raise AssertionError(label)

def fill(x, y, w, h, color):
    for row in range(y, y + h):
        pixels[(row * width + x) * 3:(row * width + x + w) * 3] = color * w

def bgra(rgb):
    return b''.join(bytes((rgb[i+2], rgb[i+1], rgb[i], 0)) for i in range(0, len(rgb), 3))

def raw(x, y, w, h, color):
    fill(x, y, w, h, color)
    return (x, y, w, h, 0, bgra(color) * w * h)

with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
    try:
        r, w = os.pipe()
        process = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0', '1024x768x24',
            '-noreset', '-nolisten', 'tcp'], pass_fds=(w,), stdout=null, stderr=null)
        processes.append(process); os.close(w)
        assert select.select([r], [], [], 10)[0]
        env = dict(os.environ, DISPLAY=':' + os.read(r, 80).decode().strip()); os.close(r)
        for key in ('VNC_USERNAME', 'VNC_PASSWORD'): env.pop(key, None)
        pidfile, perf = Path(directory)/'pid', Path(directory)/'perf.json'
        wrapper = 'echo $$ > "$1"; shift; exec "$@"'
        terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', '100x36+0+0',
            '-fa', 'monospace', '-bg', 'black', '-fg', 'white', '-b', '0', '-bw', '0', '-xrm', 'XTerm*allowSendEvents: false',
            '-xrm', 'XTerm*numColorRegisters: ' + str(args.colors), '-e', '/bin/sh', '-c',
            wrapper, 'protocol', str(pidfile), str(args.viewer.resolve()), '-ViewOnly',
            '-MaxFPS=30', '-PerfLog=' + str(perf), '127.0.0.1::' + str(server.port)],
            env=env, stdout=null, stderr=null)
        processes.append(terminal)
        windows = []
        def find_window():
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'XTerm'],
                env=env, text=True, capture_output=True)
            if result.returncode: return False
            windows[:] = [result.stdout.splitlines()[-1]]
            return True
        wait_for(find_window, 'no xterm window')
        # Explicit zero borders and black background isolate the image.
        # Compare beyond the framebuffer to catch stale shrink pixels.
        def shot():
            data = subprocess.check_output(['xwd', '-silent', '-id', windows[0]], env=env)
            return subprocess.check_output(['magick', 'xwd:-', '-crop', '720x500+0+0',
                '+repage', '-alpha', 'off', '-depth', '8', 'rgb:-'], input=data)
        def expected():
            canvas = bytearray(720 * 500 * 3)
            for row in range(height):
                canvas[row * 720 * 3:(row * 720 + width) * 3] = pixels[row * width * 3:(row+1) * width * 3]
            cw, ch = cursor_size
            for cy in range(ch):
                for cx in range(cw):
                    x, y = position[0] - hotspot[0] + cx, position[1] - hotspot[1] + cy
                    color = cursor[(cy*cw+cx)*4:(cy*cw+cx+1)*4]
                    if 0 <= x < width and 0 <= y < height and color[3]:
                        canvas[(y*720+x)*3:(y*720+x+1)*3] = color[:3]
            return bytes(canvas)
        def verify(label):
            target = expected()
            matches = [0]
            def same():
                matches[0] = matches[0] + 1 if shot() == target else 0
                return matches[0] >= 3
            try:
                wait_for(same, label)
            except AssertionError:
                actual = shot()
                differences = [(i//3%720, i//3//720, actual[i:i+3].hex(), target[i:i+3].hex())
                    for i in range(0,min(len(actual),len(target)),3) if actual[i:i+3] != target[i:i+3]]
                print(label, 'bytes', len(actual), len(target), 'different pixels', len(differences),
                      'first', differences[:12], flush=True)
                raise
            checks.append(label)
            print('PASS:', label, flush=True)
        def update(label, rectangles):
            before = server.sent
            server.update_encoded(rectangles)
            wait_for(lambda: server.sent > before, 'update not sent: ' + label)
            verify(label)
        verify('initial raw image')
        assert {0, 1, -223, -308, -239, -240, -314, 0x574d5666} <= server.encodings
        assert (server.client_format or server.server_format) == (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        update('raw primary colors', [raw(24, 48, 100, 80, b'\xff\0\0'),
                                     raw(124, 48, 100, 80, b'\0\xff\0')])
        for sx, sy, dx, dy, w, h in [(24,48,350,200,200,80), (24,48,40,64,200,80),
                                      (40,64,24,48,200,80)]:
            saved = b''.join(pixels[((sy+y)*width+sx)*3:((sy+y)*width+sx+w)*3] for y in range(h))
            for y in range(h): pixels[((dy+y)*width+dx)*3:((dy+y)*width+dx+w)*3] = saved[y*w*3:(y+1)*w*3]
            update('CopyRect ' + str((sx,sy,dx,dy)), [(dx,dy,w,h,1,struct.pack('!HH',sx,sy))])
        # Hextile raw tile and ZRLE solid tile, both independent of Raw.
        fill(260, 100, 16, 16, b'\0\0\xff')
        update('Hextile raw tile', [(260,100,16,16,5,b'\x01'+b'\xff\0\0\0'*256)])
        fill(280, 100, 32, 32, b'\0\xff\xff')
        compressed = zlib.compress(b'\x01\xff\xff\0')
        update('ZRLE solid tile', [(280,100,32,32,16,struct.pack('!I',len(compressed))+compressed)])
        # Shape, hotspot, mask, position, clipping and shape removal.
        position, hotspot, cursor_size = (180,180), (3,2), (9,7)
        cursor = b''.join(b'\xff\0\xff\xff' if x < 5 else b'\0\0\0\0' for y in range(7) for x in range(9))
        mask = b'\xf8\0' * 7
        update('RichCursor hotspot and mask', [(180,180,0,0,0x574d5666,b''),
            (3,2,9,7,-239,b'\xff\0\xff\0'*63+mask)])
        position = (0,0)
        update('cursor clipping at top left', [(0,0,0,0,0x574d5666,b'')])
        position = (width-1,height-1)
        update('cursor clipping at bottom right', [(position[0],position[1],0,0,0x574d5666,b'')])
        cursor = b'\xff\xff\0\xff' * 63
        update('XCursor bitmap', [(3,2,9,7,-240,b'\xff\xff\0\0\0\0'+b'\xff\x80'*7+b'\xff\x80'*7)])
        cursor = b'\0\xff\0\xff' * 63
        update('CursorWithAlpha opaque', [(3,2,9,7,-314,struct.pack('!i',0)+b'\0\xff\0\xff'*63)])
        cursor, cursor_size = b'', (0,0)
        update('empty cursor erases old shape', [(0,0,0,0,-239,b'')])
        for nw, nh, encoding in [(323,217,-223),(677,463,-308),(599,431,-223)]:
            old, ow, oh = pixels, width, height
            pixels = bytearray(nw*nh*3)
            for y in range(min(oh,nh)):
                pixels[y*nw*3:(y*nw+min(ow,nw))*3] = old[y*ow*3:(y*ow+min(ow,nw))*3]
            width, height = nw, nh
            payload = b'' if encoding == -223 else struct.pack('!B3xIHHHHI',1,0,0,0,nw,nh,0)
            update('resize preserving pixels ' + str((nw,nh)), [(0,0,nw,nh,encoding,payload)])
            update('resize repaint lower right', [raw(nw-7,nh-5,7,5,b'\xff\0\xff')])
        os.kill(int(pidfile.read_text()), signal.SIGTERM); terminal.wait(timeout=10)
        result = {'checks': checks, 'server_format': args.server_format, 'colors': args.colors,
                  'viewer': json.loads(perf.read_text()), 'scope': 'independent RGB model vs actual xterm pixels'}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2)+'\n')
        print('PASS: ' + ', '.join(checks))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        server.close()
