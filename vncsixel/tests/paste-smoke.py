#!/usr/bin/env python3
"""Verify paced bracketed paste, ordering and cancellation in xterm."""
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
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
x = C.CDLL(ctypes.util.find_library('X11'))
x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
x.XStoreBuffer.argtypes = [C.c_void_p,C.c_char_p,C.c_int,C.c_int]
x.XFlush.argtypes = [C.c_void_p]
x.XSync.argtypes = [C.c_void_p,C.c_int]
x.XCloseDisplay.argtypes = [C.c_void_p]
x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
x.XCreateSimpleWindow.argtypes = [C.c_void_p,C.c_ulong,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_uint,C.c_ulong,C.c_ulong]
x.XCreateSimpleWindow.restype = C.c_ulong
x.XMapWindow.argtypes = [C.c_void_p,C.c_ulong]
x.XSetInputFocus.argtypes = [C.c_void_p,C.c_ulong,C.c_int,C.c_ulong]
results = []
for mode in ('normal', 'view-only'):
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
                '-PasteRate=40', *(['-ViewOnly'] if mode == 'view-only' else []), '127.0.0.1::' + str(server.port)],
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
            display = x.XOpenDisplay(env['DISPLAY'].encode()); assert display
            def paste(text):
                data = text.encode('ascii')
                x.XStoreBuffer(display,data,len(data),0); x.XSync(display,0)
                key('F8')
            def downs(): return [(stamp,code) for stamp,down,code in server.key_events if down]
            # Wait for the first paint and input enable before testing paste.
            if mode == 'view-only':
                time.sleep(.2)
                paste('abc' * 50); key('z'); time.sleep(.2)
                assert not server.key_events, server.key_events
                results.append({'case':'ViewOnly suppresses paste and keys'})
            else:
                key('a')
                wait_for(lambda: any(code == ord('a') for _,code in downs()), 'input not ready')
                server.key_events.clear()
                text = 'abcdefghij' * 4
                paste(text)
                wait_for(lambda: bool(downs()), 'selection paste did not arrive')
                key('z')
                wait_for(lambda: any(code == ord('z') for _,code in downs()), 'paste did not drain')
                events = downs()
                assert [code for _,code in events] == list(map(ord,text+'z')), events
                span = (events[-2][0]-events[0][0])/1e9
                assert span >= (len(text)-1)/40 - .03, span
                results.append({'case':'paced paste then typed key in order','characters':len(text),'seconds':span})
                server.key_events.clear()
                key('ctrl+bracketright'); key('c')
                paste('ee')
                wait_for(lambda: any(code == ord('e') for _,code in downs()), 'selection paste did not arrive')
                key('x')
                wait_for(lambda: any(code == ord('x') for _,code in downs()), 'latched input missing')
                control = False; observed = []
                for _,down,code in server.key_events:
                    if code == 0xffe3: control = bool(down)
                    elif down and code in (ord('e'),ord('x')): observed.append((code,control))
                assert observed == [(ord('e'),False),(ord('e'),False),(ord('x'),True)], observed
                key('ctrl+bracketright'); key('c')
                results.append({'case':'paste excludes latched modifiers; queued typing retains them'})
                server.key_events.clear()
                key('ctrl+bracketright')
                paste('q')
                wait_for(lambda: any(code == ord('q') for _,code in downs()), 'pasted q invoked local prefix')
                assert terminal.poll() is None
                results.append({'case':'paste cannot complete a local command prefix'})
                server.key_events.clear()
                paste('b' * 200)
                wait_for(lambda: len(downs()) >= 5, 'paste did not start')
                server.update(96,96,24,24,b'\0\0\xff\0'*24*24)
                def response_painted():
                    data = subprocess.check_output(['xwd','-silent','-id',windows[0]],env=env)
                    rgb = subprocess.check_output(['magick','xwd:-','-alpha','off','-depth','8','rgb:-'],input=data)
                    return rgb.count(b'\xff\0\0') >= 500
                wait_for(response_painted, 'drawing stalled during paste')
                assert len(downs()) < 200
                results.append({'case':'RFB decoding and xterm painting continue during paste'})
                key('ctrl+bracketright'); key('u')
                time.sleep(.1); count = len(downs()); time.sleep(.15)
                assert len(downs()) == count and count < 200, downs()
                key('z'); wait_for(lambda: downs()[-1][1] == ord('z'), 'cancel left queue stuck')
                results.append({'case':'local cancel bypasses pending paste','sent_before_cancel':count})
                server.key_events.clear()
                paste('f' * 200)
                wait_for(lambda: len(downs()) >= 3, 'focus paste did not start')
                other = x.XCreateSimpleWindow(display,x.XDefaultRootWindow(display),900,700,50,30,0,0,0)
                x.XMapWindow(display,other); x.XSetInputFocus(display,other,2,0); x.XFlush(display)
                time.sleep(.1); count = len(downs()); time.sleep(.15)
                assert len(downs()) == count and count < 200
                x.XSetInputFocus(display,int(windows[0]),2,0); x.XFlush(display)
                time.sleep(.1)
                key('z'); wait_for(lambda: downs()[-1][1] == ord('z'), 'focus cancel left queue stuck')
                results.append({'case':'focus loss cancels queued paste','sent_before_focus_loss':count})
                server.key_events.clear()
                paste('c' * 20000)
                time.sleep(.2)
                count = len(downs())
                assert count < 30, count
                key('z'); wait_for(lambda: downs()[-1][1] == ord('z'), 'overflow did not recover')
                time.sleep(.1)
                assert downs()[-1][1] == ord('z'), downs()
                results.append({'case':'overflow cancels and recovers','sent_before_overflow':count})
                server.key_events.clear()
                paste('d' * 200)
                wait_for(lambda: len(downs()) >= 3, 'second paste did not start')
                start = time.monotonic()
                key('ctrl+bracketright'); key('q')
                terminal.wait(timeout=3)
                assert time.monotonic()-start < 1.5
                results.append({'case':'quit bypasses pending paste'})
                continue
            os.kill(int(pidfile.read_text()),signal.SIGTERM); terminal.wait(timeout=10)
        finally:
            if display: x.XCloseDisplay(display)
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            server.close()
for value in ('0','10001','-1'):
    result = subprocess.run([str(args.viewer.resolve()), '-PasteRate='+value, '127.0.0.1'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert result.returncode != 0
    assert b'Invalid argument' in result.stderr, result.stderr
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'checks':results,'invalid_values_rejected':[0,10001,-1]},indent=2)+'\n')
print('PASS: paced paste, key ordering, cancel, overflow, quit, ViewOnly, bounds')
