"""Independent arithmetic audit: no imports from analysis implementations.

Uses cluster multiplicities/matrix products instead of indexed cluster-sum
reduction. Input joins are rebuilt from npz and the frozen bank.
"""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np

BASE=Path(__file__).resolve().parent
ROOT=BASE/'release_e1_20260927_v3'
PKG=ROOT/'package_ready'
COL=ROOT/'collected-750474-_rosoog2'
SHA='558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3'

def identity(p):
    raw=p.read_bytes(); return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def check_values(observed,expected,where):
    a=np.asarray(observed,dtype=float); b=np.asarray(expected,dtype=float)
    if a.shape!=b.shape or not np.isfinite(a).all() or not np.isfinite(b).all() or not np.allclose(a,b,rtol=0,atol=1e-10):
        raise ValueError('NUMERIC_MISMATCH: '+where)

def independent_ci(speakers,values):
    groups=sorted(set(speakers))
    masks=[np.array([s==g for s in speakers]) for g in groups]
    counts=np.array([int(m.sum()) for m in masks])
    totals=np.stack([values[m].sum(axis=0) for m in masks])
    if len(groups)<2: return None,None,counts
    rng=np.random.Generator(np.random.PCG64(20260926)); digest=hashlib.sha256()
    weights=np.empty((10000,len(groups)),dtype=np.int64)
    for j in range(10000):
        sample=rng.integers(0,len(groups),len(groups))
        digest.update(sample.astype('<i8').tobytes())
        weights[j]=np.bincount(sample,minlength=len(groups))
    draws=(weights@totals)/(weights@counts)[:,None]
    return np.quantile(draws,[.025,.975],axis=0,method='linear'),digest.hexdigest(),counts

class Raw:
    def __init__(self,bank,arrays): self.bank,self.arrays=bank,arrays
    def vector(self,domain,p,cond,ids,kind):
        a=self.arrays[domain,p,cond]
        positions={int(i):j for j,i in enumerate(a['trial_ids'])}
        if len(positions)!=len(a['trial_ids']): raise ValueError('DUPLICATE_ID')
        index=[positions[i] for i in ids]
        if kind=='nll': return a['nll'][index].astype(np.float64)
        labels=np.array([int(self.bank[i]['target_label']) for i in ids])
        return (a['logits'][index].argmax(1)==labels).astype(np.float64)*100
    def cue(self,p,ids):
        return self.vector('main',p,'correct',ids,'acc')-self.vector('main',p,'shuffled',ids,'acc')
    def metric(self,name,ids,domain):
        bits=name.split('/')
        if name=='D_pp': return self.cue('alpha_1',ids)-self.cue('alpha_0',ids)
        if name=='c1_pp': return self.cue('alpha_1',ids)
        if name=='r0_pp': return self.cue('alpha_0',ids)
        if bits[0]=='negative': return self.cue('alpha_05',ids)-self.cue(bits[1],ids)
        p=bits[0]
        if bits[1]=='D_pp': return self.cue(p,ids)-self.cue('alpha_0',ids)
        if bits[1]=='cue_effect_pp': return self.cue(p,ids)
        if bits[1]=='nll_correct_minus_shuffled':
            return self.vector('main',p,'correct',ids,'nll')-self.vector('main',p,'shuffled',ids,'nll')
        kind='nll' if bits[-1]=='nll' else 'acc'
        if len(bits)==2: return self.vector('main',p,'correct',ids,kind)
        cond=bits[1]
        if cond.startswith('correct_minus_'):
            other=cond.removeprefix('correct_minus_')
            first='correct_cue' if domain=='clean' else 'correct'
            if other=='zero': other='zero_cue'
            return self.vector(domain,p,first,ids,kind)-self.vector(domain,p,other,ids,kind)
        return self.vector(domain,p,cond,ids,kind)

def audit_unit(raw,row,domain,name):
    ids=row['trial_ids']; names=list(row['metrics'])
    x=np.column_stack([raw.metric(k,ids,domain) for k in names])
    speakers=[raw.bank[i]['target_speaker'] for i in ids]
    ci,digest,counts=independent_ci(speakers,x)
    info=row['info']
    expected=dict(trials=len(ids),clusters=len(counts),cluster_size_min=int(counts.min()),
                  cluster_size_max=int(counts.max()),cluster_size_median=float(np.median(counts)))
    for k,v in expected.items():
        if info[k]!=v: raise ValueError('UNIT_METADATA: '+name+'/'+k)
    if ci is not None and digest!=info['shared_draw_indices_sha256']: raise ValueError('DRAW_HASH')
    for j,k in enumerate(names):
        check_values(row['metrics'][k]['estimate'],x[:,j].mean(),name+'/'+k+'/mean')
        if ci is None:
            if row['metrics'][k]['ci95'] is not None: raise ValueError('SMALL_CLUSTER_CI')
        else: check_values(row['metrics'][k]['ci95'],ci[:,j],name+'/'+k+'/ci')
    return len(names)

