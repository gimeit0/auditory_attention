"""Verified local-only secondary analysis runner for job 750474."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
from analyze_e1_primary import BASE,RELEASE,PACKAGE,COLLECTED,DIGEST,identity
from e1_secondary_statistics import analyze

def main():
    out=Path(tempfile.mkdtemp(prefix='secondary-analysis-750474-',dir=RELEASE))
    print('OUTPUT='+str(out),flush=True)
    signoff=BASE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json'
    approved=json.loads(signoff.read_bytes())
    if approved['release_sha256']!=DIGEST or approved['delta_percentage_points']!=2: raise ValueError('SIGNOFF')
    for row in approved['contracts']:
        if identity(BASE/row['file'])!={k:row[k] for k in ('size','sha256')}: raise ValueError('CONTRACT_SHA')
    with (out/'offline-check.json').open('xb') as stdout,(out/'offline-check.stderr').open('xb') as stderr:
        subprocess.run([sys.executable,'-I','-B',str(PACKAGE/'e1_entry.py'),'offline-check',DIGEST,
                        str(COLLECTED/'state/attempt'),'750474'],stdout=stdout,stderr=stderr,check=True,timeout=180)
    verified=json.loads((out/'offline-check.json').read_bytes())
    if verified['verified'] is not True: raise ValueError('ARCHIVE_VERIFICATION')
    worker=json.loads((COLLECTED/'state/attempt/A/WORKER.json').read_bytes())
    arrays={}; sources={}
    for row in worker['outputs']:
        p=COLLECTED/'state/attempt/A'/row['file']
        sources[str(p)]=identity(p)
        if sources[str(p)]!={k:row[k] for k in ('size','sha256')}: raise ValueError('ARRAY_SHA')
        with np.load(p,allow_pickle=False) as z:
            arrays[tuple(row['key'][1:])]={k:z[k] for k in z.files}
    with (PACKAGE/'frozen_bank.tsv').open() as f:
        bank={int(r['trial_id']):r for r in csv.DictReader(f,delimiter='\t')}
    report=analyze(arrays,bank)
    primary_path=RELEASE/'primary-analysis-750474-f4ao34wq/REPORT.json'
    primary=json.loads(primary_path.read_bytes())
    for name in ('control_full','control_excluding_e0_overlap'):
        a=report['units'][name]; b=primary['units'][name]
        if a['info']['shared_draw_indices_sha256']!=b['info']['shared_draw_indices_sha256']: raise ValueError('SHARED_DRAWS')
        for k in ('D_pp','c1_pp','r0_pp'):
            if a['metrics'][k]!=b['metrics'][k]: raise ValueError('PRIMARY_REPRODUCTION')
    if report['units']['clean_full']['info']['clusters']!=149 or report['units']['clean_excluding_e0_overlap']['info']['trials']!=195:
        raise ValueError('CLEAN_UNIT')
    sources.update({str(p):identity(p) for p in [PACKAGE/'RELEASE.json',PACKAGE/'frozen_bank.tsv',signoff,primary_path]})
    report.update(job_id='750474',release_sha256=DIGEST,
                  research_role='PILOT_DRIVEN_REUSED_VALIDATION_BANK_EXPLORATORY_DEVELOPMENT',
                  primary_and_draws_reproduced=True,sources=sources,
                  analysis_sources={n:identity(BASE/n) for n in ('e1_secondary_statistics.py','analyze_e1_secondary.py','e1_cluster_statistics.py','analyze_e1_primary.py')})
    # Check source identities again after analysis, before publishing success.
    if any(identity(Path(p))!=expected for p,expected in sources.items()): raise ValueError('SOURCE_CHANGED')
    (out/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(status=report['status'],q3_status=report['q3_status'],
        main_alpha05=report['summaries']['main/alpha_05/correct'],
        clean_alpha1=report['units']['clean_full']['metrics']['alpha_1/correct_minus_zero/accuracy_pp'],
        collapse=report['collapse']),ensure_ascii=False))

if __name__=='__main__': main()
