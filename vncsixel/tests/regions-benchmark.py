#!/usr/bin/env python3
"""Compare sparse output against SingleRect with a repeatable RFB workload."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--single-rect', action='store_true')
parser.add_argument('--textured', action='store_true')
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
server = fixture.Server(textured=args.textured)
process = None
try:
    with tempfile.TemporaryDirectory() as directory:
        credentials = Path(directory) / 'credentials'
        credentials.write_text('vnc user: unused\nvnc pass: unused\nvnc host: 127.0.0.1::%d\n' % server.port)
        credentials.chmod(0o600)
        command = [sys.executable, str(Path(__file__).with_name('real-server-perf.py')),
            str(args.viewer), '--credentials', str(credentials), '--report', str(args.report),
            '--seconds', '12', '--geometry', '100x36']
        if args.single_rect: command += ['--viewer-option=-SingleRect']
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL)
        def sent(target):
            end = time.monotonic() + 10
            while server.sent < target:
                assert time.monotonic() < end, 'server did not send update'
                assert process.poll() is None, 'viewer exited'
                if server.error: raise server.error
                time.sleep(.005)
        sent(1)
        for index in range(40):
            time.sleep(.15)
            color = b'\0\0\0\0' if index % 2 == 0 else b'\xff\xff\xff\0'
            server.update_rects([(24, 78, 48, 48, color * 48 * 48),
                                 (504, 360, 48, 48, color * 48 * 48)])
            sent(index + 2)
        assert process.wait(timeout=20) == 0
        data = json.loads(args.report.read_text())
        assert data['updates'] == 41, data
        assert data['frames'] >= 2, data  # Slow output may coalesce display frames.
        print(json.dumps({k: data[k] for k in ('updates', 'frames', 'skipped_frames', 'regions', 'encoded_pixels',
            'encoded_bytes', 'encode_ms', 'cpu_seconds')}))
finally:
    if process is not None and process.poll() is None:
        process.terminate(); process.wait(timeout=5)
    server.close()
