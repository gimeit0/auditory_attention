"""Partial E1 report: primary paired analysis and overlap sensitivity only.

Never emits E1_DEV_COMPLETE or scientific labels. Other contract analyses remain
required. Re-verifies the original archive before reading actual arrays.
"""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
from e1_cluster_statistics import bootstrap,paired_columns,OVERLAP

BASE=Path(__file__).resolve().parent
RELEASE=BASE/'release_e1_20260927_v3'
PACKAGE=RELEASE/'package_ready'
COLLECTED=RELEASE/'collected-750474-_rosoog2'
DIGEST='558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3'

def identity(p):
    raw=p.read_bytes()
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def align(ids,wanted,values):
    ids=list(map(int,ids)); wanted=list(map(int,wanted))
    if len(ids)!=len(set(ids)) or len(wanted)!=len(set(wanted)) or len(values)!=len(ids):
        raise ValueError('DUPLICATE_OR_SHAPE')
    lookup={i:j for j,i in enumerate(ids)}
    if not set(wanted)<=set(ids): raise ValueError('MISSING_TRIAL')
    return values[[lookup[i] for i in wanted]]

def main():
    out=Path(tempfile.mkdtemp(prefix='primary-analysis-750474-',dir=RELEASE))
    print('OUTPUT='+str(out),flush=True)
    signoff=BASE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json'
    approved=json.loads(signoff.read_bytes())
    assert approved['release_sha256']==DIGEST and approved['delta_percentage_points']==2
    for row in approved['contracts']:
        assert identity(BASE/row['file'])=={k:row[k] for k in ('size','sha256')}
    with (out/'offline-check.json').open('xb') as stdout,(out/'offline-check.stderr').open('xb') as stderr:
        subprocess.run([sys.executable,'-I','-B',str(PACKAGE/'e1_entry.py'),'offline-check',DIGEST,
                        str(COLLECTED/'state/attempt'),'750474'],stdout=stdout,stderr=stderr,check=True,timeout=180)
    verified=json.loads((out/'offline-check.json').read_bytes())
    assert verified['verified'] is True
    readout=verified['array_verification']['paired_readout']
    wanted=readout['trial_ids']
    bank={int(row['trial_id']):row for row in csv.DictReader((PACKAGE/'frozen_bank.tsv').open(),delimiter='\t')}
    assert len(wanted)==400 and all(bank[i]['control_subset']=='1' for i in wanted)
    labels=np.array([int(bank[i]['target_label']) for i in wanted])
    worker=json.loads((COLLECTED/'state/attempt/A/WORKER.json').read_bytes())
    arrays={}
    sources={str(signoff):identity(signoff),str(PACKAGE/'RELEASE.json'):identity(PACKAGE/'RELEASE.json'),
             str(PACKAGE/'frozen_bank.tsv'):identity(PACKAGE/'frozen_bank.tsv')}
    for row in worker['outputs']:
        _,domain,pass_name,condition=row['key']
        if domain!='main' or pass_name not in readout['terms'] or condition not in ('correct','shuffled'): continue
        p=COLLECTED/'state/attempt/A'/row['file']
        sources[str(p)]=identity(p)
        with np.load(p,allow_pickle=False) as z:
            arrays[pass_name,condition]=(align(z['trial_ids'],wanted,z['logits'].argmax(1)),
                                         align(z['trial_ids'],wanted,z['nll'].astype(np.float64)))
    terms={}
    for k in readout['terms']:
        correct,nc=arrays[k,'correct']; shuffled,ns=arrays[k,'shuffled']
        terms[k]=dict(accuracy_difference=(correct==labels).astype(int)-(shuffled==labels).astype(int),
                      nll_difference=nc-ns)
        np.testing.assert_array_equal(terms[k]['accuracy_difference'],readout['terms'][k]['accuracy_difference'])
        np.testing.assert_array_equal(terms[k]['nll_difference'],readout['terms'][k]['nll_difference'])
    columns=paired_columns(terms)
    np.testing.assert_array_equal(columns['D_pp']/100,readout['D'])
    for k in terms: np.testing.assert_array_equal(columns[k+'/D_pp']/100,readout['D_alpha'][k])
    units={}
    for name,mask in [('control_full',np.ones(400,dtype=bool)),
                      ('control_excluding_e0_overlap',np.array([i not in OVERLAP for i in wanted]))]:
        ids=np.array(wanted)[mask].tolist()
        units[name]=bootstrap([bank[i]['target_speaker'] for i in ids],{k:v[mask] for k,v in columns.items()})
        units[name]['trial_ids']=ids
    assert units['control_full']['info']['clusters']==246
    assert units['control_excluding_e0_overlap']['info']['trials']==386
    residual=terms['alpha_0']; pred=arrays['alpha_0','correct'][0]!=arrays['alpha_0','shuffled'][0]
    report=dict(status='E1_PRIMARY_STATISTICS_PARTIAL_NOT_DEV_COMPLETE',job_id='750474',
        research_role='PILOT_DRIVEN_REUSED_VALIDATION_BANK_EXPLORATORY_DEVELOPMENT',
        scientific_labels=[],units=units,delta_percentage_points=2,
        residual=dict(top1_indicator_nonzero=int(np.count_nonzero(residual['accuracy_difference'])),
            prediction_disagreements=int(pred.sum()),prediction_disagreement_trial_ids=np.array(wanted)[pred].tolist(),
            nll_mean=float(residual['nll_difference'].mean()),nll_std_ddof0=float(residual['nll_difference'].std(ddof=0)),
            nll_max_abs=float(np.abs(residual['nll_difference']).max())),
        remaining=['absolute_accuracy_and_nll','collapse_partition','snr_distractor_strata',
                   'error_structure','clean_cues','negative_controls','full_P1_P9_report','conclusion_gate'],
        sources=sources,analysis_sources={n:identity(BASE/n) for n in ('e1_cluster_statistics.py','analyze_e1_primary.py')})
    with (out/'PAIRED_TRIALS.csv').open('x',newline='') as f:
        writer=csv.writer(f); writer.writerow(['trial_id','target_speaker','e0_overlap',*columns])
        for j,i in enumerate(wanted): writer.writerow([i,bank[i]['target_speaker'],i in OVERLAP,*[v[j] for v in columns.values()]])
    report['paired_trial_file']=identity(out/'PAIRED_TRIALS.csv')
    (out/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':report['status'],'residual':report['residual'],
                     'primary':{k:v['metrics']['D_pp'] for k,v in units.items()}},ensure_ascii=False))

if __name__=='__main__': main()
