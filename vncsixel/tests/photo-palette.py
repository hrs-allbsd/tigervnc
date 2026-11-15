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
parser.add_argument('--pan-frames', type=int, default=0,
    help='Additional cyclic horizontal shifts, 0..60; requires --image')
parser.add_argument('--return-image', action='store_true',
    help='Return to the original image after panning and compare pixels')
parser.add_argument('--pan-rate', type=float, default=0,
    help='Paced producer updates/second, 1..120; requires --return-image')
args = parser.parse_args()
if args.pan_rate and (not 1 <= args.pan_rate <= 120 or not args.return_image):
    parser.error('--pan-rate must be 1..120 and requires --return-image')
if args.return_image and (not args.image or not args.pan_frames):
    parser.error('--return-image requires --image and nonzero --pan-frames')
if not 0 <= args.pan_frames <= 60 or (args.pan_frames and not args.image):
    parser.error('--pan-frames must be 0..60 and requires --image')
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
def wire(pixels):
    return b''.join(bytes((pixels[i+2],pixels[i+1],pixels[i],0))
        for i in range(0,len(pixels),3))
def fixed_pixels(pixels, colors):
    tables = []
    for channel in range(3):
        levels = 2 if colors == 8 else (4 if channel == 2 else 8)
        table = []
        for value in range(256):
            level = min(range(levels),
                key=lambda i: (abs(value-i*255//(levels-1)),i))
            palette = level*255//(levels-1)
            percent = (palette*100+127)//255
            # Allow one display channel level for xterm rounding below.
            table.append((percent*255+50)//100)
        tables.append(bytes(table))
    output = bytearray(len(pixels))
    for channel in range(3):
        output[channel::3] = pixels[channel::3].translate(tables[channel])
    return bytes(output)

def shift_pixels(pixels, offset):
    offset = (offset % w)*3
    return b''.join(pixels[row*w*3+offset:(row+1)*w*3] +
        pixels[row*w*3:row*w*3+offset] for row in range(h))

def difference(a, b):
    assert len(a) == len(b) and len(a) % 3 == 0
    squares = sum((x-y)**2 for x,y in zip(a,b))
    return {'rmse_rgb': math.sqrt(squares/len(a)),
        'max_channel_delta': max(abs(x-y) for x,y in zip(a,b)),
        'changed_pixels': sum(a[i:i+3] != b[i:i+3]
            for i in range(0,len(a),3))}

bgra = wire(rgb)
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
                if not photo or colors == 8:
                    assert max(abs(a-b) for a,b in zip(image[0],fixed_pixels(rgb,colors))) <= 1, 'Fixed image pixel mismatch'
                errors = [error]
                original = rgb
                original_display = image[0]
                aligned_previous = original_display
                temporal = []
                pacing = None
                if args.pan_rate:
                    # Conversion is outside the measured producer interval.
                    packets = [wire(shift_pixels(original,step*17))
                        for step in range(1,args.pan_frames+1)]
                    queued = []
                    started = time.monotonic()
                    for index,packet in enumerate(packets):
                        target = started+index/args.pan_rate
                        time.sleep(max(0,target-time.monotonic()))
                        deadline = time.monotonic()+20
                        with server.condition:
                            while server.pending is not None:
                                if server.error: raise server.error
                                if time.monotonic() >= deadline:
                                    raise AssertionError('paced server backpressure timeout')
                                server.condition.wait(.01)
                            server.update(0,0,w,h,packet)
                        queued.append(time.monotonic()-started)
                    wait_for(lambda: server.sent >= 2+args.pan_frames,
                        'paced updates not sent')
                    image[1] = 0
                    wait_for(lambda: stable(lambda data: data != original_display),
                        'paced final image missing')
                    final = shift_pixels(original,args.pan_frames*17)
                    if not photo or colors == 8:
                        assert max(abs(a-b) for a,b in zip(image[0],fixed_pixels(final,colors))) <= 1
                    pacing = {'requested_hz':args.pan_rate,
                        'queued_seconds':queued,
                        'max_schedule_lateness_ms':1000*max(t-i/args.pan_rate
                            for i,t in enumerate(queued)),
                        'final_observed_seconds':time.monotonic()-started,
                        'observation':'final frame only; screenshot/stability overhead included'}
                for step in range(1,0 if args.pan_rate else args.pan_frames+1):
                    rgb = shift_pixels(original,step*17)
                    previous = image[0]
                    image[1] = 0
                    server.update(0,0,w,h,wire(rgb))
                    wait_for(lambda: stable(lambda data: data != previous),
                        'pan frame missing')
                    if not photo or colors == 8:
                        assert max(abs(a-b) for a,b in zip(image[0],fixed_pixels(rgb,colors))) <= 1, 'Fixed pan pixel mismatch'
                    errors.append(rmse(image[0]))
                    aligned = shift_pixels(image[0],-step*17)
                    temporal.append(difference(aligned_previous,aligned))
                    aligned_previous = aligned
                rgb = original
                returned = None
                if args.return_image:
                    previous = image[0]
                    image[1] = 0
                    server.update(0,0,w,h,bgra)
                    wait_for(lambda: server.sent >= 3+args.pan_frames, 'return update not sent')
                    wait_for(lambda: stable(lambda data: data == original_display),
                        'original image did not return')
                    returned = difference(original_display,image[0])
                    assert returned['changed_pixels'] == 0, returned
                os.kill(int(pidfile.read_text()),signal.SIGTERM)
                terminal.wait(timeout=10)
                assert statusfile.read_text().strip() == '0', 'viewer exited unsuccessfully'
                metrics = json.loads(perf.read_text())
                assert metrics['updates'] == 2+args.pan_frames+int(args.return_image), metrics
                if args.pan_rate:
                    assert 3 <= metrics['frames'] <= metrics['updates'], metrics
                    pacing['updates_minus_frames'] = metrics['updates']-metrics['frames']
                else:
                    assert metrics['frames'] == 2+args.pan_frames+int(args.return_image), metrics
                results[name] = {'rmse_rgb':error,'frame_rmse_rgb':errors,
                    'aligned_frame_differences':temporal,'return_difference':returned,
                    'pacing':pacing,
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
if args.image:
    assert results['photo8']['frame_rmse_rgb'] == results['fixed8']['frame_rmse_rgb']
    for name in ('fixed','fixed8','photo8'):
        assert all(item['changed_pixels'] == 0 for item in
            results[name]['aligned_frame_differences']), results[name]
    metadata['return_image'] = args.return_image
    metadata['pan_frames'] = args.pan_frames
    metadata['pan_step_pixels'] = 17
    metadata['pacing'] = ('deadline producer, single pending update backpressure; no intermediate screenshots'
        if args.pan_rate else 'wait for changed stable xterm pixels after every frame; not video FPS')
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'scope':('external-image xterm quality; viewer totals include initial blue frame plus test image and optional cyclic shifts'
    if args.image else 'generated gradient xterm quality; viewer totals include palette/resize regressions'),
    'fixture':metadata,'results':results},indent=2)+'\n')
print('PASS: external image rendered in four palette configurations' if args.image else
    'PASS: adaptive quality, palette replacement, subtle changes, resize, unchanged skip, full frames, eight-color fallback')
for name, value in results.items():
    metrics=value['viewer']
    print(name,'RMSE',round(value['rmse_rgb'],3),'CPU',metrics['cpu_seconds'],'bytes',metrics['encoded_bytes'],'palette_ms',metrics['palette_ms'])
