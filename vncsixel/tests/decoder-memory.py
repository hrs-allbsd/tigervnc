#!/usr/bin/env python3
"""Exercise decoder pool high-water capacity using local Raw, Tight and ZRLE updates."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import select
import random
import struct
import zlib
import signal
import shutil
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--encoding', choices=['raw','tight','zrle','mixed'], default='raw')
parser.add_argument('--content', choices=['solid','noise'], default='solid')
parser.add_argument('--jpeg', action='store_true', help='Include Tight JPEG in mixed mode (requires cjpeg)')
parser.add_argument('--repeat-cycles', type=int, default=3)
parser.add_argument('--reset-streams', action='store_true', help='Reset all Tight streams before every rectangle')
args = parser.parse_args()
if not 1 <= args.repeat_cycles <= 100:
    parser.error('--repeat-cycles must be 1..100')
if args.reset_streams and args.encoding != 'tight':
    parser.error('--reset-streams requires --encoding=tight')
if args.jpeg and args.encoding != 'mixed':
    parser.error('--jpeg requires --encoding=mixed')
if args.jpeg and shutil.which('cjpeg') is None:
    parser.error('--jpeg requires cjpeg')
args.report.unlink(missing_ok=True)
args.report.parent.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
server = fixture.Server(width=1024, height=768, fragment_updates=True)
# Deterministic entropy avoids accidentally benchmarking only tiny solid streams.
random_source = random.Random(0)
images = {}
streams = [zlib.compressobj() for _ in range(4)]
zrle_stream = zlib.compressobj()
wire_lengths = []
modes = ['raw','tight','zrle','palette','gradient'] if args.encoding=='mixed' else [args.encoding]
if args.jpeg: modes.append('jpeg')
phase_updates = 8*len(modes) if args.encoding=='mixed' else 16
coverage, tight_uses, resets = {}, [0]*4, 0
started = time.monotonic()

def gradient(rgb, width, height):
    # The gradient predictor operates on reconstructed RGB, not residuals.
    residual = bytearray(len(rgb))
    for y in range(height):
        for x in range(width):
            offset = (y*width+x)*3
            for channel in range(3):
                i = offset+channel
                left = rgb[i-3] if x else 0
                above = rgb[i-width*3] if y else 0
                diagonal = rgb[i-width*3-3] if x and y else 0
                estimate = min(255,max(0,left+above-diagonal))
                residual[i] = (rgb[i]-estimate)&255
    return bytes(residual)

def rectangle(width, height, index):
    global streams, resets
    mode = modes[(index//8)%len(modes)] if args.encoding=='mixed' else args.encoding
    coverage[mode] = coverage.get(mode,0)+1
    key = (mode, width, height, index % 2)
    if key not in images:
        rgb = (random_source.randbytes(width*height*3) if args.content=='noise'
               else bytes((255 if index%2 else 0, 0, 255 if not index%2 else 0))*width*height)
        if mode == 'raw':
            data = bytearray(width*height*4)
            data[0::4], data[1::4], data[2::4] = rgb[2::3], rgb[1::3], rgb[0::3]
        elif mode == 'zrle':
            # Raw 64x64 tiles with three-byte little-endian CPIXELs.
            bgr = bytearray(len(rgb))
            bgr[0::3], bgr[1::3], bgr[2::3] = rgb[2::3], rgb[1::3], rgb[0::3]
            data = bytearray()
            for y in range(0,height,64):
                for x in range(0,width,64):
                    data.append(0)
                    for row in range(y,min(y+64,height)):
                        data.extend(bgr[(row*width+x)*3:(row*width+min(x+64,width))*3])
        elif mode == 'gradient':
            data = gradient(rgb,width,height)
        elif mode == 'palette':
            # Two-color rows are MSB-first, padded independently to bytes.
            data = bytes(0xaa if (y+index)%2 else 0x55
                         for y in range(height) for _ in range((width+7)//8))
        elif mode == 'jpeg':
            ppm = f'P6\n{width} {height}\n255\n'.encode()+rgb
            data = subprocess.run(['cjpeg','-quality','80'],input=ppm,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
        else:
            data = rgb  # Tight copy filter uses RGB, unlike ZRLE's CPIXEL.
        images[key] = bytes(data)
    data = images[key]
    encoding = 0 if mode=='raw' else 16 if mode=='zrle' else 7
    if mode == 'zrle':
        compressed = zrle_stream.compress(data)+zrle_stream.flush(zlib.Z_SYNC_FLUSH)
        data = struct.pack('!I',len(compressed))+compressed
    elif encoding == 7:
        control = 0x90 if mode=='jpeg' else (index%4)<<4
        filters = b''
        if mode!='jpeg':
            # Mixed mode resets all streams before each copy-filter block,
            # then carries zlib history across its eight rectangles.
            reset = args.reset_streams or (args.encoding=='mixed' and mode=='tight' and index%8==0)
            if reset:
                streams = [zlib.compressobj() for _ in range(4)]
                control |= 15
                resets += 1
            stream = index%4
            tight_uses[stream] += 1
            if mode=='palette':
                control |= 64
                filters = b'\x01\x01\xff\0\0\0\0\xff'
            elif mode=='gradient':
                control |= 64
                filters = b'\x02'
            data = streams[stream].compress(data)+streams[stream].flush(zlib.Z_SYNC_FLUSH)
        length = len(data)
        assert 0 <= length <= 0x3fffff
        compact = bytearray([length & 127])
        if length > 127:
            compact[0] |= 128; compact.append((length>>7)&127)
            if length > 16383:
                compact[1] |= 128; compact.append(length>>14)
        data = bytes([control])+filters+compact+data
    wire_lengths.append(len(data))
    return (0,0,width,height,encoding,data)
# Replace the fixture's initial Raw image before starting the viewer, so the
# selected encoding is responsible for every buffer's high-water capacity.
with server.condition:
    server.pending = [rectangle(1024,768,0)]
processes, pid = [], None
with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
    try:
        r, w = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
            '1024x768x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,), stdout=null, stderr=null)
        processes.append(xvfb); os.close(w)
        assert select.select([r], [], [], 10)[0], 'Xvfb timeout'
        display = ':' + os.read(r, 80).decode().strip(); os.close(r)
        pidfile, memory, perf = [Path(directory)/s for s in ('pid','memory','perf')]
        env = dict(os.environ, DISPLAY=display)
        for key in ('VNC_USERNAME', 'VNC_PASSWORD'): env.pop(key, None)
        terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', '100x36',
            '-fa', 'monospace', '-e', '/bin/sh', '-c',
            'echo $$ > "$1"; shift; exec "$@"', 'decoder-memory', str(pidfile),
            str(args.viewer.resolve()), '-ViewOnly', '-MemoryLog='+str(memory),
            '-MemoryLogInterval=1', '-PerfLog='+str(perf),
            '127.0.0.1::'+str(server.port)], env=env, stdout=null, stderr=null)
        processes.append(terminal)
        def wait(check):
            deadline = time.monotonic()+20
            while not check():
                if server.error: raise server.error
                assert terminal.poll() is None, 'viewer exited'
                assert time.monotonic()<deadline, 'fixture timeout'
                time.sleep(.02)
        wait(pidfile.exists); pid = int(pidfile.read_text())
        def samples():
            return [json.loads(s) for s in memory.read_text().splitlines() if s.endswith('}')]
        def completed(count):
            if not memory.exists(): return False
            rows = samples()
            return bool(rows) and rows[-1]['updates']>=count
        wait(lambda: completed(1))
        phases = []
        count = 1
        for label, width, height in [('large',1024,768),('small',16,16)]+[('repeat-'+str(i+1),1024,768) for i in range(args.repeat_cycles)]:
            for i in range(phase_updates):
                wait(lambda: server.pending is None and server.requested)
                server.update_encoded([rectangle(width,height,count)])
                count += 1
                wait(lambda: server.sent>=count)
            wait(lambda: completed(count))
            rss = int(subprocess.check_output(['ps','-o','rss=','-p',str(pid)]))
            phases.append(dict(phase=label, rss_kib=rss, **samples()[-1]))
        # All queue buffers rotate through large updates.  Small updates and
        # a repeated large cycle must not grow their retained capacities.
        capacity = phases[0]['decoder_buffer_bytes']
        assert capacity >= 1024, phases
        # At most eight buffers; doubling never exceeds twice the largest
        # staged rectangle (Tight's internal length needs up to two extra bytes).
        assert capacity <= 8*max(1024,2*(max(wire_lengths)+2)), phases
        assert all(p['decoder_buffer_bytes']==capacity for p in phases), phases
        os.kill(pid, signal.SIGTERM); terminal.wait(timeout=15); pid=None
        result = {'encoding':args.encoding, 'content':args.content,
                  'reset_streams':args.reset_streams, 'repeat_cycles':args.repeat_cycles,
                  'jpeg':args.jpeg, 'phase_updates':phase_updates, 'coverage':coverage,
                  'tight_stream_uses':tight_uses, 'tight_reset_count':resets,
                  'measurement_seconds':time.monotonic()-started,
                  'max_wire_bytes':max(wire_lengths), 'phases':phases, 'samples':samples(), 'viewer':json.loads(perf.read_text()),
                  'scope':'local rectangle buffer capacities; not an allocator leak test'}
        assert result['viewer']['updates']==count, result['viewer']
        assert all(coverage.get(mode,0)>0 for mode in modes), coverage
        if args.encoding=='mixed':
            assert all(tight_uses) and resets>0, (tight_uses,resets)
        args.report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'capacity_bytes':capacity,'updates':count,'encoding':args.encoding,'content':args.content}))
    finally:
        if pid is not None:
            try: os.kill(pid,signal.SIGTERM)
            except ProcessLookupError: pass
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        server.close()
