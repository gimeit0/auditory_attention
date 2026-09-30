"""Metadata-only E1 candidate selection. Never authorizes input freeze or GPU."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
BANK = BASE / 'docs/superpowers/evidence/p05-confirmation-set-20260919/frozen_bank.tsv'
PILOT = BASE / 'docs/superpowers/evidence/r1-development-inventory-20260922/pilot-decode-juw608jg/PILOT_MANIFEST.json'
BANK_SHA = 'd03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091'
PILOT_SHA = '0415868e9127e60fea2cbd592131e41af045349008ff3d611dd7d3dc165d294e'
O = {9000,0,1,158,317,476,634,793,952,1111,1269,1428,1587,1745,1904,2063,2222,2380,2539,2698,2856,3015,3174,3333,3491,3650,3809,3967,4126,4285,4444,4602}
ROLES = ['target','correct_cue'] + [f'distractor_{i}' for i in range(1,5)] + ['probe_distractor_cue','shuffled_cue']

def require(ok, msg):
    if not ok: raise ValueError(msg)

def checked(path, digest):
    require(path.is_file() and not path.is_symlink(), 'INPUT_FILE')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == digest, 'INPUT_SHA')
    return raw

def validate(row):
    for role in ROLES:
        require(all(role+s in row for s in ('_speaker','_path','_index')), 'ROLE_SCHEMA')
    n = int(row['distractor_count'])
    require(row['scene_kind'] in ('clean','mixed') and 0 <= n <= 4, 'SCENE')
    require((n == 0) == (row['scene_kind'] == 'clean'), 'SCENE_COUNT')
    require(row['target_gender'] in ('female','male'), 'GENDER')
    control = int(row['control_subset'])
    require(control in (0,1) and not (n == 0 and control), 'CONTROL')
    active = ['target','correct_cue'] + [f'distractor_{i}' for i in range(1,n+1)]
    if n: active += ['probe_distractor_cue']
    if control: active += ['shuffled_cue']
    for role in ROLES:
        if role in active:
            require(bool(row[role+'_speaker']) and bool(row[role+'_path']) and int(row[role+'_index']) >= 0, 'ROLE_MISSING')
            require(Path(row[role+'_path']).name == row[role+'_path'], 'UNSAFE_CLIP')
        else:
            require(not row[role+'_speaker'] and not row[role+'_path'] and int(row[role+'_index']) == -1, 'UNEXPECTED_ROLE')
    require(row['target_speaker'] == row['correct_cue_speaker'], 'CUE_SPEAKER')
    require(row['target_path'] != row['correct_cue_path'], 'CUE_NOT_INDEPENDENT_RECORDING')
    for role in active:
        x = float(row[role+'_anchor_center_s'])
        require(math.isfinite(x) and x >= 0 and 0 <= int(row[role+'_label']) < 800, 'ANCHOR')

def select(rows, pilot):
    ids = [int(r['trial_id']) for r in rows]
    require(len(ids) == len(set(ids)), 'DUPLICATE_ID')
    index = dict(zip(ids, rows))
    excluded = []
    usable = []
    for row in rows:
        validate(row)
        tid = int(row['trial_id'])
        speakers = {row[p+'_speaker'] for p in ROLES} - {''}
        if int(row['control_subset']):
            donor = index.get(int(row['shuffled_source_trial_id']))
            require(donor is not None, 'DONOR_MISSING')
            require(all(row['shuffled_cue_'+s] == donor['correct_cue_'+s]
                        for s in ('speaker','path','index','label','anchor_center_s')), 'DONOR_MISMATCH')
            speakers.add(donor['correct_cue_speaker'])
        reasons = (['ORIGINAL_O'] if tid in O else []) + (['PILOT_ROLE'] if speakers & pilot else [])
        if reasons: excluded.append(dict(trial_id=tid,reasons=reasons))
        else: usable.append(row)
    rng = np.random.Generator(np.random.PCG64(20260920))
    groups, capacities = [], []
    specs = [('clean',0,-1,g,0,100) for g in ('female','male')]
    specs += [('mixed',d,s,g,c,10 if c else 35) for d in range(1,5) for s in range(5)
              for g in ('female','male') for c in (1,0)]
    for kind,d,s,g,c,quota in specs:
        pool = sorted([r for r in usable if (r['scene_kind'],int(r['distractor_count']),int(r['snr_bin']),r['target_gender'],int(r['control_subset'])) == (kind,d,s,g,c)], key=lambda r:int(r['trial_id']))
        capacities.append(dict(stratum=[kind,d,s,g,c],available=len(pool),required=quota))
        if len(pool) < quota: continue
        chosen = [int(pool[i]['trial_id']) for i in sorted(rng.choice(len(pool),quota,replace=False))]
        groups.append(chosen)
    if any(r['available'] < r['required'] for r in capacities):
        return dict(status='SELECTION_INFEASIBLE',capacities=capacities,excluded=excluded)
    # Merge gender/control subgroups into clean + 20 mixed strata, then shuffle.
    strata = [groups[0]+groups[1]] + [sum(groups[i:i+4],[]) for i in range(2,82,4)]
    strata = [[int(x) for x in rng.permutation(s)] for s in strata]
    order = [s[i] for i in range(max(map(len,strata))) for s in strata if i < len(s)]
    require(len(order) == len(set(order)) == 2000 and not set(order)&O, 'SELECTION_COUNT')
    selected = [index[i] for i in order]
    batches = [order[i:i+16] for i in range(0,len(order),16)]
    controls = [[i for i in b if int(index[i]['control_subset'])] for b in batches]
    clean = [r for r in selected if r['scene_kind']=='clean']
    require(len(clean)==200 and sum(map(len,controls))==400, 'QUOTAS')
    return dict(status='E1_METADATA_CANDIDATE_NOT_INPUTS_FROZEN',seed=20260920,
                numpy_version=np.__version__,rng='PCG64',trial_ids=order,batches=batches,
                control_batches=controls,clean_batches=[[int(r['trial_id']) for r in clean[i:i+16]] for i in range(0,200,16)],
                clean_sources=[{k:v for k,v in r.items() if k=='trial_id' or k.startswith(('target_','correct_cue_'))} for r in clean],
                target_speakers=len({r['target_speaker'] for r in selected}),
                control_target_speakers=len({r['target_speaker'] for r in selected if int(r['control_subset'])}),
                target_labels=len({r['target_label'] for r in selected}),
                role_speaker_counts={p:len({r[p+'_speaker'] for r in selected}-{''}) for p in ROLES},
                capacities=capacities,excluded=excluded,
                blockers=['PINNED_VALIDATION_ANCHOR_IDENTITY_NOT_YET_VERIFIED','CLEAN_AUDIO_BYTES_AND_DECODE_NOT_VERIFIED','NEW_CLEAN_PREPROCESSING_NOT_ACCEPTED'],
                inputs_frozen=False,jobs_submitted=0)

def main():
    rows = list(csv.DictReader(io.StringIO(checked(BANK,BANK_SHA).decode()), delimiter='\t'))
    require(len(rows)==10000, 'BANK_COUNT')
    pilot = json.loads(checked(PILOT,PILOT_SHA))
    require(len(set(pilot['speakers']))==16, 'PILOT_COUNT')
    result = select(rows,set(pilot['speakers']))
    result['sources'] = dict(bank_sha256=BANK_SHA,pilot_sha256=PILOT_SHA,
                             selector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if 'trial_ids' in result:
        for name,path in [('e0',HERE/'E0_LAYOUT_96.json'),('confirmation_256',BANK.parent/'confirmation_256.json')]:
            raw=path.read_bytes()
            result[name+'_overlap'] = sorted(set(result['trial_ids']) & set(json.loads(raw)['trial_ids']))
            result['sources'][name+'_sha256']=hashlib.sha256(raw).hexdigest()
    # Exclusive output: never overwrite a candidate or silently resample.
    with Path(sys.argv[1]).open('x') as out: json.dump(result,out,ensure_ascii=False,sort_keys=True,indent=2)
    print(json.dumps({k:result[k] for k in ('status','target_speakers','control_target_speakers','inputs_frozen') if k in result}))

if __name__ == '__main__': main()
