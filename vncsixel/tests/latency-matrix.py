#!/usr/bin/env python3
"""Sequential synthetic-delay input measurements; no real server input."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer',type=Path)
parser.add_argument('--report-dir',required=True,type=Path)
parser.add_argument('--samples',type=int,default=30)
parser.add_argument('--application-ms',type=float,default=25)
args=parser.parse_args()
if args.samples<5:parser.error('--samples must be at least 5')
if not 0<=args.application_ms<=1000:parser.error('--application-ms must be 0..1000')
viewer=args.viewer.resolve()
if not viewer.is_file():parser.error('viewer does not exist')
args.report_dir.mkdir(parents=True,exist_ok=True)
summary=args.report_dir/'summary.json';summary.unlink(missing_ok=True)
script=Path(__file__).with_name('input-latency.py')
results=[]
# Deliberately serial: parallel display workloads would skew comparisons.
for delay,fps in ((0,10),(0,30),(50,10),(50,30)):
    name=f'delay{delay}-fps{fps}'
    report=args.report_dir/(name+'.json')
    with (args.report_dir/(name+'.log')).open('w') as log:
        subprocess.run([sys.executable,str(script),str(viewer),'--samples',str(args.samples),
            '--one-way-ms',str(delay),'--application-ms',str(args.application_ms),
            '--viewer-option=-MaxFPS='+str(fps),'--report',str(report)],
            stdout=log,stderr=subprocess.STDOUT,check=True)
    data=json.loads(report.read_text())
    assert min(data['latencies_ms'])>=2*delay+args.application_ms
    assert data['key_events']==2*(data['samples']+2)
    assert all(v<=data['link']['queue_limit_bytes'] for v in data['link']['peak_queued_bytes'])
    result={key:data[key] for key in ('one_way_ms','samples','median_ms','p95_ms','max_ms',
        'rfb_dispatch_median_ms','application_median_ms','response_median_ms')}
    result['max_fps']=fps
    results.append(result)
summary.write_text(json.dumps({'profiles':results,'scope':'Fixed loopback delay and synthetic '
    'application; no WAN congestion, packet loss or physical display latency'},indent=2)+'\n')
print(f'PASS: {len(results)} profiles, {sum(r["samples"] for r in results)} measured responses')
