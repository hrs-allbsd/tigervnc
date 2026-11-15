#!/usr/bin/env python3
"""Measure a real server in a private xterm without forwarding any input.

Only numeric viewer statistics are saved.  Credentials, hostnames and screen
contents are never written to the report or captured as screenshots.
"""
import argparse
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
parser.add_argument('--credentials', type=Path, required=True)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--seconds', type=int, default=20)
parser.add_argument('--geometry', default='160x50')
parser.add_argument('--viewer-option', action='append', default=[])
args = parser.parse_args()
if args.seconds < 1:
    parser.error('--seconds must be positive')
args.report.parent.mkdir(parents=True, exist_ok=True)
# Run the credential reader inside xterm so its environment is not shared
# with Xvfb or the benchmark parent.  No values are interpolated into code.
launcher = r'''
import os, sys
from pathlib import Path
values = {}
for line in Path(sys.argv[2]).read_text().splitlines():
    if not line.strip(): continue
    separator = '=' if '=' in line and (':' not in line or line.index('=') < line.index(':')) else ':'
    key, value = line.split(separator, 1)
    values[key.strip().lower()] = value.strip()
os.environ['VNC_USERNAME'] = values['vnc user']
os.environ['VNC_PASSWORD'] = values['vnc pass']
Path(sys.argv[4]).write_text(str(os.getpid()))
null = os.open(os.devnull, os.O_WRONLY)
os.dup2(null, 1); os.dup2(null, 2); os.close(null)
os.execv(sys.argv[1], [sys.argv[1], '-ViewOnly', '-PerfLog=' + sys.argv[3], *sys.argv[5:], values['vnc host']])
'''
processes = []
viewer_pid = None
with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
    try:
        r, w = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
            '1920x1080x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,), stdout=null, stderr=null)
        processes.append(xvfb)
        os.close(w)
        assert select.select([r], [], [], 10)[0], 'Xvfb timeout'
        display = ':' + os.read(r, 80).decode().strip()
        os.close(r)
        pidfile = Path(directory) / 'pid'
        terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', args.geometry,
            '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false',
            '-e', 'python3', '-c', launcher, str(args.viewer.resolve()),
            str(args.credentials.resolve()), str(args.report.resolve()), str(pidfile), *args.viewer_option],
            env=dict(os.environ, DISPLAY=display), stdout=null, stderr=null)
        processes.append(terminal)
        deadline = time.monotonic() + 10
        while not pidfile.exists():
            assert terminal.poll() is None, 'xterm exited before viewer launch'
            assert time.monotonic() < deadline, 'viewer launch timeout'
            time.sleep(.05)
        viewer_pid = int(pidfile.read_text())
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            assert terminal.poll() is None, 'viewer exited before measurement completed'
            time.sleep(.1)
        os.kill(viewer_pid, signal.SIGTERM)
        terminal.wait(timeout=15)
        viewer_pid = None
        data = json.loads(args.report.read_text())
        assert data['frames'] > 0 and data['remote_width'] > 0, 'no framebuffer rendered'
        print(json.dumps(data, sort_keys=True))
    finally:
        if viewer_pid is not None:
            try: os.kill(viewer_pid, signal.SIGTERM)
            except ProcessLookupError: pass
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
