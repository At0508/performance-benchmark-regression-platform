"""Demonstrate detection with two intentionally different command delays."""

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchreg.runner import run_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('results/verification'))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports = {}
    baseline = None
    for label, delay in (('baseline', 0.15), ('slower', 0.40)):
        suite = args.output_dir / f'{label}-suite.json'
        suite.write_text(json.dumps({
            'schema_version': 1,
            'name': 'controlled regression detection',
            'benchmarks': [{'id': 'controlled-delay',
                            'command': [sys.executable, '-c',
                                        f'import time; time.sleep({delay})'],
                            'warmups': 1, 'repetitions': 5, 'timeout_seconds': 5}]
        }, indent=2) + '\n', encoding='utf-8')
        report = run_suite(suite, args.output_dir / label, baseline, threshold=0.25)
        reports[label] = report['cases'][0]
        if label == 'baseline':
            baseline = args.output_dir / label / 'report.json'
    summary = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'environment': {'os': platform.platform(), 'python': platform.python_version(),
                        'processor': platform.processor()},
        'experiment': 'Deliberately increase sleep from 150 ms to 400 ms; includes process startup.',
        'threshold': 0.25,
        'baseline': {key: reports['baseline'][key] for key in ('samples_ms', 'median_ms', 'mad_ms')},
        'slower': {key: reports['slower'][key] for key in ('samples_ms', 'median_ms', 'mad_ms',
                                                         'relative_change', 'status')},
        'detected': reports['slower']['status'] == 'regression',
    }
    path = args.output_dir / 'verification.json'
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    if not summary['detected']:
        raise SystemExit('Expected slowdown was not detected; inspect host contention.')


if __name__ == '__main__':
    main()
