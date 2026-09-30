"""Bounded local synthetic archive pipeline; no network, release or submission."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import pass_store as store

ORDER=('D-write','D-verify','E-write','E-verify','unit')


def load(path,digest,name):
    raw=store.pinned(path,digest)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec',dont_inherit=True),vars(module))
    return module


prior=load(HERE.parent/'g2_lifetime_20260917/validate_local.py',
           '14c9e3832b73597e64de8b3d343b0ba76f38edf6bf4b2155c6ca114e87948c6f','g2_archive_prior_validation')
runner=load(prior.RUNNER,prior.RUNNER_SHA,'g2_archive_bounded_runner')


def sources():
    records=prior.sources()
    paths=[HERE/n for n in ('pass_store.py','hermetic_check.py','test_store.py','validate_local.py')]
    paths += [store.SOURCE,store.GEOMETRY,store.PARENT]
    records.update({str(p.relative_to(store.ROOT)):prior.record(p) for p in paths})
    return dict(sorted(records.items()))


def parse(stage,raw):
    prefix=('G2_ARCHIVE_TEST_REPORT=' if stage=='unit' else
            'G2_ARCHIVE_WRITER_REPORT=' if stage.endswith('write') else 'G2_ARCHIVE_VERIFY_REPORT=')
    values=[json.loads(line[len(prefix):]) for line in raw.decode().splitlines() if line.startswith(prefix)]
    store.require(len(values)==1,'missing/duplicate report')
    value=values[0]
    store.require(value['production_model_loaded'] is False and value['jobs_submitted']==0,'scope differs')
    if stage=='unit':
        store.require(value==dict(tests=27,errors=0,failures=0,skipped=0,
              scope='LOCAL_SYNTHETIC_ARCHIVE_CONTENT_ONLY',production_model_loaded=False,jobs_submitted=0),
              'unit report differs')
    elif stage.endswith('write'):
        store.require(value['profile']==stage[0] and value['arrays']==40
                and value['original_gate_live_after_storage'] is True and value['rng_unchanged'] is True,
                'writer result differs')
        # Original complete fixture endpoint also must pass after the callback.
        marker='G2_LIFETIME_MMAP_REPORT='
        endpoints=[json.loads(line[len(marker):]) for line in raw.decode().splitlines() if line.startswith(marker)]
        store.require(len(endpoints)==1 and endpoints[0]['status']=='HERMETIC_MMAP_TWO_PASS_PASS'
                and endpoints[0]['forward_calls']==34 and endpoints[0]['spills']==endpoints[0]['mappings']==4
                and endpoints[0]['descriptor_scopes_closed'] is True
                and endpoints[0]['production_lifetime_executed'] is False,'original fixture endpoint differs')
    else:
        store.require(value['status']=='G2_ARCHIVE_CONTENT_VERIFIED' and value['arrays_rehashed']==40
                and value['per_trial_hashes_checked']==1280 and value['numeric']['status']=='NUMERIC_ACCEPT'
                and value['binding']['profile']==stage[0] and value['execution_authority_verified'] is False
                and value['ready_for_gpu'] is False and value['cuda_initialized'] is False,'verifier result differs')
    return value


def verify(folder, *, check_review=True):
    if check_review:
        review=json.loads((folder/'REVIEW.json').read_bytes())
        store.require(review['status']=='LOCAL_G2_ARCHIVE_REVIEW_PASS'
                and review['validation']==prior.record(folder/'VALIDATION.json'),'final review differs')
    value=json.loads((folder/'VALIDATION.json').read_bytes())
    store.require(value['status']=='LOCAL_G2_ARCHIVE_CHECKS_PASS' and value['before']==value['after']==sources()
            and value['stage_order']==list(ORDER) and value['elapsed_seconds']<120
            and value['jobs_submitted']==value['remote_operations']==0,'validation receipt differs')
    for index,(name,record) in enumerate(value['before'].items()):
        store.require(prior.record(folder/'sources'/(str(index)+'-'+Path(name).name))==record,'snapshot differs')
    pids=[]
    for stage in ORDER:
        process=value['stages'][stage]['process']
        log=folder/(stage+'.log')
        report=parse(stage,log.read_bytes())
        store.require(process['returncode']==0 and process['error'] is None and process['elapsed_seconds']<45.5
                and process['log']==dict(name=log.name,**prior.record(log))
                and report==value['stages'][stage]['report'],'process/log differs')
        pids.append(process['pid'])
    store.require(len(set(pids))==len(ORDER),'cold PID reused')
    for profile in ('D','E'):
        # The original loader owns a fixed module name. Profiles must retain
        # separate interpreters even for offline decoding; never unload/patch it.
        process=subprocess.run([sys.executable,'-I','-B',str(HERE/'hermetic_check.py'),'verify',str(folder/profile)],
                               stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        store.require(process.returncode==0 and len(process.stdout)+len(process.stderr)<=2*1024**2,
                      'cold read-only verification failed: '+process.stderr.decode(errors='replace')[-2000:])
        report=parse(profile+'-verify',process.stdout)
        expected=value['stages'][profile+'-verify']['report']
        store.require({k:v for k,v in expected.items() if k!='verifier_pid'} ==
                      {k:v for k,v in report.items() if k!='verifier_pid'},'fresh content recheck differs')
        key=str((HERE/'pass_store.py').relative_to(store.ROOT))
        store.require(report['binding']['release_sha256']==value['before'][key]['sha256']
                and report['binding']['pid']==value['stages'][profile+'-write']['process']['pid'],
                'source/writer linkage differs')
    print('LOCAL_G2_ARCHIVE_RECHECK=PASS',flush=True)


def main():
    os.umask(0o077)
    before=sources()
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder=Path(tempfile.mkdtemp(prefix='g2-archive-local-'+stamp,dir=store.ROOT/'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE='+str(folder),flush=True)
    (folder/'sources').mkdir(mode=0o700)
    for index,name in enumerate(before):
        prior.write(folder/'sources'/(str(index)+'-'+Path(name).name),(store.ROOT/name).read_bytes())
    stages,error,started={},None,time.monotonic()
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',
             OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    try:
        for stage in ORDER:
            if stage=='unit': argv=[str(HERE/'test_store.py'),str(folder/'D')]
            else:
                profile,action=stage.split('-')
                if action=='write':
                    (folder/profile).mkdir(mode=0o700)
                    argv=[str(HERE/'hermetic_check.py'),'write',profile,str(folder/profile)]
                else: argv=[str(HERE/'hermetic_check.py'),'verify',str(folder/profile)]
            remaining=115-(time.monotonic()-started)
            store.require(remaining>0,'local time budget exhausted')
            process=runner.run_process([sys.executable,'-I','-B',*argv],env,folder/(stage+'.log'),
                                       seconds=min(45,remaining),max_log_bytes=2*1024**2)
            stages[stage]=dict(process=process)
            store.require(process['returncode']==0 and process['error'] is None,'child failed: '+stage)
            stages[stage]['report']=parse(stage,(folder/(stage+'.log')).read_bytes())
            print(stage+'=PASS',flush=True)
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
    elapsed,after=time.monotonic()-started,sources()
    passed=error is None and before==after and elapsed<120 and list(stages)==list(ORDER)
    runner.write_once(folder/'VALIDATION.json',dict(status='LOCAL_G2_ARCHIVE_CHECKS_PASS' if passed else
        'LOCAL_G2_ARCHIVE_CHECKS_FAILED',before=before,after=after,stages=stages,stage_order=list(stages),
        elapsed_seconds=elapsed,error=error,jobs_submitted=0,remote_operations=0))
    if passed:
        try:
            verify(folder,check_review=False)
        except BaseException as exc:
            passed=False
            error=dict(type=type(exc).__name__,message=str(exc))
        runner.write_once(folder/'REVIEW.json',dict(status='LOCAL_G2_ARCHIVE_REVIEW_PASS' if passed else
             'LOCAL_G2_ARCHIVE_REVIEW_FAILED',validation=prior.record(folder/'VALIDATION.json'),error=error))
    if not passed: print(json.dumps(error),flush=True)
    return 0 if passed else 2


if __name__=='__main__':
    if len(sys.argv)==1: raise SystemExit(main())
    if len(sys.argv)==3 and sys.argv[1]=='verify': verify(Path(sys.argv[2]).resolve())
    else: raise SystemExit('usage: validate_local.py [verify FOLDER]')
