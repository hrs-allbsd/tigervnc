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
parser.add_argument('--rss-interval', type=float, default=1)
parser.add_argument('--geometry', default='160x50')
parser.add_argument('--viewer-option', action='append', default=[])
parser.add_argument('--rss-log', type=Path, help='Flush numeric RSS samples as JSONL during the run')
parser.add_argument('--memory-log', type=Path, help='Viewer numeric allocator/decoder JSONL')
args = parser.parse_args()
outputs = [args.report, *([args.rss_log] if args.rss_log else []),
    *([args.memory_log] if args.memory_log else [])]
resolved = [path.resolve() for path in outputs]
if len(set(resolved)) != len(resolved) or any(path in
        (args.credentials.resolve(),args.viewer.resolve()) for path in resolved):
    parser.error('Output paths must be distinct from each other and input files')
for path in outputs:
    path.parent.mkdir(parents=True,exist_ok=True)
if not .1 <= args.rss_interval <= 60:
    parser.error('--rss-interval must be .1..60 seconds')
args.report.unlink(missing_ok=True)
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
os.execv(sys.argv[1], [sys.argv[1], *sys.argv[5:], '-Shared', '-ViewOnly', '-PerfLog=' + sys.argv[3], values['vnc host']])
'''
processes = []
viewer_pid = None
with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null, \
        (args.rss_log.open('w') if args.rss_log else open(os.devnull,'w')) as rss_log:
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
        statusfile = Path(directory)/'status'
        wrapper = 'statusfile=$1; shift; "$@"; status=$?; echo $status > "$statusfile"; exit $status'
        options = args.viewer_option + (['-MemoryLog='+str(args.memory_log.resolve())] if args.memory_log else [])
        terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', args.geometry,
            '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false',
            '-e', '/bin/sh', '-c', wrapper, 'real-server', str(statusfile), 'python3', '-c', launcher, str(args.viewer.resolve()),
            str(args.credentials.resolve()), str(args.report.resolve()), str(pidfile), *options],
            env=dict(os.environ, DISPLAY=display), stdout=null, stderr=null)
        processes.append(terminal)
        deadline = time.monotonic() + 10
        while not pidfile.exists():
            assert terminal.poll() is None, 'xterm exited before viewer launch'
            assert time.monotonic() < deadline, 'viewer launch timeout'
            time.sleep(.05)
        viewer_pid = int(pidfile.read_text())
        started = time.monotonic()
        deadline = started + args.seconds
        next_rss = started + 5
        rss_samples = []
        while time.monotonic() < deadline:
            assert terminal.poll() is None, 'viewer exited before measurement completed'
            if time.monotonic() >= next_rss:
                rss = int(subprocess.check_output(['ps','-o','rss=','-p',str(viewer_pid)],stderr=subprocess.DEVNULL))
                sample = {'seconds':time.monotonic()-started,'rss_kib':rss}
                rss_samples.append(sample)
                rss_log.write(json.dumps(sample)+'\n'); rss_log.flush()
                next_rss = time.monotonic()+args.rss_interval
            time.sleep(.1)
        os.kill(viewer_pid, signal.SIGTERM)
        terminal.wait(timeout=15)
        viewer_pid = None
        assert statusfile.read_text().strip() == '0', 'viewer exited unsuccessfully'
        data = json.loads(args.report.read_text())
        assert data['frames'] > 0 and data['remote_width'] > 0, 'no framebuffer rendered'
        data['rss_samples'] = rss_samples
        data['rss_warmup_seconds'] = 5
        args.report.write_text(json.dumps(data,indent=2)+'\n')
        print(json.dumps({k:v for k,v in data.items() if k!='rss_samples'}, sort_keys=True))
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
