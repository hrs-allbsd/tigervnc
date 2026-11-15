#!/usr/bin/env python3
"""Repeat private VNC/xterm startup and initial-pixel checks with diagnostics."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report-dir', type=Path, required=True)
parser.add_argument('--attempts', type=int, default=20)
parser.add_argument('--jobs', type=int, default=2)
args = parser.parse_args()
if not 1 <= args.attempts <= 200: parser.error('--attempts must be 1..200')
if not 1 <= args.jobs <= 3: parser.error('--jobs must be 1..3')
if not args.viewer.is_file(): parser.error('viewer does not exist')
args.report_dir.mkdir(parents=True, exist_ok=True)
summary = args.report_dir/'summary.json'
summary.unlink(missing_ok=True)
def run(index):
    name = f'{index+1:03d}'
    report, diagnostic = [args.report_dir/(name+suffix) for suffix in ('.json','-startup.json')]
    report.unlink(missing_ok=True); diagnostic.unlink(missing_ok=True)
    command = [sys.executable,str(Path(__file__).with_name('protocol-smoke.py')),
        str(args.viewer.resolve()),'--report',str(report),'--startup-only',
        '--startup-report',str(diagnostic),'--colors','8' if index%2==0 else '256']
    if (index//2)%2: command.append('--fragment-updates')
    with (args.report_dir/(name+'.log')).open('w') as log:
        process = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    passed = process.returncode==0
    if passed:
        data = json.loads(report.read_text())
        passed = data['checks']==['initial raw image'] and data['viewer']['frames']>=1
    return {'attempt':index+1,'returncode':process.returncode,'passed':passed,
            'diagnostics_written':diagnostic.exists()}
with ThreadPoolExecutor(max_workers=args.jobs) as pool:
    results = list(pool.map(run,range(args.attempts)))
failures = sum(not r['passed'] for r in results)
# Failed attempts are useful evidence; preserve them explicitly, without retry.
summary.write_text(json.dumps({'attempts':results,'failures':failures,'jobs':args.jobs,
    'scope':'Private loopback VNC/Xvfb/xterm only; initial RGB pixel verification; '
            'per-attempt stderr diagnostics contain no live server data'},indent=2)+'\n')
print(f'{len(results)-failures}/{len(results)} startup checks passed; {failures} failed')
sys.exit(1 if failures else 0)
