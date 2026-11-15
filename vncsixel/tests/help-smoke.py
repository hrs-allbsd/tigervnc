#!/usr/bin/env python3
"""Verify local help, isolated input and latest-frame restore in xterm."""
import argparse
import ctypes as C
import ctypes.util
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
parser.add_argument('--viewer-option', action='append', default=[])
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
x = C.CDLL(ctypes.util.find_library('X11'))
x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
x.XStoreBuffer.argtypes = [C.c_void_p,C.c_char_p,C.c_int,C.c_int]
x.XSync.argtypes = [C.c_void_p,C.c_int]
x.XCloseDisplay.argtypes = [C.c_void_p]
results = []
for mode in ('normal','view-only'):
    display = None
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
                '-fa', 'monospace', '-xrm', 'XTerm*allowSendEvents: false',
                '-xrm', 'XTerm*VT100.translations: #override <Key>F8: insert-selection(CUT_BUFFER0)', '-e', '/bin/sh', '-c',
                'echo $$ > "$1"; shift; exec "$@"', 'timing', str(pidfile), str(args.viewer.resolve()),
                *(['-ViewOnly'] if mode == 'view-only' else []), *args.viewer_option, '127.0.0.1::' + str(server.port)],
                env=env, stdout=null, stderr=null)
            processes.append(terminal)
            def wait_for(check, label):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if server.error: raise server.error
                    if check(): return
                    time.sleep(.01)
                raise AssertionError((mode,label,server.key_events))
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
            def shot():
                data = subprocess.check_output(['xwd','-silent','-id',windows[0]],env=env)
                return subprocess.check_output(['magick','xwd:-','-alpha','off','-depth','8','rgb:-'],input=data)
            def count(color):
                rgb = shot()
                channel = 2 if color == b'\0\0\xff' else 1
                return sum(rgb[i+channel] > 220 and all(rgb[i+c] < 24 for c in range(3) if c != channel)
                    for i in range(0,len(rgb),3))
            wait_for(lambda: count(b'\0\0\xff') >= 100, 'initial image not painted')
            def command(letter): key('ctrl+bracketright'); key(letter)
            time.sleep(.15)
            command('h')
            wait_for(lambda: count(b'\0\0\xff') == 0, 'help not painted')
            baseline = shot()
            before_keys, before_pointer = len(server.key_events), len(server.pointer_events)
            key('x')
            display = x.XOpenDisplay(env['DISPLAY'].encode()); assert display
            data = b'qq\r'
            x.XStoreBuffer(display,data,len(data),0); x.XSync(display,0)
            key('F8')
            subprocess.run(['xdotool','mousemove','--window',windows[0],'100','100','click','1'],env=env,check=True)
            server.update(96,96,96,78,b'\0\xff\0\0'*96*78)
            wait_for(lambda: server.sent >= 2, 'server update stalled in help')
            # Repeated equality checks guard against a delayed framebuffer draw.
            for _ in range(8):
                assert shot() == baseline, 'remote update overwrote help'
                time.sleep(.03)
            assert len(server.key_events) == before_keys, server.key_events
            assert len(server.pointer_events) == before_pointer, server.pointer_events
            key('Escape')
            wait_for(lambda: count(b'\0\xff\0') >= 5000, 'latest image missing after help')
            assert len(server.key_events) == before_keys, 'help Escape forwarded'
            command('h')
            wait_for(lambda: count(b'\0\xff\0') == 0, 'help did not reopen')
            subprocess.run(['xdotool','windowsize','--usehints',windows[0],'40','12'],env=env,check=True)
            # Wait for geometry queries, then verify next/previous page pixels.
            settled = [b'',0]
            def stable():
                current = shot()
                settled[1] = settled[1]+1 if current == settled[0] else 0
                settled[0] = current
                return settled[1] >= 8
            wait_for(stable, 'resized help did not settle')
            first = shot(); key('space')
            wait_for(lambda: shot() != first, 'small-window help did not page')
            key('p'); wait_for(lambda: shot() == first, 'previous page differs')
            # Suspension should preserve the local screen on resume.
            os.kill(int(pidfile.read_text()),signal.SIGTSTP)
            wait_for(lambda: 'T' in subprocess.check_output(['ps','-o','state=','-p',pidfile.read_text().strip()],text=True), 'did not suspend')
            os.kill(int(pidfile.read_text()),signal.SIGCONT)
            wait_for(lambda: shot() == first, 'help not restored after resume')
            command('q'); terminal.wait(timeout=5)
            results.append({'mode':mode,'checks':['help open','remote update retained',
                'keyboard/mouse/paste isolated','Escape returns latest image','resize and paging',
                'suspend/resume','local quit']})
        finally:
            if display: x.XCloseDisplay(display)
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            server.close()
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'checks':results},indent=2)+'\n')
print('PASS: local help, input isolation, latest image, resize/paging, suspend, quit, ViewOnly')
