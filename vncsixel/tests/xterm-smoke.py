#!/usr/bin/env python3
"""Exercise an actual xterm and x11vnc; requires Xvfb and X11 test tools."""
import argparse
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('viewer', type=Path)
parser.add_argument('--records', type=Path, required=True)
parser.add_argument('--remote-geometry', default='1024x768')
parser.add_argument('--exit-mode', choices=['keyboard', 'signal', 'disconnect'], default='keyboard')
args = parser.parse_args()
args.records.mkdir(parents=True, exist_ok=True)
processes = []
log = (args.records / 'integration.log').open('w')

def spawn(argv, env=None, **kw):
    p = subprocess.Popen(list(map(str, argv)), env=env, stdout=log, stderr=log, **kw)
    processes.append(p)
    return p

def display(geometry='1024x768'):
    r, w = os.pipe()
    try:
        spawn(['Xvfb', '-displayfd', w, '-screen', '0', geometry + 'x24', '-noreset', '-nolisten', 'tcp'], pass_fds=(w,))
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
    remote, local = display(args.remote_geometry), display()
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
        before, after, status, pidfile = [Path(tmp) / n for n in ('before', 'after', 'status', 'pid')]
        # Pass paths as positional parameters, not interpolated shell code.
        wrapper = 'python3 "$8" "$9"; stty -g > "$1"; "$4" "$5" 2> "$6" & p=$!; echo $p > "$7"; wait $p; echo $? > "$3"; stty -g > "$2"; python3 "$8" "${10}"'
        terminal = spawn(['xterm', '-ti', 'vt340', '-geometry', '100x36', '-fa', 'monospace',
                          '-xrm', 'XTerm*allowSendEvents: false', '-e', '/bin/sh', '-c', wrapper, 'smoke', before, after, status,
                          args.viewer.resolve(), '127.0.0.1::' + str(port), args.records.resolve() / 'viewer.log', pidfile, Path(__file__).resolve().parent / 'terminal-state.py',
                          args.records.resolve() / 'modes-before.json', args.records.resolve() / 'modes-after.json'], env=local)
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
        with (args.records / 'remote-events.log').open('w') as events:
            event_app = subprocess.Popen(['xev', '-geometry', args.remote_geometry + '+0+0'],
                                         env=remote, stdout=events, stderr=log)
            processes.append(event_app)
            def remote_window():
                result = subprocess.run(['xdotool', 'search', '--name', 'Event Tester'],
                                        env=remote, capture_output=True, text=True)
                return result.stdout.splitlines()[-1] if result.returncode == 0 else None
            rw = wait_for(remote_window, 'remote event window missing')
            subprocess.run(['xdotool', 'windowfocus', '--sync', rw], env=remote, check=True)
            subprocess.run(['xdotool', 'key', 'a', 'ctrl+c'], env=local, check=True)
            subprocess.run(['xdotool', 'mousemove', '100', '100', 'click', '1'],
                           env=local, check=True)
            def received():
                text = (args.records / 'remote-events.log').read_text()
                if 'ButtonRelease' not in text:
                    subprocess.run(['xdotool', 'mousemove', '100', '100', 'click', '1'], env=local, check=True)
                return 'keysym 0x61, a' in text and 'keysym 0x63, c' in text and 'ButtonRelease' in text
            wait_for(received, 'remote keyboard/mouse events missing')
        event_app.terminate()
        event_app.wait(timeout=5)
        # Exercise suspend/resume and a smaller terminal before exiting.
        pid = int(pidfile.read_text())
        os.kill(pid, signal.SIGTSTP)
        wait_for(lambda: 'T' in subprocess.check_output(['ps', '-o', 'state=', '-p', str(pid)], text=True),
                 'viewer did not suspend')
        os.kill(pid, signal.SIGCONT)
        subprocess.run(['xdotool', 'windowsize', '--sync', win, '644', '420'], env=local, check=True)
        wait_for(painted, 'framebuffer missing after resume/resize')
        if args.exit_mode == 'signal':
            os.kill(pid, signal.SIGTERM)
        elif args.exit_mode == 'disconnect':
            server.terminate(); server.wait(timeout=5)
        else:
            subprocess.run(['xdotool', 'key', 'ctrl+bracketright', 'q'], env=local, check=True)
        wait_for(lambda: (args.records / 'modes-after.json').exists(), 'viewer did not restore terminal modes')
        assert (args.records / 'modes-before.json').read_bytes() == (args.records / 'modes-after.json').read_bytes(), 'xterm modes not restored'
        assert before.read_bytes() == after.read_bytes(), 'termios not restored'
        expected = '1' if args.exit_mode == 'disconnect' else '0'
        assert status.read_text().strip() == expected, (args.records / 'viewer.log').read_text()
        print('PASS: VNC/Sixel, input, resume/resize, restoration after ' + args.exit_mode)
finally:
    for p in reversed(processes):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill(); p.wait()
    log.close()
