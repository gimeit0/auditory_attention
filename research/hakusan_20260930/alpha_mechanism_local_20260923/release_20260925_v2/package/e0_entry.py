"""Stdlib bootstrap: verify every packaged file before importing local code."""
import hashlib
import json
import os
from pathlib import Path
import sys

def verify_package(package,digest):
    if package.is_symlink(): raise ValueError('PACKAGE_SYMLINK')
    manifest=package/'RELEASE.json'
    if manifest.is_symlink() or hashlib.sha256(manifest.read_bytes()).hexdigest()!=digest:
        raise ValueError('RELEASE_SHA')
    release=json.loads(manifest.read_text())
    if any(p.is_symlink() for p in package.rglob('*')): raise ValueError('PACKAGE_SYMLINK')
    for name,row in release['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('PACKAGE_PATH')
        path=package/relative
        if any(p.is_symlink() for p in [path,*list(path.parents)[:len(relative.parts)]]):
            raise ValueError('PACKAGE_SYMLINK')
        if not path.is_file() or path.stat().st_size!=row['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('PACKAGE_FILE: '+name)
    actual={str(p.relative_to(package)) for p in package.rglob('*') if p.is_file()}
    if actual!=set(release['files'])|{'RELEASE.json'}: raise ValueError('PACKAGE_INVENTORY')
    if release['scope']!='E0_FORMAL40_NATIVE_20260925_V2': raise ValueError('PACKAGE_SCOPE')
    if any(release.get(k)!=v for k,v in dict(wall_minutes=30,gpus=1,cpus=8,host_memory_gib=64,
                                            coordinator_deadline_seconds=1500).items()):
        raise ValueError('PACKAGE_BUDGET')
    return release

def main():
    if len(sys.argv)<3 or sys.argv[1] not in ('check','source-check','run','worker'): raise ValueError('ENTRY_ARGUMENTS')
    package=Path(__file__).resolve().parent
    digest=sys.argv[2]
    release=verify_package(package,digest)
    if sys.argv[1]=='check':
        print(json.dumps({'status':'PACKAGE_BYTES_PASS','release_sha256':digest,'jobs_submitted':0}))
        return
    if not sys.flags.isolated or not sys.dont_write_bytecode: raise ValueError('ISOLATED_REQUIRED')
    if sys.argv[1]=='source-check' and len(sys.argv)==3:
        sys.path.insert(0,str(package))
        from audited_model_session import native_source_preflight
        print(json.dumps(native_source_preflight()))
        return
    if sys.platform!='linux' or not os.environ.get('SLURM_JOB_ID','').isdigit(): raise ValueError('ALLOCATED_ONLY')
    state=package.parent/'state'
    receipt=json.loads((state/'SUBMISSION.json').read_text())
    if receipt['job_id']!=os.environ['SLURM_JOB_ID'] or receipt['release_sha256']!=digest:
        raise ValueError('JOB_RECEIPT')
    sys.path.insert(0,str(package))
    from production_e0 import worker,coordinator
    if sys.argv[1]=='run' and len(sys.argv)==4:
        if Path(sys.argv[3])!=state/'attempt': raise ValueError('ATTEMPT_PATH')
        coordinator(package,Path(sys.argv[3]),release,digest)
    elif sys.argv[1]=='worker' and len(sys.argv)==5 and sys.argv[3] in ('A','B'):
        directory=Path(sys.argv[4])
        if directory!=state/'attempt'/sys.argv[3]: raise ValueError('WORKER_PATH')
        try: worker(package,sys.argv[3],directory,release)
        except BaseException as e:
            from e0_archive_harness import write_json
            write_json(directory/'WORKER_FAILED.json',dict(error_type=type(e).__name__,error=str(e)))
            raise
    else: raise ValueError('ENTRY_ARGUMENTS')

if __name__=='__main__': main()
