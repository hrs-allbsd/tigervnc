#!/usr/bin/env python3
"""Measure adaptive palette quality and cost in an actual private xterm.

The default smooth warm gradient is a controlled fixture, not a photograph.
--image replaces it with a local image without imposing a quality winner.
Only numeric error and performance results are retained.
"""
import argparse
import hashlib
import importlib.util
import json
import math
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
parser.add_argument('--image', type=Path, help='Local public test image; never a private server capture')
args = parser.parse_args()
args.report.unlink(missing_ok=True)
spec = importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
w, h = 599, 431
rgb = bytes(channel for y in range(h) for x in range(w)
    for channel in (100+x*80//w,40+y*80//h,30+(x+y)*60//(w+h)))
metadata = {'kind': 'generated warm gradient'}
if args.image:
    source = args.image.read_bytes()
    rgb = subprocess.check_output(['magick',str(args.image.resolve()),
        '-auto-orient','-colorspace','sRGB','-resize',f'{w}x{h}!',
        '-alpha','off','-depth','8','rgb:-'])
    if len(rgb) != w*h*3:
        raise ValueError('Unexpected RGB image length')
    metadata = {'kind': 'external image, stretched to fixture dimensions',
        'source_sha256': hashlib.sha256(source).hexdigest(),
        'rgb_sha256': hashlib.sha256(rgb).hexdigest(), 'width': w, 'height': h}
bgra = b''.join(bytes((rgb[i+2],rgb[i+1],rgb[i],0)) for i in range(0,len(rgb),3))
results = {}
for name, photo, colors in [('fixed',False,256),('photo',True,256),('fixed8',False,8),('photo8',True,8)]:
    server = fixture.Server()
    processes = []
    def wait_for(check,label):
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            if server.error: raise server.error
            if check(): return
            time.sleep(.03)
        raise AssertionError((name,label))
    with tempfile.TemporaryDirectory() as directory, open(os.devnull,'wb') as null:
        try:
            r, fd = os.pipe()
            xvfb = subprocess.Popen(['Xvfb','-displayfd',str(fd),'-screen','0','1024x768x24',
                '-noreset','-nolisten','tcp'],pass_fds=(fd,),stdout=null,stderr=null)
            processes.append(xvfb); os.close(fd)
            assert select.select([r],[],[],10)[0]
            env = dict(os.environ,DISPLAY=':'+os.read(r,80).decode().strip()); os.close(r)
            for key in ('VNC_USERNAME','VNC_PASSWORD'): env.pop(key,None)
            pidfile, perf, statusfile = [Path(directory)/key for key in ('pid','perf','status')]
            wrapper = 'pidfile=$1; statusfile=$2; shift 2; "$@" <&0 & viewer_pid=$!; echo $viewer_pid > "$pidfile"; wait $viewer_pid; status=$?; echo $status > "$statusfile"; exit $status'
            terminal = subprocess.Popen(['xterm','-ti','vt340','-geometry','100x36+0+0',
                '-fa','monospace','-b','0','-bw','0','-bg','black','-fg','white',
                '-xrm','XTerm*allowSendEvents: false','-xrm','XTerm*numColorRegisters: '+str(colors),
                '-e','/bin/sh','-c',wrapper,'photo',str(pidfile),str(statusfile),
                str(args.viewer.resolve()),'-ViewOnly','-MaxFPS=30','-PerfLog='+str(perf),
                *(['-PhotoPalette'] if photo else []),'127.0.0.1::'+str(server.port)],
                env=env,stdout=null,stderr=null)
            processes.append(terminal)
            windows = []
            def find():
                found = subprocess.run(['xdotool','search','--onlyvisible','--class','XTerm'],env=env,text=True,capture_output=True)
                if found.returncode: return False
                windows[:] = [found.stdout.splitlines()[-1]]; return True
            wait_for(find,'xterm missing')
            def shot():
                data = subprocess.check_output(['xwd','-silent','-id',windows[0]],env=env)
                pixels = subprocess.check_output(['magick','xwd:-','-crop',f'{w}x{h}+0+0','+repage',
                    '-alpha','off','-depth','8','rgb:-'],input=data)
                assert len(pixels) == len(rgb), 'Incomplete screenshot'
                return pixels
            wait_for(lambda: server.sent >= 1,'initial update missing')
            def blue():
                image = shot()
                return image[0] < 24 and image[1] < 24 and image[2] > 220
            wait_for(blue,'initial image missing')
            initial = shot()
            server.update(0,0,w,h,bgra)
            image = [b'',0]
            def stable(predicate):
                current = shot()
                image[1] = image[1]+1 if current == image[0] and predicate(current) else 0
                image[0] = current
                return image[1] >= 4
            def rmse(image): return math.sqrt(sum((a-b)**2 for a,b in zip(rgb,image))/len(rgb))
            wait_for(lambda: stable(lambda data: data != initial and
                (bool(args.image) or rmse(data) < (12 if photo and colors==256 else 100))),
                'test image missing')
            gradient = image[0]
            error = rmse(gradient)
            if args.image:
                os.kill(int(pidfile.read_text()),signal.SIGTERM)
                terminal.wait(timeout=10)
                assert statusfile.read_text().strip() == '0', 'viewer exited unsuccessfully'
                metrics = json.loads(perf.read_text())
                assert metrics['updates'] == 2 and metrics['frames'] == 2, metrics
                results[name] = {'rmse_rgb':error,
                    'psnr_db':20*math.log10(255/error) if error else None,
                    'viewer':metrics}
                continue
            # Change the entire palette, then make a change hidden by RGB332.
            server.update(0,0,w,h,b'\x64\x64\x64\0'*w*h)
            image[1] = 0
            wait_for(lambda: stable(lambda data: len(set(zip(data[::3],data[1::3],data[2::3]))) == 1), 'uniform palette missing')
            before = image[0]
            server.update(0,0,200,200,b'\x68\x68\x68\0'*200*200)
            wait_for(lambda: server.sent >= 4,'subtle update missing')
            image[1] = 0
            if photo and colors==256:
                wait_for(lambda: stable(lambda data: data != before), 'sub-RGB332 change lost')
                # Nearby source colors can still share an adaptive entry.
            else:
                time.sleep(.2)
                assert shot() == before, 'fixed quantization unexpectedly changed'
            server.update(0,0,200,200,b'\xc8\xc8\0\0'*200*200)
            image[1] = 0
            def replaced(data):
                return data[0] < 24 and data[1] > 140 and data[2] > 140 and data[:3] != data[-3:]
            wait_for(lambda: stable(replaced), 'palette replacement left stale pixels')
            server.update_encoded([(0,0,320,210,-223,b'')])
            image[1] = 0
            def resized(data):
                inside = data[(100*w+100)*3:(100*w+100)*3+3]
                outside = data[(250*w+400)*3:(250*w+400)*3+3]
                return inside[0] < 24 and inside[1] > 140 and inside[2] > 140 and outside == b'\0\0\0'
            wait_for(lambda: stable(resized), 'resize did not clear old image')
            server.update_encoded([])
            wait_for(lambda: server.sent >= 7,'unchanged update missing')
            time.sleep(.2)
            os.kill(int(pidfile.read_text()),signal.SIGTERM); terminal.wait(timeout=10)
            assert statusfile.read_text().strip() == '0', 'viewer exited unsuccessfully'
            metrics = json.loads(perf.read_text())
            assert metrics['updates'] == 7 and metrics['skipped_frames'] >= 1, metrics
            if photo and colors==256:
                assert metrics['partial_frames'] == 0 and metrics['full_frames'] >= 6, metrics
                assert metrics['palette_ms'] > 0, metrics
            else: assert metrics['palette_ms'] == 0, metrics
            results[name] = {'rmse_rgb':error,'psnr_db':20*math.log10(255/error) if error else None,'viewer':metrics}
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            server.close()
if not args.image:
    assert results['photo']['rmse_rgb'] < results['fixed']['rmse_rgb']*.5, results
assert results['photo8']['rmse_rgb'] == results['fixed8']['rmse_rgb']
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'scope':('external-image xterm quality; viewer totals include initial blue frame plus test image'
    if args.image else 'generated gradient xterm quality; viewer totals include palette/resize regressions'),
    'fixture':metadata,'results':results},indent=2)+'\n')
print('PASS: external image rendered in four palette configurations' if args.image else
    'PASS: adaptive quality, palette replacement, subtle changes, resize, unchanged skip, full frames, eight-color fallback')
for name, value in results.items():
    metrics=value['viewer']
    print(name,'RMSE',round(value['rmse_rgb'],3),'CPU',metrics['cpu_seconds'],'bytes',metrics['encoded_bytes'],'palette_ms',metrics['palette_ms'])
