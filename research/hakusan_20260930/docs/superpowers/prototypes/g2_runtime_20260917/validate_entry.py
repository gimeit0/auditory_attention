"""Bounded local entry/package verification, without production input loading."""
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

HERE=Path(__file__).absolute().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(HERE))
import entry as e
import build_release as b
import runtime as r

EXTRA=('entry.py','run_matrix.sbatch','bootstrap.py','build_release.py','test_entry.py','validate_entry.py',
       'test_runtime.py','validate_local.py')
PACKAGE_CHECK='''import sys
from pathlib import Path
package=Path(sys.argv[1])
sys.path.insert(0,str(package/'docs/superpowers/prototypes/g2_runtime_20260917'))
import entry as e
r=e.load('runtime', e.HERE/'runtime.py', e.RUNTIME_SHA)
bridge=e.load('package_bridge', e.HERE.parent/'g2_worker_20260916/cell_bridge.py',e.BRIDGE_SHA)
for p in e.ORDER:
    d=bridge.load_candidate(package.parent/p/'tools/diagnose_batch_invariance.py',p)
    bridge._check_module(d)
    assert d._G2_PROFILE==p
assert not any(k in sys.modules for k in ('torch','numpy','pandas','torchaudio'))
print('PACKAGED_COLD_IMPORT_CHECK=PASS')
'''


def records():
    values={n:dict(size=len(raw),sha256=e.digest(raw)) for n,raw in b.sources().items()}
    values.update({'local/'+n:dict(size=len(e.read(HERE/n)),sha256=e.digest(e.read(HERE/n))) for n in EXTRA})
    return dict(sorted(values.items()))


def report(raw,prefix,expected):
    found=[json.loads(line[len(prefix):]) for line in raw.decode().splitlines() if line.startswith(prefix)]
    e.require(len(found)==1 and found[0]['tests']==expected
              and found[0]['failures']==found[0]['errors']==found[0]['skipped']==0
              and found[0]['production_model_loaded'] is False and found[0]['jobs_submitted']==0,'test report differs')


def verify(folder):
    value=json.loads(e.read(folder/'VALIDATION.json'))
    e.require(value['status']=='LOCAL_G2_ENTRY_CANDIDATE_PASS'
              and value['sources_before']==value['sources_after']==records(),'entry sources changed')
    b.verify(folder/'candidate',value['release_sha256'])
    for name,expected in value['sources_before'].items():
        raw=e.read(folder/'snapshots'/name)
        e.require(dict(size=len(raw),sha256=e.digest(raw))==expected,'source snapshot changed')
    expected_names=('entry_tests','runtime_tests','package_imports','runner_syntax')
    e.require(tuple(value['order'])==expected_names and set(value['stages'])==set(expected_names),'stage inventory differs')
    for name,stage in value['stages'].items():
        process=stage['process']; raw=e.read(folder/(name+'.log'))
        e.require(process['returncode']==0 and process['error'] is None and process['elapsed_seconds']<45.5
                  and process['log']==dict(name=name+'.log',size=len(raw),sha256=e.digest(raw)),'stage/log differs')
    report(e.read(folder/'entry_tests.log'),'G2_ENTRY_TEST_REPORT=',27)
    report(e.read(folder/'runtime_tests.log'),'G2_RUNTIME_TEST_REPORT=',30)
    e.require(e.read(folder/'package_imports.log')==b'PACKAGED_COLD_IMPORT_CHECK=PASS\n','package cold import differs')
    print('LOCAL_G2_ENTRY_CANDIDATE_RECHECK=PASS',flush=True)


def main():
    os.umask(0o077)
    before=records()
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder=Path(tempfile.mkdtemp(prefix='g2-entry-local-'+stamp,dir=ROOT/'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE='+str(folder),flush=True)
    release_sha=b.build(folder/'candidate')
    for name in before:
        raw=e.read(HERE/name.removeprefix('local/')) if name.startswith('local/') else e.read(folder/'candidate'/name)
        b.write(folder/'snapshots'/name,raw)
    commands={
        'entry_tests':[sys.executable,'-I','-B',str(HERE/'test_entry.py')],
        'runtime_tests':[sys.executable,'-I','-B',str(HERE/'test_runtime.py')],
        'package_imports':[sys.executable,'-I','-B','-c',PACKAGE_CHECK,str(folder/'candidate/package')],
        'runner_syntax':['/bin/bash','-n',str(folder/'candidate/package'/e.PREFIX/'run_matrix.sbatch')],
    }
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    stages={}; error=None
    try:
        for name,command in commands.items():
            process=r.process_api.run_process(command,env,folder/(name+'.log'),seconds=45,max_log_bytes=2*1024**2)
            stages[name]=dict(process=process,argv=command)
            e.require(process['returncode']==0 and process['error'] is None,'stage failed: '+name)
        after=records()
        e.require(before==after,'source drift during entry tests')
        b.verify(folder/'candidate',release_sha)
        report(e.read(folder/'entry_tests.log'),'G2_ENTRY_TEST_REPORT=',27)
        report(e.read(folder/'runtime_tests.log'),'G2_RUNTIME_TEST_REPORT=',30)
        e.require(e.read(folder/'package_imports.log')==b'PACKAGED_COLD_IMPORT_CHECK=PASS\n','packaged import failed')
    except BaseException as exc:
        error=r.error_record(exc)
        after=records()
    result=dict(status='LOCAL_G2_ENTRY_CANDIDATE_PASS' if error is None else 'LOCAL_G2_ENTRY_CANDIDATE_FAILED',
        release_sha256=release_sha,sources_before=before,sources_after=after,stages=stages,order=list(commands),error=error,
        scope='LOCAL_TESTS_AND_PACKAGED_COLD_IMPORTS_NOT_PRODUCTION_EXECUTION',
        remote_operations=0,jobs_submitted=0,inputs_frozen=False,resource_approval=False,ready_for_gpu=False)
    r.process_api.write_once(folder/'VALIDATION.json',result)
    if error:
        print(json.dumps(error),flush=True)
        return 2
    verify(folder)
    return 0


if __name__=='__main__':
    if len(sys.argv)==1: raise SystemExit(main())
    if len(sys.argv)==3 and sys.argv[1]=='verify': verify(Path(sys.argv[2]).absolute())
    else: raise SystemExit('usage: validate_entry.py [verify FOLDER]')
