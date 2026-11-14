#!/usr/bin/env python3
"""Exercise an actual xterm and x11vnc; requires Xvfb and X11 test tools."""
import argparse
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('viewer', type=Path)
parser.add_argument('--records', type=Path, required=True)
args = parser.parse_args()
args.records.mkdir(parents=True, exist_ok=True)
processes = []
log = (args.records / 'integration.log').open('w')

def spawn(argv, env=None, **kw):
    p = subprocess.Popen(list(map(str, argv)), env=env, stdout=log, stderr=log, **kw)
    processes.append(p)
    return p

def display():
    r, w = os.pipe()
    try:
        spawn(['Xvfb', '-displayfd', w, '-screen', '0', '1024x768x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,))
        os.close(w)
        assert select.select([r], [], [], 10)[0], 'Xvfb timeout'
        return dict(os.environ, DISPLAY=':' + os.read(r, 80).decode().strip())
    finally:
        os.close(r)

def wait_for(check, message):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise RuntimeError(message)

try:
    remote, local = display(), display()
    subprocess.run(['xsetroot', '-solid', '#ff0000'], env=remote, check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = spawn(['x11vnc', '-display', remote['DISPLAY'], '-rfbport', port,
                    '-localhost', '-nopw', '-forever', '-shared', '-quiet'])
    def listening():
        try:
            with socket.create_connection(('127.0.0.1', port), .1):
                return True
        except OSError:
            return False
    wait_for(listening, 'VNC server not ready')
    with tempfile.TemporaryDirectory() as tmp:
        before, after, status = [Path(tmp) / n for n in ('before', 'after', 'status')]
        # Pass paths as positional parameters, not interpolated shell code.
        wrapper = 'stty -g > "$1"; "$4" "$5" 2> "$6"; echo $? > "$3"; stty -g > "$2"'
        terminal = spawn(['xterm', '-ti', 'vt340', '-geometry', '100x36', '-fa', 'monospace',
                          '-e', '/bin/sh', '-c', wrapper, 'smoke', before, after, status,
                          args.viewer.resolve(), '127.0.0.1::' + str(port), args.records.resolve() / 'viewer.log'], env=local)
        def window():
            result = subprocess.run(['xdotool', 'search', '--class', 'XTerm'], env=local,
                                    capture_output=True, text=True)
            return result.stdout.splitlines()[-1] if result.returncode == 0 else None
        win = wait_for(window, 'xterm window missing')
        # Observe the red Sixel image, not merely a running process/window.
        image = args.records / 'viewer.png'
        def painted():
            if terminal.poll() is not None:
                raise RuntimeError('viewer terminated before painting')
            shot = subprocess.check_output(['xwd', '-silent', '-id', win], env=local)
            subprocess.run(['convert', 'xwd:-', image], input=shot, check=True, stderr=log)
            fraction = subprocess.check_output(['convert', image, '-alpha', 'off',
                '-fx', '(r>0.9 && g<0.1 && b<0.1)?1:0', '-format', '%[fx:mean]', 'info:'], text=True)
            return float(fraction) > .2
        wait_for(painted, 'no red SIXEL framebuffer observed')
        subprocess.run(['xdotool', 'windowfocus', '--sync', win], env=local, check=True)
        subprocess.run(['xdotool', 'key', 'ctrl+bracketright'], env=local, check=True)
        wait_for(status.exists, 'viewer did not exit')
        assert before.read_bytes() == after.read_bytes(), 'termios not restored'
        assert status.read_text().strip() == '0', (args.records / 'viewer.log').read_text()
        print('PASS: VNC connection, Sixel pixels in xterm, and terminal restoration')
finally:
    for p in reversed(processes):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
    log.close()
