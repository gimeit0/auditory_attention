"""Combined 0-1 readout from jobs 756262 and 757288 (local only; no SSH/GPU).

Re-runs each job's own frozen offline-check, SHA-checks every array against its WORKER.json, requires the
0.50/0.75 anchors and the original pass to be bitwise identical across the two jobs, then computes statistics.
"""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from analyze_e1_primary import identity
from analyze_fine_alpha_756262 import load_block, COLLECTED as OLD_COLLECTED, PACKAGE as OLD_PACKAGE, DIGEST as OLD_DIGEST
from fine_alpha_v4_anchor import compare
import fine_alpha_combined as fc

BASE = Path(__file__).resolve().parent
NEW_RELEASE = BASE/'release_fine_alpha_20260929_candidate_v4'
NEW_PACKAGE = NEW_RELEASE/'package'
NEW_DIGEST = '0b067f57d612987d9c80a56e385658b1414095e46b5956b0bff43a7760668a2a'


def offline(package, digest, attempt, job, out, name, predictions):
    with (out/f'{name}.json').open('xb') as stdout, (out/f'{name}.stderr').open('xb') as stderr:
        subprocess.run([sys.executable, '-I', '-B', str(package/'fine_alpha_entry.py'), 'offline-check', digest, str(attempt), job],
                       stdout=stdout, stderr=stderr, check=True, timeout=3600)
    v = json.loads((out/f'{name}.json').read_bytes())
    if v.get('status') != 'FINE_ALPHA_ARTIFACTS_VERIFIED' or v.get('predictions') != predictions or v.get('job_id') != job:
        raise ValueError('ARCHIVE_NOT_VERIFIED: '+name)
    return v


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('new_collected', type=Path); p.add_argument('--new-job', required=True)
    a = p.parse_args()
    out = Path(tempfile.mkdtemp(prefix=f'readout-combined-756262-{a.new_job}-', dir=NEW_RELEASE)); print('OUTPUT='+str(out), flush=True)
    checks = dict(offline_756262=offline(OLD_PACKAGE, OLD_DIGEST, OLD_COLLECTED/'state/attempt', '756262', out, 'offline-check-756262', 219600),
                  offline_new=offline(NEW_PACKAGE, NEW_DIGEST, a.new_collected/'state/attempt', a.new_job, out, 'offline-check-'+a.new_job, 122400))
    sources = {}
    old = {b: load_block(OLD_COLLECTED/'state/attempt'/b/'output', sources) for b in 'ABC'}
    new = {b: load_block(a.new_collected/'state/attempt'/b/'output', sources) for b in 'AB'}
    anchor = compare(new, {'C': old['C']})
    if not anchor['passed']: raise ValueError('ANCHOR_MISMATCH_STOP')
    arrays, source, cross = fc.assemble(old, new)
    if not all(cross.values()): raise ValueError('ORIGINAL_PASS_DIFFERS_ACROSS_JOBS')
    with (OLD_PACKAGE/'frozen_bank.tsv').open() as f: bank = {int(r['trial_id']): r for r in csv.DictReader(f, delimiter='\t')}
    if identity(OLD_PACKAGE/'frozen_bank.tsv') != identity(NEW_PACKAGE/'frozen_bank.tsv'): raise ValueError('BANK_DIFFERS')
    report = fc.analyze(arrays, bank)
    report.update(jobs=dict(old='756262', new=a.new_job), release_sha256=dict(old=OLD_DIGEST, new=NEW_DIGEST), point_source=source,
                  anchor_check=anchor, original_cross_job=cross, offline_checks=checks, array_sources=sources,
                  bank=identity(OLD_PACKAGE/'frozen_bank.tsv'),
                  analysis_sources={n: identity(BASE/n) for n in ('fine_alpha_combined.py', 'analyze_fine_alpha_combined.py',
                                    'fine_alpha_v4_anchor.py', 'e1_cluster_statistics.py', 'e1_secondary_statistics.py',
                                    'e1_error_structure.py', 'analyze_e1_primary.py', 'analyze_fine_alpha_756262.py')})
    if any(identity(Path(k)) != v for k, v in sources.items()): raise ValueError('SOURCE_CHANGED')
    (out/'REPORT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    rows = []
    mx = report['main_mixed_summaries']; u = report['units']['main_mixed']['metrics']
    for c in fc.GRID:
        n = fc.code(c)
        rows.append(dict(alpha=fc.value(c), code=n, source_job=source[n][0], unit='main_mixed_correct_cue_1800',
                         accuracy_pp=u[n+'/accuracy_pp']['estimate'], ci95_low=u[n+'/accuracy_pp']['ci95'][0], ci95_high=u[n+'/accuracy_pp']['ci95'][1],
                         mean_nll=mx[n]['mean_nll'], logit_max_abs=mx[n]['logit_max_abs'], predicted_classes=mx[n]['predicted_classes'],
                         most_frequent_count=mx[n]['most_frequent_count'], collapse=report['collapse_mixed'][n]['collapse']))
    with (out/'CURVE.csv').open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(json.dumps(dict(anchor=anchor['status'], cross=all(cross.values()), boundary=report['collapse_boundary']['mixed'],
                          transitions=report['transitions']['mixed']['point'],
                          decreasing=report['transitions']['mixed']['monotonicity']['decreasing_steps']), ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
