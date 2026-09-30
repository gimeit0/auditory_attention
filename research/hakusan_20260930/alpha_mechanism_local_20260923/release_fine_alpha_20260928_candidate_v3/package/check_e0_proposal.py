"""Read-only local proposal check; no torch, checkpoints, SSH, or submission."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def check():
    proposal=Path(__file__).with_name('E0_SAMPLE_PROPOSAL.json')
    p=json.loads(proposal.read_text())
    root=ROOT/p['archive']
    for name,expected in p['reference_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('REFERENCE_SHA_MISMATCH: '+name)
    run=json.loads((root/'RUN.json').read_text())
    with (root/'bank.csv').open(newline='') as f:
        bank={int(r['trial_id']):r for r in csv.DictReader(f)}
    assert run['models']['formal40']['sha256']==p['checkpoint_sha256']
    batches=[list(range(i,i+16)) for i in p['original_batch_start_trial_ids']]
    assert all(b in run['batches'] for b in batches)
    ids=[i for b in batches for i in b]
    assert len(ids)==len(set(ids))==p['expected_trials']
    rows=[bank[i] for i in ids]
    clean=sum(r['scene_kind']=='clean' for r in rows)
    controls=sum(int(r['control_subset']) for r in rows)
    assert clean==p['expected_clean'] and len(rows)-clean==p['expected_mixed']
    assert controls==p['expected_control_trials']
    counts=len(rows)+3*controls
    passes=len(p['passes_per_process'])*p['independent_processes']+p['extra_observed_alpha_05_passes']
    assert counts*passes==p['expected_model_condition_predictions']
    return dict(status='E0_LOCAL_PROPOSAL_CHECK_PASS',proposal_sha256=hashlib.sha256(proposal.read_bytes()).hexdigest(),
                trials=len(rows),clean=clean,mixed=len(rows)-clean,control=controls,
                predictions_per_pass=counts,passes=passes,total_predictions=counts*passes,
                batch_ranges=[[b[0],b[-1]] for b in batches],
                runtime_reference=run['runtime'],remote_access=False,jobs_submitted=0,
                note='Plan arithmetic and local archive identity only; no production endpoint validation')

if __name__=='__main__':
    print(json.dumps(check(),ensure_ascii=False,indent=2))
