"""Verified local-only 54-point readout for fine-alpha job 756262 (doc 46 §4). No SSH/GPU.

Re-runs the frozen package offline-check, checks every array against its WORKER SHA,
checks cold repeats across the three processes, then computes descriptive statistics.
"""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
from analyze_e1_primary import identity
from fine_alpha_statistics import analyze, CODES, BLOCK_OF, MAIN, CLEAN, value

BASE = Path(__file__).resolve().parent
RELEASE = BASE/'release_fine_alpha_20260928_candidate_v3'
PACKAGE = RELEASE/'package'
COLLECTED = RELEASE/'collected-756262-2xu_4ag0'
DIGEST = '1644b8bd3e9eea855476f123e904707f82c9d1465f4345f43432c847893e87d7'
JOB = '756262'
E1_A = BASE/'release_e1_20260927_v3/collected-750474-_rosoog2/state/attempt/A'


def load_block(folder, sources):
    worker = json.loads((folder/'WORKER.json').read_bytes()); arrays = {}
    for row in worker['outputs']:
        p = folder/row['file']; sources[str(p)] = identity(p)
        if sources[str(p)] != {k: row[k] for k in ('size', 'sha256')}: raise ValueError('ARRAY_SHA '+str(p))
        with np.load(p, allow_pickle=False) as z: arrays[tuple(row['key'])] = {k: z[k] for k in z.files}
    return arrays


def equal(a, b): return all(np.array_equal(a[k], b[k]) for k in ('trial_ids', 'logits', 'nll'))


