#!/usr/bin/env python3
"""Run deterministic rectangle-capacity checks across encodings and entropy."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report-dir', type=Path, required=True)
parser.add_argument('--mixed', action='store_true', help='Add mixed Raw/Tight/ZRLE/filter cases')
parser.add_argument('--jpeg', action='store_true', help='Add a mixed JPEG case; requires --mixed and cjpeg')
parser.add_argument('--repeat-cycles', type=int, default=3)
args = parser.parse_args()
if not 1 <= args.repeat_cycles <= 100:
    parser.error('--repeat-cycles must be 1..100')
if args.jpeg and not args.mixed:
    parser.error('--jpeg requires --mixed')
args.report_dir.mkdir(parents=True, exist_ok=True)
summary = args.report_dir/'summary.json'
summary.unlink(missing_ok=True)
cases = [(encoding,content,False,False) for encoding in ('raw','tight','zrle')
         for content in ('solid','noise')]+[('tight','noise',True,False)]
if args.mixed:
    cases += [('mixed',content,False,False) for content in ('solid','noise')]
if args.jpeg:
    cases.append(('mixed','noise',False,True))
results = []
# Serial execution avoids competing local workloads when comparing allocation
# samples.  These short runs still do not demonstrate multi-hour stability.
for encoding,content,reset,jpeg in cases:
    name = encoding+'-'+content+('-reset' if reset else '')+('-jpeg' if jpeg else '')
    report = args.report_dir/(name+'.json')
    report.unlink(missing_ok=True)
    command = [sys.executable,str(Path(__file__).with_name('decoder-memory.py')),
               str(args.viewer.resolve()),'--encoding',encoding,'--content',content,
               '--repeat-cycles',str(args.repeat_cycles),'--report',str(report)]
    if reset: command.append('--reset-streams')
    if jpeg: command.append('--jpeg')
    with (args.report_dir/(name+'.log')).open('w') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    data = json.loads(report.read_text())
    phases = data['phases']
    assert len(phases)==2+args.repeat_cycles
    capacity = phases[0]['decoder_buffer_bytes']
    assert all(p['decoder_buffer_bytes']==capacity for p in phases), name
    results.append({'case':name,'capacity_bytes':capacity,
        'max_wire_bytes':data['max_wire_bytes'],'updates':data['viewer']['updates'],
        'allocated_phase_bytes':[p.get('allocated_bytes') for p in phases],
        'rss_phase_kib':[p['rss_kib'] for p in phases],
        'coverage':data['coverage'], 'seconds':data['measurement_seconds']})
summary.write_text(json.dumps({'cases':results,
    'updates':sum(r['updates'] for r in results),
    'scope':'Serial private xterm; fragmented loopback updates; retained staging '
            'capacity, not general leak freedom or pixel validation'},indent=2)+'\n')
print(f'PASS: {len(results)} configurations, {sum(r["updates"] for r in results)} updates')
