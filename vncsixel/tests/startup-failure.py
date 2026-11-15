#!/usr/bin/env python3
"""Verify startup diagnostics reject early child exits and stale success data."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report', type=Path, required=True)
args = parser.parse_args()
args.report.unlink(missing_ok=True)
results = []
for program,status in [('false',1),('true',0)]:
    executable = shutil.which(program)
    if not executable: parser.error(program+' is required')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('001','002'):
            (root/(name+'.json')).write_text('{"stale_success":true}\n')
        with (root/'runner.log').open('w') as log:
            process = subprocess.run([sys.executable,str(Path(__file__).with_name('xterm-startup.py')),
                executable,'--attempts','2','--jobs','2','--report-dir',str(root)],
                stdout=log,stderr=subprocess.STDOUT)
        assert process.returncode==1, (program,process.returncode)
        summary = json.loads((root/'summary.json').read_text())
        assert summary['failures']==2 and len(summary['attempts'])==2, summary
        for name in ('001','002'):
            assert not (root/(name+'.json')).exists(), 'stale success survived'
            data = json.loads((root/(name+'-startup.json')).read_text())
            assert data['exit_before_cleanup']['viewer']==status, data
            assert data['checks_completed']==0, data
            assert 'viewer exited' in (root/(name+'.log')).read_text()
        results.append({'child_program':program,'child_status':status,'rejected_attempts':2,
                        'stale_success_removed':True})
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps({'cases':results,'scope':'Injected local child exits; no VNC credentials'},indent=2)+'\n')
print('PASS: four early exits rejected, actual child status captured, stale success removed')
