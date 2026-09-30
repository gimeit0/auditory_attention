"""Bind a pre-submission plan to Slurm's assigned job without a hash cycle.

sbatch receives the already reviewed release/plan digests and nonce. While held,
the submitter writes RUN_REQUEST = PLAN plus the returned job ID. At execution
we independently derive those exact request bytes from the pinned plan and the
actual SLURM_JOB_ID; no child-created file supplies new launch authority.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE=Path(__file__).absolute().parent
REMOTE=Path('/home/s2510040/audattn_external_eval_diag/formal40_numeric_profiles_20260916_v1')
PREFIX='package/docs/superpowers/prototypes/g2_runtime_20260917/'
PYTHON=Path('/home/s2510040/miniconda3/envs/attn/bin/python')


def require(ok,message):
    if not ok: raise RuntimeError('G2 bootstrap: '+message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')


def read(path):
    require(path.is_absolute() and '..' not in path.parts and not any(p.is_symlink() for p in (path,*path.parents)),
            'absolute nonsymlink file required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1
                and 0<before.st_size<=2*1024**2,'bounded owned regular source required')
        with os.fdopen(os.dup(fd),'rb') as handle: raw=handle.read(2*1024**2+1)
        identity=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mode,v.st_uid,v.st_nlink,v.st_mtime_ns,v.st_ctime_ns)
        require(len(raw)==before.st_size and identity(before)==identity(os.fstat(fd))==identity(path.lstat()),
                'source changed while reading')
        return raw
    finally: os.close(fd)


def derive_request(plan_raw,plan_sha,release_sha,nonce,job):
    require(type(plan_sha) is str and re.fullmatch('[a-f0-9]{64}',plan_sha) and sha(plan_raw)==plan_sha,
            'pre-submission plan digest differs')
    require(type(job) is str and re.fullmatch('[1-9][0-9]{0,19}',job),'actual job ID required')
    require(type(nonce) is str and re.fullmatch('[a-f0-9]{32}',nonce),'nonce differs')
    require(type(release_sha) is str and re.fullmatch('[a-f0-9]{64}',release_sha),'release digest differs')
    plan=json.loads(plan_raw)
    require(type(plan) is dict and wire(plan)==plan_raw and set(plan)=={
        'schema_version','protocol','nonce','release_sha256','freezes','limits','partition'},'plan schema differs')
    require(plan['nonce']==nonce and plan['release_sha256']==release_sha,'submitted plan identity differs')
    return dict(plan,job_id=job)


def main():
    require(len(sys.argv)==5,'expected release SHA, plan SHA, nonce, actual spool script')
    release_sha,plan_sha,nonce,spool=sys.argv[1:]
    require(HERE==REMOTE/PREFIX and sys.platform=='linux' and sys.version.split()[0]=='3.11.5'
            and sys.flags.isolated and sys.dont_write_bytecode and Path(sys.executable).resolve()==PYTHON.resolve(),
            'native deployed bootstrap required')
    job=os.environ.get('SLURM_JOB_ID')
    plan_raw=read(REMOTE/'EXECUTION_PLAN.json')
    request=derive_request(plan_raw,plan_sha,release_sha,nonce,job)
    release_raw=read(REMOTE/'RELEASE.json')
    require(sha(release_raw)==release_sha,'submitted release differs')
    release=json.loads(release_raw)
    require(wire(release)==release_raw,'release encoding differs')
    files=release['files']
    require(sha(read(Path(__file__).absolute()))==files[PREFIX+'bootstrap.py'],'bootstrap source differs')
    expected_spool=Path('/var/spool/slurm/slurmd')/('job'+job)/'slurm_script'
    require(Path(spool)==expected_spool and sha(read(expected_spool))==files[PREFIX+'run_matrix.sbatch'],
            'actual Slurm spool script differs')
    entry_path=HERE/'entry.py'
    raw=read(entry_path)
    require(sha(raw)==files[PREFIX+'entry.py'],'entry source differs')
    spec=importlib.util.spec_from_file_location('g2_bootstrap_entry',entry_path)
    entry=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(entry_path),'exec',dont_inherit=True),vars(entry))
    entry.validate_request(request)
    request_raw=wire(request)
    require(read(REMOTE/'RUN_REQUEST.json')==request_raw,'held submitter request differs from actual plan/job')
    # Start a new interpreter, retaining the real HOME and allocation environment.
    os.execv(str(PYTHON),[str(PYTHON),'-I','-B',str(entry_path),'matrix',sha(request_raw)])


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(json.dumps(dict(status='G2_BOOTSTRAP_REJECTED',error_type=type(exc).__name__,message=str(exc))),file=sys.stderr)
        raise SystemExit(2)