def main():
    out = Path(tempfile.mkdtemp(prefix=f'readout-{JOB}-', dir=RELEASE))
    print('OUTPUT='+str(out), flush=True)
    with (out/'offline-check.json').open('xb') as stdout, (out/'offline-check.stderr').open('xb') as stderr:
        subprocess.run([sys.executable, '-I', '-B', str(PACKAGE/'fine_alpha_entry.py'), 'offline-check', DIGEST,
                        str(COLLECTED/'state/attempt'), JOB], stdout=stdout, stderr=stderr, check=True, timeout=1800)
    verified = json.loads((out/'offline-check.json').read_bytes())
    if verified.get('status') != 'FINE_ALPHA_ARTIFACTS_VERIFIED' or verified.get('predictions') != 219600:
        raise ValueError('ARCHIVE_NOT_VERIFIED')
    sources = {}
    blocks = {b: load_block(COLLECTED/'state/attempt'/b/'output', sources) for b in 'ABC'}
    arrays = {}
    for p in CODES:
        for d, conds in (('main', MAIN), ('clean', CLEAN)):
            for c in conds: arrays[d, p, c] = blocks[BLOCK_OF[p]][BLOCK_OF[p], d, p, c]
    checks = dict(cold_repeat={}, reference_vs_alpha_1000={}, bypass_vs_alpha_0000={})
    for d, conds in (('main', MAIN), ('clean', CLEAN)):
        for c in conds:
            arrays[d, 'original', c] = blocks['A']['A', d, 'original', c]
            for pass_name in ('original', 'reference'):
                checks['cold_repeat'][f'{d}/{pass_name}/{c}'] = all(
                    equal(blocks['A']['A', d, pass_name, c], blocks[b][b, d, pass_name, c]) for b in 'BC')
            checks['reference_vs_alpha_1000'][f'{d}/{c}'] = equal(blocks['C']['C', d, 'reference', c], arrays[d, 'alpha_1000', c])
            checks['bypass_vs_alpha_0000'][f'{d}/{c}'] = equal(blocks['A']['A', d, 'explicit_bypass', c], arrays[d, 'alpha_0000', c])
    e1_sources = {}; e1 = {}
    for key, a in load_block(E1_A, e1_sources).items(): e1[key[1:]] = a
    with (PACKAGE/'frozen_bank.tsv').open() as f:
        bank = {int(r['trial_id']): r for r in csv.DictReader(f, delimiter='\t')}
    report = analyze(arrays, bank, e1)
    report.update(job_id=JOB, release_sha256=DIGEST, offline_check=verified, archive_checks=checks,
                  sources=dict(fine=sources, e1_750474_A=e1_sources, bank=identity(PACKAGE/'frozen_bank.tsv')),
                  analysis_sources={n: identity(BASE/n) for n in ('fine_alpha_statistics.py', 'analyze_fine_alpha_756262.py',
                                    'e1_cluster_statistics.py', 'e1_secondary_statistics.py', 'e1_error_structure.py',
                                    'analyze_e1_primary.py')},
                  age_mapping_validated=False, scientific_report_complete=False)
    for group in (sources, e1_sources):
        if any(identity(Path(p)) != v for p, v in group.items()): raise ValueError('SOURCE_CHANGED')
    (out/'REPORT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    rows = []
    mixed = report['main_mixed_summaries']
    for p in CODES:
        m = report['units']['main_correct_mixed']['metrics'][f'{p}/accuracy_pp']
        rows.append(dict(alpha=value(p), code=p, block=BLOCK_OF[p], domain='main', condition='correct_cue_mixed_scenes',
                         unit='main_mixed_1800', n=report['units']['main_correct_mixed']['info']['trials'],
                         accuracy_pp=m['estimate'], ci95_low=m['ci95'][0], ci95_high=m['ci95'][1], mean_nll=mixed[p]['mean_nll'],
                         logit_max_abs=mixed[p]['logit_max_abs'], predicted_classes=mixed[p]['predicted_classes'],
                         most_frequent_count=mixed[p]['most_frequent_count'], collapse=report['main_mixed_collapse'][p]['collapse']))
        for d, conds in (('main', MAIN), ('clean', CLEAN)):
            for c in conds:
                s_ = report['summaries'][f'{d}/{p}/{c}']
                pooled = (d, c) == ('main', 'correct')
                unit = report['units']['main_correct_all' if pooled else 'control' if d == 'main' else 'clean']
                key = f'{p}/accuracy_pp' if pooled else f'{p}/{c}/accuracy_pp'
                ci = unit['metrics'][key]['ci95']
                nll = s_['mean_nll'] if pooled or d == 'clean' else unit['metrics'][key.replace('accuracy_pp', 'nll')]['estimate']
                rows.append(dict(alpha=value(p), code=p, block=BLOCK_OF[p], domain=d,
                                 condition='correct_pooled_1800cue_200zerocue' if pooled else c,
                                 unit='main_2000' if pooled else 'control_400' if d == 'main' else 'clean_200',
                                 n=unit['info']['trials'], accuracy_pp=unit['metrics'][key]['estimate'],
                                 ci95_low=ci[0], ci95_high=ci[1], mean_nll=nll,
                                 # logit/class columns describe the whole stored array of that condition
                                 logit_max_abs=s_['logit_max_abs'], predicted_classes=s_['predicted_classes'],
                                 most_frequent_count=s_['most_frequent_count'],
                                 collapse=report['collapse'].get(f'{d}/{p}', {}).get('collapse') if c in ('correct', 'correct_cue') else ''))
    with (out/'CURVE.csv').open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    t = report['transitions']
    print(json.dumps(dict(out=str(out), checks={k: all(v.values()) for k, v in checks.items()},
                          e1_bridge_bitwise=all(v['bitwise_logits'] for v in report['e1_bridge'].values()),
                          residual=report['alpha0_residual'],
                          first_passage={u: {k: (v['point'], v['interval_95'], v['draws_not_reached']) for k, v in t[u]['first_passage']['levels'].items()}
                                         for u in ('main_mixed_correct_cue', 'main_all_pooled')},
                          decreasing_steps={u: t[u]['monotonicity']['decreasing_steps'] for u in ('main_mixed_correct_cue', 'main_all_pooled')},
                          collapse_free=t['collapse_free_all_points'], mixed_collapse_free=t['mixed_collapse_free_all_points']),
                     ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
