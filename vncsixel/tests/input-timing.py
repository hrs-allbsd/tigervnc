#!/usr/bin/env python3
"""Verify configurable Escape/Alt timing through an actual xterm."""
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
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
results = []
for timeout in (20, 250):
    server = fixture.Server(on_key=lambda *unused: None)
    processes = []
    with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
        try:
            r, w = os.pipe()
            xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
                '1024x768x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,), stdout=null, stderr=null)
            processes.append(xvfb); os.close(w)
            assert select.select([r], [], [], 10)[0]
            env = dict(os.environ, DISPLAY=':' + os.read(r,80).decode().strip()); os.close(r)
            for key in ('VNC_USERNAME', 'VNC_PASSWORD'): env.pop(key, None)
            pidfile = Path(directory)/'pid'
            terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', '100x36',
                '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false', '-e', '/bin/sh', '-c',
                'echo $$ > "$1"; shift; exec "$@"', 'timing', str(pidfile), str(args.viewer.resolve()),
                '-EscapeTimeout=' + str(timeout), '127.0.0.1::' + str(server.port)],
                env=env, stdout=null, stderr=null)
            processes.append(terminal)
            def wait_for(check, label):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if server.error: raise server.error
                    if check(): return
                    time.sleep(.01)
                raise AssertionError(label)
            windows = []
            def find_window():
                found = subprocess.run(['xdotool','search','--onlyvisible','--class','XTerm'],
                    env=env,text=True,capture_output=True)
                if found.returncode: return False
                windows[:] = [found.stdout.splitlines()[-1]]; return True
            wait_for(find_window, 'xterm missing')
            subprocess.run(['xdotool','windowfocus','--sync',windows[0]],env=env,check=True)
            wait_for(lambda: server.sent > 0, 'initial frame missing')
            def key(name): subprocess.run(['xdotool','key',name],env=env,check=True)
            # Ensure terminal negotiation and input enabling have completed.
            key('a')
            wait_for(lambda: any(down and code == ord('a') for _,down,code in server.key_events), 'input not ready')
            key('Escape')
            time.sleep(.09)
            key('x')
            wait_for(lambda: any(not down and code == ord('x') for _,down,code in server.key_events), 'x missing')
            events = [(down,code) for _,down,code in server.key_events if code != ord('a')]
            if timeout == 20:
                assert events == [(1,0xff1b),(0,0xff1b),(1,ord('x')),(0,ord('x'))], events
            else:
                assert events == [(1,0xffe9),(1,ord('x')),(0,ord('x')),(0,0xffe9)], events
            # An isolated Escape must eventually be sent for either setting.
            start = time.monotonic_ns()
            key('Escape')
            wait_for(lambda: any(stamp >= start and down and code == 0xff1b
                for stamp,down,code in server.key_events), 'isolated Escape missing')
            elapsed = next((stamp-start)/1e6 for stamp,down,code in server.key_events
                if stamp >= start and down and code == 0xff1b)
            assert elapsed >= timeout - 5, (timeout,elapsed)
            results.append({'timeout_ms': timeout, 'escape_received_ms': elapsed,
                'delayed_x': 'separate Escape and x' if timeout == 20 else 'Alt+x'})
            os.kill(int(pidfile.read_text()),signal.SIGTERM); terminal.wait(timeout=10)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            server.close()
for value in ('0','1001','-1'):
    result = subprocess.run([str(args.viewer.resolve()), '-EscapeTimeout='+value, '127.0.0.1'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert result.returncode != 0
    assert b'Invalid argument' in result.stderr, result.stderr
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'checks':results,'invalid_values_rejected':[0,1001,-1]},indent=2)+'\n')
print('PASS: short Escape, delayed Alt, isolated Escape, parameter bounds')
