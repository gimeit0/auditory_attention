"""Local error taxonomy for every archived prediction, including cold repeat B."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
from analyze_e1_primary import BASE,RELEASE,PACKAGE,COLLECTED,DIGEST,identity
from e1_error_structure import analyze_errors

def main():
    out=Path(tempfile.mkdtemp(prefix='error-analysis-750474-',dir=RELEASE))
    print('OUTPUT='+str(out),flush=True)
    with (out/'offline-check.json').open('xb') as stdout,(out/'offline-check.stderr').open('xb') as stderr:
        subprocess.run([sys.executable,'-I','-B',str(PACKAGE/'e1_entry.py'),'offline-check',DIGEST,
                        str(COLLECTED/'state/attempt'),'750474'],stdout=stdout,stderr=stderr,check=True,timeout=180)
    verified=json.loads((out/'offline-check.json').read_bytes())
    if verified['verified'] is not True: raise ValueError('ARCHIVE_NOT_VERIFIED')
    with (PACKAGE/'frozen_bank.tsv').open() as f:
        bank={int(r['trial_id']):r for r in csv.DictReader(f,delimiter='\t')}
    reports={}; sources={}; all_rows=[]
    for process in ('A','B'):
        folder=COLLECTED/'state/attempt'/process
        worker=json.loads((folder/'WORKER.json').read_bytes()); arrays={}
        for row in worker['outputs']:
            p=folder/row['file']; sources[str(p)]=identity(p)
            if sources[str(p)]!={k:row[k] for k in ('size','sha256')}: raise ValueError('ARRAY_SHA')
            with np.load(p,allow_pickle=False) as z:
                arrays[tuple(row['key'][1:])]={k:z[k] for k in z.files}
        result=analyze_errors(arrays,bank)
        all_rows.extend(dict(process=process,**r) for r in result.pop('rows'))
        reports[process]=result
    if len(all_rows)!=38400: raise ValueError('PREDICTION_COUNT')
    with (out/'ERROR_TRIALS.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(all_rows[0])); w.writeheader(); w.writerows(all_rows)
    # Cold repeat is independently retained, not pooled as extra observations.
    for key,row in reports['B']['summaries'].items():
        if row!=reports['A']['summaries'][key]: raise ValueError('COLD_REPEAT_ERROR_TAXONOMY')
    sources[str(PACKAGE/'frozen_bank.tsv')]=identity(PACKAGE/'frozen_bank.tsv')
    if any(identity(Path(p))!=v for p,v in sources.items()): raise ValueError('SOURCE_CHANGED')
    report=dict(status='E1_ERROR_STRUCTURE_COMPLETE_NOT_DEV_COMPLETE',job_id='750474',predictions=38400,
                cold_repeat_not_pooled=True,processes=reports,sources=sources,
                trial_file=identity(out/'ERROR_TRIALS.csv'),scientific_labels=[],
                analysis_sources={n:identity(BASE/n) for n in ('e1_error_structure.py','analyze_e1_errors.py','e1_cluster_statistics.py','analyze_e1_primary.py')})
    (out/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':report['status'],'predictions':len(all_rows),
                      'alpha1_correct':reports['A']['summaries']['main/alpha_1/correct'],
                      'alpha1_shuffled':reports['A']['summaries']['main/alpha_1/shuffled']},ensure_ascii=False))

if __name__=='__main__': main()
