#!/usr/bin/env python3
"""Compare partial redraws with forced full redraws in a real xterm."""
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

parser = argparse.ArgumentParser()
parser.add_argument('viewer', type=Path)
parser.add_argument('--records', type=Path, required=True)
parser.add_argument('--colors', type=int, default=256)
parser.add_argument('--slow-pty', action='store_true')
args = parser.parse_args()
args.records.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
server = fixture.Server()
processes = []

def wait_for(check, message):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if check(): return
        if server.error: raise server.error
        time.sleep(.05)
    raise AssertionError(message)

with tempfile.TemporaryDirectory() as directory, open(os.devnull, 'wb') as null:
    try:
        r, w = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(w), '-screen', '0',
            '1024x768x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,), stdout=null, stderr=null)
        processes.append(xvfb)
        os.close(w)
        assert select.select([r], [], [], 10)[0]
        env = dict(os.environ, DISPLAY=':' + os.read(r, 80).decode().strip())
        os.close(r)
        for key in ('VNC_USERNAME', 'VNC_PASSWORD'): env.pop(key, None)
        report = args.records.resolve() / 'performance.json'
        pidfile = Path(directory) / 'pid'
        wrapper = 'echo $$ > "$1"; exec "$2" -ViewOnly -PerfLog="$3" "$4" 2> "$5"'
        terminal = subprocess.Popen(['xterm', '-ti', 'vt340', '-geometry', '100x36',
            '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false',
            '-xrm', 'XTerm*numColorRegisters: ' + str(args.colors), '-e',
            '/bin/sh', '-c', wrapper, 'damage', str(pidfile), str(args.viewer.resolve()),
            str(report), '127.0.0.1::' + str(server.port), str(args.records.resolve() / 'viewer.log')], env=env, stdout=null, stderr=null)
        processes.append(terminal)
        window = []
        def find_window():
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'XTerm'], env=env,
                                    capture_output=True, text=True)
            if result.returncode == 0:
                window[:] = [result.stdout.splitlines()[-1]]
                return True
            return False
        wait_for(find_window, 'no xterm')
        win = window[0]
        subprocess.run(['xdotool', 'windowfocus', '--sync', win], env=env, check=True)

        def shot():
            data = subprocess.check_output(['xwd', '-silent', '-id', win], env=env)
            return subprocess.check_output(['magick', 'xwd:-', '-alpha', 'off', '-depth', '8', 'rgb:-'], input=data)

        # Use an image-content condition rather than a fixed startup sleep.
        image = [b'']
        stable = [0]
        def initially_painted():
            current = shot()
            stable[0] = stable[0] + 1 if current == image[0] else 0
            image[0] = current
            return current.count(b'\0\0\xff') >= 100 and stable[0] >= 35
        wait_for(initially_painted, 'initial white framebuffer not drawn')
        prior = image[0]
        cases = [(18, 78, 96, 78, b'\0\0\0\0'),
                 (114, 78, 96, 78, b'\0\0\xff\0'),
                 (18, 78, 96, 78, b'\xff\xff\xff\0'),
                 (594, 426, 5, 5, b'\0\xff\0\0')]
        for i, (x, y, width, height, color) in enumerate(cases):
            server.update(x, y, width, height, color * width * height)
            wait_for(lambda: server.sent >= i + 2, 'update not sent')
            def changed():
                image[0] = shot()
                return image[0] != prior
            wait_for(changed, 'partial image did not change')
            stable[0] = 0
            def settled():
                current = shot()
                stable[0] = stable[0] + 1 if current == image[0] else 0
                image[0] = current
                return stable[0] >= 5
            wait_for(settled, 'partial image did not settle')
            partial = image[0]
            subprocess.run(['xdotool', 'key', 'ctrl+bracketright', 'r'], env=env, check=True)
            # A full redraw passes through geometry negotiation.  Capture once
            # it matches the partial image again, requiring repeated equality.
            matches = [0]
            def same():
                current = shot()
                matches[0] = matches[0] + 1 if current == partial else 0
                return matches[0] >= 35
            wait_for(same, 'partial and full redraw differ')
            prior = partial
        if args.slow_pty:
            # Stop only xterm's reader, leaving the viewer and RFB server
            # running.  A busy image fills the PTY; subsequent RFB updates
            # must still be decoded without accumulating encoded frames.
            pixels = bytearray()
            for y in range(server.height):
                for x in range(server.width):
                    c = (x * 17 + y * 29) & 255
                    pixels.extend(((c & 3) * 255 // 3,
                        ((c >> 2) & 7) * 255 // 7, (c >> 5) * 255 // 7, 0))
            os.kill(terminal.pid, signal.SIGSTOP)
            try:
                target = server.sent + 1
                server.update(0, 0, server.width, server.height, bytes(pixels))
                wait_for(lambda: server.sent >= target, 'busy image not received')
                for n in range(6):
                    target += 1
                    server.update(20 + n, 20, 1, 1, b'\0\0\0\0')
                    wait_for(lambda: server.sent >= target, 'RFB stalled on blocked PTY')
                # The queue stays blocked while further updates are decoded.
                assert os.kill(int(pidfile.read_text()), 0) is None
            finally:
                os.kill(terminal.pid, signal.SIGCONT)
            image[0] = b''
            stable[0] = 0
            def resumed():
                current = shot()
                stable[0] = stable[0] + 1 if current == image[0] else 0
                image[0] = current
                return stable[0] >= 35 and current != prior
            wait_for(resumed, 'blocked image did not finish after resume')
            partial = image[0]
            subprocess.run(['xdotool', 'key', 'ctrl+bracketright', 'r'], env=env, check=True)
            matches[0] = 0
            wait_for(same, 'latest framebuffer lost while PTY was blocked')
        os.kill(int(pidfile.read_text()), signal.SIGTERM)
        terminal.wait(timeout=10)
        data = json.loads(report.read_text())
        assert data['partial_frames'] >= len(cases), data
        assert data['full_frames'] >= len(cases) + 1, data
        if args.slow_pty:
            assert data['blocked_writes'] > 0, data
            assert data['peak_queue_bytes'] < 32 * 1024 * 1024, data
            assert data['updates'] >= len(cases) + 8, data
            print('PASS: blocked PTY stays bounded, RFB progresses, latest framebuffer preserved')
        print('PASS: partial/full pixel equality, black erasure, adjacent regions, lower-right band, shared/view-only')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        server.close()
