"""Local handoff audit. No SSH, scheduler, model loading, or authorization issuance."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
RELEASE_SHA='558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3'
ENTRY_SHA='bc3ce55e57f1870df86cf89a48230c88476193afe9fa07a459fd8d30c11c47fd'

def identity(p):
    if p.is_symlink() or not p.is_file(): raise ValueError('REGULAR_FILE_REQUIRED')
    raw=p.read_bytes()
    return dict(sha256=hashlib.sha256(raw).hexdigest(),size=len(raw))

def check_documents(release,root):
    docs=release['decision_record']['documents']
    required={'statistics_contract_v2','statistics_contract_v3_correction'}
    if not required.issubset(docs): raise ValueError('BOTH_CONTRACTS_REQUIRED')
    checked={}
    for key,row in docs.items():
        name=row['file']
        if Path(name).name!=name: raise ValueError('DOCUMENT_PATH')
        got=identity(root/name)
        if got!={k:row[k] for k in ('sha256','size')}: raise ValueError('DOCUMENT_CHANGED: '+name)
        checked[key]=dict(file=name,**got)
    return checked

def check():
    package=HERE/'release_e1_20260927_v3/package_ready'
    if identity(package/'RELEASE.json')['sha256']!=RELEASE_SHA: raise ValueError('RELEASE_CHANGED')
    if identity(package/'e1_entry.py')['sha256']!=ENTRY_SHA: raise ValueError('ENTRY_CHANGED')
    r=json.loads((package/'RELEASE.json').read_bytes())
    docs=check_documents(r,HERE)
    command=[sys.executable,'-I','-B',str(package/'e1_entry.py'),'check',RELEASE_SHA]
    run=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if run.returncode: raise ValueError('PACKAGE_CHECK_FAILED: '+run.stderr)
    result=json.loads(run.stdout)
    if result['status']!='E1_PACKAGE_BYTES_AND_INPUTS_PASS': raise ValueError('PACKAGE_NOT_PASS')
    e=r['execution']
    if e['paired_metric_policy']!='FULL_D_WITH_OBSERVED_ALPHA0_RESIDUAL_NOT_FORCED_ZERO':
        raise ValueError('PAIRED_POLICY')
    if sum(x['predictions'] for x in e['records'])!=38400: raise ValueError('COUNT')
    return dict(status='E1_LOCAL_HANDOFF_CHECK_PASS_NOT_AUTHORIZATION',
        release_sha256=RELEASE_SHA,documents=docs,package_check=result,
        predictions=38400,alpha_grid=e['alpha_grid'],budget_candidate=r['budget'],
        pending=['statistics signoff binding BOTH contracts and delta',
                 'separate remote publication authorization','separate GPU budget and held submission authorization',
                 'held resource inspection and separate release authorization',
                 'full bootstrap/report implementation and acceptance'],
        network_used=False,checkpoint_loaded=False,jobs_submitted=0,gpu_authorized=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    a=p.parse_args();report=check()
    raw=json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    if a.output:
        with a.output.open('x') as f:f.write(raw)
    print(raw,end='')
