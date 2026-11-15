#!/usr/bin/env python3
"""Compare two viewer binaries on serialized local sparse-update workloads."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--report-dir', type=Path, required=True)
parser.add_argument('--repeats', type=int, default=3)
args = parser.parse_args()
if not 1 <= args.repeats <= 9: parser.error('--repeats must be 1..9')
args.report_dir.mkdir(parents=True, exist_ok=True)
summary = args.report_dir/'summary.json'
summary.unlink(missing_ok=True)
viewers = {'baseline':args.baseline.resolve(),'candidate':args.candidate.resolve()}
if not all(p.is_file() for p in viewers.values()): parser.error('viewer does not exist')
results = []
for textured in (False,True):
    name = 'textured' if textured else 'solid'
    trials = {key:[] for key in viewers}
    for trial in range(args.repeats):
        order = ['baseline','candidate'] if trial%2==0 else ['candidate','baseline']
        for key in order:
            report = args.report_dir/f'{name}-{key}-{trial+1}.json'
            report.unlink(missing_ok=True)
            command = [sys.executable,str(Path(__file__).with_name('regions-benchmark.py')),
                       str(viewers[key]),'--report',str(report)]
            if textured: command.append('--textured')
            with report.with_suffix('.log').open('w') as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
            data = json.loads(report.read_text())
            assert data['updates']==41, data
            trials[key].append({k:data[k] for k in ('frames','regions','encoded_pixels',
                'encoded_bytes','encode_ms','cpu_seconds','tty_bytes')})
    # Compare output only when all trials rendered the same amount of work.
    work = {(r['frames'],r['regions'],r['encoded_pixels']) for t in trials.values() for r in t}
    results.append({'case':name,'comparable':len(work)==1,'trials':trials,
        'median':{key:{field:statistics.median(r[field] for r in trials[key])
            for field in trials[key][0]} for key in trials}})
summary.write_text(json.dumps({'cases':results,'repeats':args.repeats,
    'scope':'Serialized private xterm; 41 local updates per trial; '
            'synthetic sparse work, not WAN latency or viewer throughput'},indent=2)+'\n')
print(f'PASS: {len(results)} workloads, {args.repeats*2*len(results)} trials')
