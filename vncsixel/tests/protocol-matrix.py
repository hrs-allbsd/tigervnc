#!/usr/bin/env python3
"""Run xterm pixel comparisons for all ServerInit/color/transport cases."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer', type=Path)
parser.add_argument('--report-dir', required=True, type=Path)
parser.add_argument('--jobs', type=int, default=1)
args = parser.parse_args()
if not 1 <= args.jobs <= 3:
    parser.error('--jobs must be between 1 and 3')
viewer = args.viewer.resolve()
if not viewer.is_file():
    parser.error('viewer does not exist')
args.report_dir.mkdir(parents=True, exist_ok=True)
script = Path(__file__).with_name('protocol-smoke.py')
cases = [(pixel_format, colors, fragmented)
         for pixel_format in ('rgb888', 'rgb565', 'big-endian')
         for colors in (8, 256) for fragmented in (False, True)]
# A failed rerun must not leave an old successful summary in place.
summary = args.report_dir / 'summary.json'
summary.unlink(missing_ok=True)

def run(case):
    pixel_format, colors, fragmented = case
    name = f'{pixel_format}-{colors}-' + ('fragmented' if fragmented else 'normal')
    report = args.report_dir / (name + '.json')
    report.unlink(missing_ok=True)
    command = [sys.executable, str(script), str(viewer), '--report', str(report),
               '--server-format', pixel_format, '--colors', str(colors)]
    if fragmented: command.append('--fragment-updates')
    with (args.report_dir / (name + '.log')).open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = json.loads(report.read_text())
    assert len(result['checks']) == 40, name
    assert result['negotiated_format'] == [32,24,0,1,255,255,255,16,8,0], name
    return {'case': name, 'comparisons': len(result['checks']),
            'negotiated_format': result['negotiated_format']}

with ThreadPoolExecutor(max_workers=args.jobs) as pool:
    results = list(pool.map(run, cases))
summary.write_text(json.dumps({'cases': results,
    'comparisons': sum(result['comparisons'] for result in results),
    'scope': 'Private Xvfb/xterm; RGB888 updates, ServerInit negotiation, '
             '8/256 colors, normal/fragmented update writes; no live data'}, indent=2) + '\n')
print(f'PASS: {len(results)} configurations, {sum(r["comparisons"] for r in results)} pixel comparisons')
