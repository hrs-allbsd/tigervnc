#!/usr/bin/env python3
"""Check encoding hints on the wire using a private RFB server and xterm."""
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

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer',type=Path)
parser.add_argument('--report',required=True,type=Path)
args=parser.parse_args()
viewer=args.viewer.resolve()
spec=importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('rfb-fixture.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
checks=[]
with tempfile.TemporaryDirectory() as directory, open(os.devnull,'wb') as null:
    root=Path(directory)
    r,w=os.pipe()
    display=subprocess.Popen(['Xvfb','-displayfd',str(w),'-screen','0','800x600x24',
        '-noreset','-nolisten','tcp'],pass_fds=(w,),stdout=null,stderr=null)
    os.close(w)
    try:
        assert select.select([r],[],[],10)[0],'Xvfb timeout'
        env=dict(os.environ,DISPLAY=':'+os.read(r,80).decode().strip());os.close(r)
        for name in ('VNC_USERNAME','VNC_PASSWORD'):env.pop(name,None)
        cases=[('defaults',[],None,None,False),
            ('lowest',['-QualityLevel=0','-CompressLevel=0'],0,0,False),
            ('highest',['-QualityLevel=9','-CompressLevel=9'],9,9,False),
            ('split options',['-QualityLevel','8','-CompressLevel','2'],8,2,False),
            ('case insensitive',['--qualitylevel=6','compresslevel=3'],6,3,False),
            ('disabled hints',['-QualityLevel=-1','-CompressLevel=-1'],None,None,False),
            ('last option wins',['-QualityLevel=9','-QualityLevel=-1','-CompressLevel=0','-CompressLevel=9'],None,9,False),
            ('NoJPEG suppresses quality',['-QualityLevel=8','-CompressLevel=2','-NoJPEG'],None,2,True),
            ('NoJPEG cleared',['-NoJPEG','-NoJPEG=0','-QualityLevel=8'],8,None,False)]
        for label,options,quality,compression,no_jpeg in cases:
            server=fixture.Server(width=32,height=24)
            pidfile=root/'pid';pidfile.unlink(missing_ok=True)
            wrapper='echo $$ > "$1"; shift; exec "$@"'
            terminal=subprocess.Popen(['xterm','-ti','vt340','-e','/bin/sh','-c',wrapper,
                'encodings',str(pidfile),str(viewer),'-ViewOnly',*options,
                '127.0.0.1::'+str(server.port)],env=env,stdout=null,stderr=null)
            try:
                deadline=time.monotonic()+10
                while not server.encodings:
                    assert time.monotonic()<deadline,(label,'encoding negotiation timeout')
                    if server.error:raise server.error
                    time.sleep(.01)
                qualities={e+32 for e in server.encodings if -32<=e<=-23}
                compressions={e+256 for e in server.encodings if -256<=e<=-247}
                assert qualities==({quality} if quality is not None else set()),(label,qualities)
                assert compressions==({compression} if compression is not None else set()),(label,compressions)
                assert (21 in server.encodings)==(not no_jpeg),(label,'standalone JPEG capability')
                checks.append(label)
            finally:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()),signal.SIGTERM)
                    except ProcessLookupError:pass
                if terminal.poll() is None:
                    try:terminal.wait(timeout=5)
                    except subprocess.TimeoutExpired:terminal.kill();terminal.wait()
                server.close()
        for parameter in ('QualityLevel','CompressLevel'):
            for value in (-2,10):
                result=subprocess.run([str(viewer),f'-{parameter}={value}','127.0.0.1::1'],
                    stdin=subprocess.DEVNULL,capture_output=True,timeout=5)
                assert result.returncode!=0 and b'Invalid argument' in result.stderr,(parameter,value,result.stderr)
                checks.append(f'{parameter}={value} rejected')
    finally:
        display.terminate();display.wait(timeout=5)
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'checks':checks,'scope':'private RFB/xterm encoding negotiation; no credentials'},indent=2)+'\n')
print(f'PASS: {len(checks)} encoding option cases')
