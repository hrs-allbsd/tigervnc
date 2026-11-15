#!/usr/bin/env python3
"""Exercise decoder pool high-water capacity using only local raw updates."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', type=Path, required=True)
args = parser.parse_args()
args.report.unlink(missing_ok=True)
args.report.parent.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
server = fixture.Server(width=1024, height=768, fragment_updates=True)
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
            return memory.exists() and samples()[-1]['updates']>=count
        wait(lambda: completed(1))
        phases = []
        count = 1
        for label, width, height in [('large',1024,768),('small',16,16),('repeat',1024,768)]:
            for i in range(16):
                wait(lambda: server.pending is None and server.requested)
                server.update(0,0,width,height,bytes((i*16,255-i*16,0,0))*width*height)
                count += 1
                wait(lambda: server.sent>=count)
            wait(lambda: completed(count))
            phases.append(dict(phase=label, **samples()[-1]))
        # All queue buffers rotate through large updates.  Small updates and
        # a repeated large cycle must not grow their retained capacities.
        capacity = phases[0]['decoder_buffer_bytes']
        assert capacity >= 1024*768*4, phases
        assert all(p['decoder_buffer_bytes']==capacity for p in phases), phases
        os.kill(pid, signal.SIGTERM); terminal.wait(timeout=15); pid=None
        result = {'phases':phases, 'samples':samples(), 'viewer':json.loads(perf.read_text()),
                  'scope':'local raw buffer capacities; not an allocator leak test'}
        args.report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'capacity_bytes':capacity,'updates':count}))
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