def main():
    out=Path(tempfile.mkdtemp(prefix='independent-stat-audit-750474-',dir=ROOT)); print('OUTPUT='+str(out),flush=True)
    with (out/'offline-check.json').open('xb') as stdout,(out/'offline-check.stderr').open('xb') as stderr:
        subprocess.run([sys.executable,'-I','-B',str(PKG/'e1_entry.py'),'offline-check',SHA,
                        str(COL/'state/attempt'),'750474'],check=True,stdout=stdout,stderr=stderr,timeout=180)
    sources={}; arrays={}
    worker=json.loads((COL/'state/attempt/A/WORKER.json').read_bytes())
    for r in worker['outputs']:
        p=COL/'state/attempt/A'/r['file']; sources[str(p)]=identity(p)
        if sources[str(p)]!={k:r[k] for k in ('size','sha256')}: raise ValueError('RAW_SHA')
        with np.load(p,allow_pickle=False) as z: arrays[tuple(r['key'][1:])]={k:z[k] for k in z.files}
    with (PKG/'frozen_bank.tsv').open() as f: bank={int(r['trial_id']):r for r in csv.DictReader(f,delimiter='\t')}
    raw=Raw(bank,arrays); metrics=0; units=0
    primary_path=ROOT/'primary-analysis-750474-f4ao34wq/REPORT.json'
    secondary_path=ROOT/'secondary-analysis-750474-mo1tlyrm/REPORT.json'
    for p in (primary_path,secondary_path):
        sources[str(p)]=identity(p); report=json.loads(p.read_bytes())
        for name,row in report['units'].items():
            metrics+=audit_unit(raw,row,'clean' if name.startswith('clean') else 'main',name); units+=1
        for name,group in report.get('strata',{}).items():
            for key,row in group.items(): metrics+=audit_unit(raw,row,'main',name+'/'+key); units+=1
    secondary=json.loads(secondary_path.read_bytes())
    for key,s in secondary['summaries'].items():
        a=arrays[tuple(key.split('/'))]; x=a['logits'].astype(np.float64); nll=a['nll'].astype(np.float64)
        pred=np.argmax(x,axis=1); labels=np.array([int(bank[int(i)]['target_label']) for i in a['trial_ids']])
        counts=np.bincount(pred,minlength=800)
        expected=dict(n=len(x),accuracy=float((pred==labels).mean()),mean_nll=float(nll.mean()),
                      logit_max_abs=float(np.abs(x).max()),predicted_classes=int((counts>0).sum()),
                      most_frequent_count=int(counts.max()),sample_logit_rms_mean=float(np.sqrt((x*x).mean(1)).mean()),
                      sample_logit_rms_max=float(np.sqrt((x*x).mean(1)).max()))
        for k,v in expected.items(): check_values(s[k],v,key+'/'+k)
        if s['most_frequent_classes']!=np.flatnonzero(counts==counts.max()).tolist(): raise ValueError('TIED_CLASSES')
        # Independent logaddexp reduction rather than max-shift exp/sum.
        n64=np.logaddexp.reduce(x,axis=1)-x[np.arange(len(x)),labels]
        check_values(s['nll_float64_recompute_max_abs'],np.abs(n64-nll).max(),key+'/nll64')
    for key,record in secondary['collapse'].items():
        domain,p=key.split('/')
        cond='correct' if domain=='main' else 'correct_cue'
        a=arrays[domain,p,cond]; ref=arrays[domain,'original',cond]
        labels=np.array([int(bank[int(i)]['target_label']) for i in a['trial_ids']])
        ref_labels=np.array([int(bank[int(i)]['target_label']) for i in ref['trial_ids']])
        low=bool(np.mean(a['logits'].argmax(1)==labels)<.5*np.mean(ref['logits'].argmax(1)==ref_labels))
        high=bool(np.abs(a['logits']).max()>10*float(np.abs(ref['logits']).max()))
        if record!=dict(collapse=low or high,accuracy_below_half_original=low,logit_above_ten_times_original=high):
            raise ValueError('COLLAPSE_RULE: '+key)
    base=arrays['main','alpha_05','correct']
    for p,record in secondary['negative_agreement'].items():
        other=arrays['main',p,'correct']
        lookup={int(i):j for j,i in enumerate(other['trial_ids'])}
        x=other['logits'][[lookup[int(i)] for i in base['trial_ids']]]
        check_values(record['top1_agreement'],np.mean(base['logits'].argmax(1)==x.argmax(1)),p+'/agreement')
        check_values(record['max_abs_logit_difference'],np.abs(base['logits'].astype(float)-x.astype(float)).max(),p+'/logit_difference')
    sources[str(PKG/'frozen_bank.tsv')]=identity(PKG/'frozen_bank.tsv')
    if any(identity(Path(p))!=v for p,v in sources.items()): raise ValueError('SOURCE_CHANGED')
    result=dict(status='INDEPENDENT_PRIMARY_SECONDARY_ARITHMETIC_PASS',units=units,metrics=metrics,
                array_summaries=len(secondary['summaries']),collapse_rules=len(secondary['collapse']),
                negative_agreement_records=len(secondary['negative_agreement']),absolute_tolerance=1e-10,
                implementation='cluster multiplicity matrix; raw npz joins; no analysis helper imports',
                numpy_version=np.__version__,sources=sources,code=identity(Path(__file__)),
                not_covered=['error taxonomy independent audit','P1-P9 contract closure','scientific label gate'],
                scientific_conclusion=False)
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='sources'}))

if __name__=='__main__': main()
