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
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--encoding', choices=['raw','tight','zrle'], default='raw')
parser.add_argument('--content', choices=['solid','noise'], default='solid')
parser.add_argument('--repeat-cycles', type=int, default=3)
parser.add_argument('--reset-streams', action='store_true', help='Reset all Tight streams before every rectangle')
args = parser.parse_args()
if not 1 <= args.repeat_cycles <= 100:
    parser.error('--repeat-cycles must be 1..100')
if args.reset_streams and args.encoding != 'tight':
    parser.error('--reset-streams requires --encoding=tight')
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
def rectangle(width, height, index):
    global streams
    key = (width, height, index % 2)
    if key not in images:
        rgb = (random_source.randbytes(width*height*3) if args.content=='noise'
               else bytes((255 if index%2 else 0, 0, 255 if not index%2 else 0))*width*height)
        if args.encoding == 'raw':
            data = bytearray(width*height*4)
            data[0::4], data[1::4], data[2::4] = rgb[2::3], rgb[1::3], rgb[0::3]
        elif args.encoding == 'zrle':
            # Raw 64x64 tiles with three-byte little-endian CPIXELs.
            bgr = bytearray(len(rgb))
            bgr[0::3], bgr[1::3], bgr[2::3] = rgb[2::3], rgb[1::3], rgb[0::3]
            data = bytearray()
            for y in range(0,height,64):
                for x in range(0,width,64):
                    data.append(0)
                    for row in range(y,min(y+64,height)):
                        data.extend(bgr[(row*width+x)*3:(row*width+min(x+64,width))*3])
        else:
            data = rgb  # Tight copy filter uses RGB, unlike ZRLE's CPIXEL.
        images[key] = bytes(data)
    data = images[key]
    encoding = {'raw':0,'tight':7,'zrle':16}[args.encoding]
    if args.encoding == 'zrle':
        compressed = zrle_stream.compress(data)+zrle_stream.flush(zlib.Z_SYNC_FLUSH)
        data = struct.pack('!I',len(compressed))+compressed
    elif args.encoding == 'tight':
        if args.reset_streams: streams = [zlib.compressobj() for _ in range(4)]
        stream = index%4
        compressed = streams[stream].compress(data)+streams[stream].flush(zlib.Z_SYNC_FLUSH)
        length = len(compressed)
        assert 0 <= length <= 0x3fffff
        compact = bytearray([length & 127])
        if length > 127:
            compact[0] |= 128; compact.append((length>>7)&127)
            if length > 16383:
                compact[1] |= 128; compact.append(length>>14)
        data = bytes([(stream<<4)|(15 if args.reset_streams else 0)])+compact+compressed
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
            for i in range(16):
                wait(lambda: server.pending is None and server.requested)
                server.update_encoded([rectangle(width,height,count)])
                count += 1
                wait(lambda: server.sent>=count)
            wait(lambda: completed(count))
            phases.append(dict(phase=label, **samples()[-1]))
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
                  'max_wire_bytes':max(wire_lengths), 'phases':phases, 'samples':samples(), 'viewer':json.loads(perf.read_text()),
                  'scope':'local rectangle buffer capacities; not an allocator leak test'}
        assert result['viewer']['updates']==count, result['viewer']
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
