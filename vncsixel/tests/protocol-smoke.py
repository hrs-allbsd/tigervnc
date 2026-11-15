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
parser.add_argument('--server-format', choices=['rgb888', 'rgb565', 'big-endian'], default='rgb888',
    help='ServerInit format; viewer still negotiates RGB888 update pixels')
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
compressor = zlib.compressobj()
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

# RFC 6143 sections 7.7.4-7.7.6.  These generate wire bytes without using
# TigerVNC's encoders; the expected RGB model is painted separately.
def cpixel(color):
    return color[::-1]

def zrle(x, y, w, h, data):
    compressed = compressor.compress(data) + compressor.flush(zlib.Z_SYNC_FLUSH)
    return (x, y, w, h, 16, struct.pack('!I', len(compressed)) + compressed)

def paint(x, y, w, h, rgb):
    assert len(rgb) == w * h * 3
    for row in range(h):
        pixels[((y+row)*width+x)*3:((y+row)*width+x+w)*3] = rgb[row*w*3:(row+1)*w*3]

def packed(indices, w, h, bits):
    result = bytearray()
    for y in range(h):
        for x in range(0, w, 8//bits):
            value = 0
            for j in range(8//bits):
                value <<= bits
                if x+j < w: value |= indices[y*w+x+j]
            result.append(value)
    return bytes(result)

def run_length(length):
    full, remainder = divmod(length - 1, 255)
    return b'\xff' * full + bytes([remainder])

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
        update('ZRLE solid tile', [zrle(280,100,32,32,b'\x01\xff\xff\0')])
        red, green, blue = b'\xff\0\0', b'\0\xff\0', b'\0\0\xff'
        white, black, yellow = b'\xff\xff\xff', b'\0\0\0', b'\xff\xff\0'
        # Six 16x16 Hextile tiles include right/bottom partial tiles.
        # Background/foreground persist within a rectangle, even across Raw.
        fill(30,140,35,19,blue)
        fill(31,141,4,5,red); fill(46,140,16,16,red)
        fill(30,156,16,3,white)
        fill(30,156,1,1,red); fill(44,157,2,2,green)
        fill(46,156,16,3,green); fill(62,156,3,3,white)
        payload = (b'\x0e'+bgra(blue)+bgra(red)+b'\x01\x11\x34' +
                   b'\x08\x01\x00\xff' + b'\x00' +
                   b'\x1a'+bgra(white)+b'\x02'+bgra(red)+b'\x00\x00'+bgra(green)+b'\xe1\x11' +
                   b'\x01'+bgra(green)*48 + b'\x00')
        update('Hextile inherited colors and partial tiles', [(30,140,35,19,5,payload)])

        # Four ZRLE tiles include 1-pixel-wide and 3-pixel-high edges.
        colors = [red,green,blue,white,black,yellow,b'\0\xff\xff',b'\xff\0\xff']
        rgb = b''.join(colors[(x+3*y)%8] for y in range(67) for x in range(65))
        paint(340,100,65,67,rgb)
        payload = bytearray()
        for ty in range(0,67,64):
            for tx in range(0,65,64):
                payload.append(0)
                for y in range(ty,min(ty+64,67)):
                    for x in range(tx,min(tx+64,65)):
                        payload.extend(cpixel(rgb[(y*65+x)*3:(y*65+x+1)*3]))
        update('ZRLE raw multiple partial tiles', [zrle(340,100,65,67,payload)])
        for count,bits in [(2,1),(3,2),(5,4)]:
            indices = [(x+2*y)%count for y in range(9) for x in range(13)]
            rgb = b''.join(colors[i] for i in indices)
            paint(420,100,13,9,rgb)
            payload = bytes([count])+b''.join(cpixel(c) for c in colors[:count])+packed(indices,13,9,bits)
            update('ZRLE packed palette '+str(count)+' with row padding', [zrle(420,100,13,9,payload)])

        # Runs cross rows and exercise the 255-byte continuation boundary.
        runs = [(0,255),(1,256),(2,257),(3,1),(4,255)]
        rgb = b''.join(colors[index]*length for index,length in runs)
        paint(440,120,32,32,rgb)
        payload = b'\x80'+b''.join(cpixel(colors[i])+run_length(n) for i,n in runs)
        update('ZRLE plain RLE continuation lengths', [zrle(440,120,32,32,payload)])
        paint(480,120,32,32,rgb)
        payload = b'\x85'+b''.join(cpixel(c) for c in colors[:5])
        for index,length in runs:
            payload += bytes([index]) if length==1 else bytes([index|128])+run_length(length)
        update('ZRLE palette RLE singleton and long runs', [zrle(480,120,32,32,payload)])
        fill(440,180,21,17,yellow); fill(480,180,19,13,blue)
        update('ZRLE ordered rectangles share zlib history',
            [zrle(440,180,21,17,b'\x01'+cpixel(yellow)),
             zrle(480,180,19,13,b'\x01'+cpixel(blue))])
        saved = b''.join(pixels[((120+y)*width+480)*3:((120+y)*width+512)*3] for y in range(32))
        paint(480,220,32,32,saved)
        update('CopyRect from decoded ZRLE pixels', [(480,220,32,32,1,struct.pack('!HH',480,120))])
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
                  'negotiated_format': server.client_format or server.server_format,
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
