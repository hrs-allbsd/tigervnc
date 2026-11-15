#!/usr/bin/env python3
"""Check zoom/pan pixels and remote input in private xterms (local fixture only)."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report', required=True, type=Path)
parser.add_argument('--view-only', action='store_true')
parser.add_argument('--photo', action='store_true')
args = parser.parse_args()
args.report.unlink(missing_ok=True)
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('rfb-fixture.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
rw, rh, tw, th = 599, 431, 320, 246
# Eight exact palette corners, with an asymmetric spatial pattern.
source = bytes(c for y in range(rh) for x in range(rw)
    for c in (255 if (x//17+y//13)&1 else 0,
              255 if (x//31+y//19)&1 else 0, 255 if (x//11+y//23)&1 else 0))
bgra = b''.join(bytes((source[i+2],source[i+1],source[i],0)) for i in range(0,len(source),3))
server = fixture.Server(on_key=lambda *args: None)
processes, checks = [], []
vw, vh, ox, oy = 320, int(rh*320/rw), 0, 0
follow = True
cursor_position = None

def wait(check, label):
    deadline = time.monotonic()+20
    while time.monotonic()<deadline:
        if server.error: raise server.error
        if check(): return
        if any(p.poll() is not None for p in processes): raise AssertionError('private process exited: '+label)
        time.sleep(.03)
    raise AssertionError(label)

def expected():
    out = bytearray(tw*th*3)
    for y in range(min(th,vh)):
        sy = (y+oy)*rh//vh
        for x in range(min(tw,vw)):
            sx = (x+ox)*rw//vw
            at = (y*tw+x)*3
            if cursor_position and cursor_position[0] <= sx < cursor_position[0]+2 and cursor_position[1] <= sy < cursor_position[1]+2:
                out[at:at+3] = b'\xff\0\xff'
            else:
                out[at:at+3] = source[(sy*rw+sx)*3:(sy*rw+sx)*3+3]
    return bytes(out)

def center(px, py):
    global ox, oy
    ox = max(0,min(vw-min(tw,vw),px*vw//rw-min(tw,vw)//2))
    oy = max(0,min(vh-min(th,vh),py*vh//rh-min(th,vh)//2))

with tempfile.TemporaryDirectory() as d, open(os.devnull,'wb') as null:
    pid,status = Path(d)/'pid',Path(d)/'status'
    terminal = None
    try:
        r,fd = os.pipe()
        xvfb = subprocess.Popen(['Xvfb','-displayfd',str(fd),'-screen','0','1024x768x24','-noreset','-nolisten','tcp'],pass_fds=(fd,),stdout=null,stderr=null)
        processes.append(xvfb);os.close(fd)
        assert select.select([r],[],[],10)[0]
        env=dict(os.environ,DISPLAY=':'+os.read(r,80).decode().strip());os.close(r)
        for key in ('VNC_USERNAME','VNC_PASSWORD'):env.pop(key,None)
        pid,status = Path(d)/'pid',Path(d)/'status'
        wrapper='pidfile=$1; statusfile=$2; shift 2; "$@" <&0 & p=$!; echo $p > "$pidfile"; wait $p; status=$?; echo $status > "$statusfile"; exit $status'
        terminal=subprocess.Popen(['xterm','-ti','vt340','-geometry','100x36+0+0','-fa','monospace','-b','0','-bw','0','-bg','black',
            '-xrm','XTerm*allowSendEvents: false','-e','/bin/sh','-c',wrapper,'zoom',str(pid),str(status),
            str(args.viewer.resolve()),'-PixelSize=320x270','-CellSize=8x16',
            *(['-ViewOnly'] if args.view_only else []),*(['-PhotoPalette'] if args.photo else []),
            '127.0.0.1::'+str(server.port)],env=env,stdout=null,stderr=null)
        processes.append(terminal)
        window=[]
        def find():
            r=subprocess.run(['xdotool','search','--onlyvisible','--class','XTerm'],env=env,capture_output=True,text=True)
            if r.returncode:return False
            window[:]=[r.stdout.splitlines()[-1]];return True
        wait(find,'xterm missing')
        subprocess.run(['xdotool','windowfocus','--sync',window[0]],env=env,check=True)
        def shot():
            raw=subprocess.check_output(['xwd','-silent','-id',window[0]],env=env)
            return subprocess.check_output(['magick','xwd:-','-crop',f'{tw}x{th}+0+0','+repage','-alpha','off','-depth','8','rgb:-'],input=raw)
        wait(lambda:server.sent>=1 and pid.exists(),'initial update missing')
        def blue():
            data=shot()
            return data[0]<24 and data[1]<24 and data[2]>220
        wait(blue,'initial frame missing')
        server.update(0,0,rw,rh,bgra)
        def pixels(label):
            want=expected()
            def matches():
                data=shot()
                return len(data)==len(want) and (
                    max(abs(a-b) for a,b in zip(data,want)) <= 8
                    if args.photo else data==want)
            wait(matches,label)
            checks.append(label)
        def command(key):
            subprocess.run(['xdotool','key','ctrl+bracketright',key],env=env,check=True)
        pixels('fit')
        # Anchor at the initial remote pointer (0,0).
        command('0');vw,vh=rw,rh;center(0,0);pixels('pixel-perfect')
        command('Right');ox=min(vw-tw,ox+tw//4);follow=False;pixels('manual pan right')
        command('Down');oy=min(vh-th,oy+th//4);pixels('manual pan down')
        # A key/button selection in this crop must address the sampled source.
        subprocess.run(['xdotool','mousemove','--window',window[0],'100','80','click','1'],env=env,check=True)
        px,py=ox+100,oy+80
        if not args.view_only:
            wait(lambda:any(struct.unpack('!BHH',e)==(1,px,py) for e in server.pointer_events),'cropped click coordinates')
            checks.append('cropped click coordinates')
        else:
            px=py=0
        command('equal');vw,vh=rw*150//100,rh*150//100;center(px,py);pixels('150 percent')
        command('minus');vw,vh=rw,rh;center(px,py);pixels('zoom out')
        command('f');vw,vh=320,int(rh*320/rw);ox=oy=0;pixels('fit restored and old area erased')
        # Returning to 100% preserves the known anchor.
        command('0');vw,vh=rw,rh;center(px,py);pixels('100 percent restored')
        if not args.view_only:
            oldx,oldy=ox,oy
            # Fixed mode must leave the viewport stationary at the edge.
            subprocess.run(['xdotool','mousemove','--window',window[0],'310','120'],env=env,check=True)
            target=(oldx+310,oldy+120)
            wait(lambda:any(struct.unpack('!BHH',e)[1:]==target for e in server.pointer_events),'fixed edge motion')
            pixels('fixed edge does not pan')
            command('p');ox=max(0,min(vw-tw,target[0]-tw//2));pixels('follow enabled recenters edge')
            # Motion in the middle must not change the viewport.
            subprocess.run(['xdotool','mousemove','--window',window[0],'160','123'],env=env,check=True)
            time.sleep(.15);pixels('follow dead zone')
        # A remote cursor uses the same crop/scale as the background.
        cursor_position=((ox+min(tw,vw)//2)*rw//vw,(oy+min(th,vh)//2)*rh//vh)
        advertised_pointer=cursor_position
        server.update_encoded([(0,0,2,2,-239,b'\xff\0\xff\0'*4+b'\xc0\xc0'),
            (*cursor_position,0,0,0x574d5666,b'')])
        pixels('cursor in cropped viewport')
        # Keep the cursor centered as the background is magnified.
        command('equal')
        vw,vh=rw*150//100,rh*150//100;center(*cursor_position)
        pixels('magnified cursor and background')
        server.update_encoded([(0,0,0,0,-239,b'')])
        cursor_position=None
        pixels('cursor removal restores magnified background')
        command('0');vw,vh=rw,rh
        center(*advertised_pointer)
        pixels('100 percent after cursor')
        # A remote framebuffer resize must clamp the current cropped view.
        cx,cy=(ox+min(tw,vw)//2)*rw//vw,(oy+min(th,vh)//2)*rh//vh
        original,oldrw=source,rw
        rw,rh=401,301
        source=b''.join(original[y*oldrw*3:y*oldrw*3+rw*3] for y in range(rh))
        resized=b''.join(bytes((source[i+2],source[i+1],source[i],0)) for i in range(0,len(source),3))
        server.update_encoded([(0,0,rw,rh,-223,b''),(0,0,rw,rh,0,resized)])
        vw,vh=rw,rh;center(cx,cy);pixels('remote resize clamps cropped view')
        command('f');vw,vh=tw,int(rh*tw/rw);ox=oy=0;pixels('fit after remote resize')
        # Every command is local; no zoom/pan command may become a remote key.
        assert not server.key_events,server.key_events
        if args.view_only:assert not server.pointer_events,server.pointer_events
        command('q');terminal.wait(timeout=10)
        assert status.read_text().strip()=='0'
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({'checks':checks,'view_only':args.view_only,'photo':args.photo,'scope':'local synthetic xterm pixels and input; no real server'},indent=2)+'\n')
        print('PASS:',len(checks),'zoom/pan checks; view_only',args.view_only,'photo',args.photo)
    finally:
        if pid.exists() and terminal is not None and terminal.poll() is None:
            try:os.kill(int(pid.read_text()),signal.SIGTERM)
            except ProcessLookupError:pass
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        server.close()
