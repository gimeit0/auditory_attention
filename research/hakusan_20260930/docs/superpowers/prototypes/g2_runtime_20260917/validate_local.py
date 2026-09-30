"""Persist bounded runtime-core tests and readonly checks of saved array inputs."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(HERE))
import runtime as r

PRIOR=HERE.parent/'g2_archive_20260917/validate_local.py'
raw=r.store.pinned(PRIOR,'0e34fa31b0dcfd9fd9a7d814f88845d09ae1d35528254d99c17088d32652d1c7')
# The original validator uses its sibling pass_store; add only this pinned
# sibling directory, never cwd, and execute the checked bytes.
sys.path.insert(0,str(PRIOR.parent))
spec=importlib.util.spec_from_file_location('g2_runtime_archive_validation',PRIOR)
prior=importlib.util.module_from_spec(spec)
exec(compile(raw,str(PRIOR),'exec'),vars(prior))
ARCHIVE=ROOT/'docs/superpowers/evidence/g2-archive-local-20260917T034258Z-47rh9pu7'
EXPECTED=dict(tests=30,failures=0,errors=0,skipped=0,
              scope='CONTROL_FLOW_DOUBLES_AND_SAVED_SYNTHETIC_PASS_SEMANTICS',
              production_model_loaded=False,jobs_submitted=0,remote_operations=0)


def sources():
    values=prior.sources()
    values.update({str((HERE/n).relative_to(ROOT)):prior.prior.record(HERE/n)
                   for n in ('runtime.py','evidence.py','test_runtime.py','validate_local.py')})
    return dict(sorted(values.items()))


def inputs():
    paths=[ARCHIVE/n for n in ('VALIDATION.json','REVIEW.json','D/RECEIPT.json','D/EXPECTED.json')]
    paths+=sorted((ARCHIVE/'D/arrays').iterdir())
    return {str(p.relative_to(ROOT)):prior.prior.record(p) for p in paths}


def report(log):
    prefix='G2_RUNTIME_TEST_REPORT='
    values=[json.loads(line[len(prefix):]) for line in log.decode().splitlines() if line.startswith(prefix)]
    r.require(values==[EXPECTED],'runtime report differs')
    return values[0]


def verify(folder):
    value=json.loads((folder/'VALIDATION.json').read_bytes())
    r.require(value['status']=='LOCAL_G2_RUNTIME_CORE_PASS'
              and value['sources_before']==value['sources_after']==sources()
              and value['inputs_before']==value['inputs_after']==inputs(),'source/data changed')
    for index,(name,expected) in enumerate(value['sources_before'].items()):
        r.require(prior.prior.record(folder/'sources'/(str(index)+'-'+Path(name).name))==expected,'source snapshot differs')
    log=folder/'tests.log'
    process=value['process']
    r.require(process['returncode']==0 and process['error'] is None and process['elapsed_seconds']<45.5
              and process['log']==dict(name='tests.log',**prior.prior.record(log))
              and report(log.read_bytes())==value['report'],'process/log differs')
    prior.verify(ARCHIVE)
    print('LOCAL_G2_RUNTIME_CORE_RECHECK=PASS',flush=True)


def main():
    os.umask(0o077)
    before,data=sources(),inputs()
    prior.verify(ARCHIVE)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder=Path(tempfile.mkdtemp(prefix='g2-runtime-local-'+stamp,dir=ROOT/'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE='+str(folder),flush=True)
    (folder/'sources').mkdir(mode=0o700)
    for i,name in enumerate(before):
        prior.prior.write(folder/'sources'/(str(i)+'-'+Path(name).name),(ROOT/name).read_bytes())
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    process=r.process_api.run_process([sys.executable,'-I','-B',str(HERE/'test_runtime.py')],env,folder/'tests.log',
                                      seconds=45,max_log_bytes=2*1024**2)
    after,data_after=sources(),inputs()
    error,value=None,None
    try:
        r.require(process['returncode']==0 and process['error'] is None,'runtime tests failed')
        value=report((folder/'tests.log').read_bytes())
        r.require(before==after and data==data_after,'sources/inputs changed')
    except BaseException as exc: error=r.error_record(exc)
    r.process_api.write_once(folder/'VALIDATION.json',dict(status='LOCAL_G2_RUNTIME_CORE_PASS' if error is None else
        'LOCAL_G2_RUNTIME_CORE_FAILED',sources_before=before,sources_after=after,inputs_before=data,inputs_after=data_after,
        process=process,report=value,error=error,remote_operations=0,jobs_submitted=0))
    if error is None:
        verify(folder)
        return 0
    print(json.dumps(error),flush=True)
    return 2


if __name__=='__main__':
    if len(sys.argv)==1: raise SystemExit(main())
    if len(sys.argv)==3 and sys.argv[1]=='verify': verify(Path(sys.argv[2]).resolve())
    else: raise SystemExit('usage: validate_local.py [verify FOLDER]')
