"""Build a new local G2 execution candidate. No remote writes, freeze or job.

Profile-local legacy submission names are deliberately fail-closed notices,
not copied old submitters. The single matrix runner owns the future execution.
Approval/request/held submission and live freezes are NOT created here.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import entry as e

PINS = {
    'g2_runtime_20260917/runtime.py': e.RUNTIME_SHA,
    'g2_runtime_20260917/evidence.py': e.EVIDENCE_SHA,
    'g2_lifetime_20260917/production_cell.py': '602d90cc26ee5900ed801e45a15b4f30ebbbe3bd9edf5f9ccb65a93f8982be24',
    'g2_archive_20260917/pass_store.py': '1b21505669bbc29b9072548f0134f582b3a3534cb7109e5a7b41e04e4dbc6a10',
    'g2_inputs_20260917/input_binding.py': '6a99559df859bb88cdf730d7dcd1bf72caf2f2f04800ae69781da23e64103896',
    'g2_scratch_20260917/scratch_binding.py': 'f0d16a11c712c9c1c96de6a5906efc4ac3978d012660eb33399672a681b2e271',
    'g2_worker_20260916/cell_bridge.py': e.BRIDGE_SHA,
    'g2_profiles_20260916/profiles.py': 'd5d83e810fef28c15835c28a583f1a5c4a4401adcf558e164ef3e5f46ea91227',
    'g2_native_20260916/backend_evidence.py': '018089bf401af07a076818f2e7d7b9347aff60572bd57951b6b3207f504179a4',
    'targeted_gpu_job_20260915_v5/process_runner.py': '189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a',
    'targeted_gpu_pair_20260915_scan/pass_archive.py': '48fe6e50b54a1b5a2ab88057dcbc2be5bd073f00fae9c06eaf7273a61026dfbd',
}
PROFILE_SHAS = dict(R='d77b316ca1d3dfdc0954100c73dd51783a074974a5ebb1d69c655a11a6ecdebd',
    C='32b79a3264ff3f1da3b43cdfed8d509c8aaa40df8da20ee9b8fd15b97da1b189',
    D='92fbad73ee2efa665d529fc69267d9b9397941e571b43cbb5bf35fa54920167b',
    E='4302bb1d2fc21897ced6618006587d3776c1c7c5339c5906fbf46d99babfd864')
TRACE_SHA = 'fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b'
DATA_SHAS = ('bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178',
             '95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34')
NOTICES = {
    'submit_numeric_diag.py': b'"""No per-profile submission. Use the separately reviewed matrix controller."""\nraise SystemExit("STOP: this profile has no standalone submission authority")\n',
    'run_numeric_diag.sbatch': b'#!/bin/bash\necho "STOP: profile-local runner is disabled; use reviewed matrix runner" >&2\nexit 2\n',
}


def sources():
    files = {}
    for name in e.DEPENDENCIES:
        raw = e.read(HERE.parent/name)
        if name in PINS:
            e.require(e.digest(raw) == PINS[name], 'pinned dependency changed: '+name)
        files['package/docs/superpowers/prototypes/'+name] = raw
    for name, expected in zip(e.DATA, DATA_SHAS):
        raw = e.read(ROOT/name)
        e.require(e.digest(raw) == expected, 'historical reference changed')
        files['package/'+name] = raw
    base = ROOT/'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
    for profile in e.ORDER:
        for name, expected in (('diagnose_batch_invariance.py', PROFILE_SHAS[profile]), ('numeric_trace.py', TRACE_SHA)):
            raw = e.read(base/profile/name)
            e.require(e.digest(raw) == expected, 'original derived profile changed')
            files[profile+'/tools/'+name] = raw
        for name, raw in NOTICES.items():
            files[profile+'/tools/'+name] = raw
    e.require(set(files) == e.required_files(), 'package dependency closure differs')
    return files


def write(path, raw):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify(folder, release_sha):
    release = e.decode(e.read(folder/'RELEASE.json'), release_sha)
    e.require(release['protocol'] == e.REMOTE.name and release['schema_version'] == 1
              and set(release['files']) == e.required_files(), 'release contract differs')
    actual = {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_symlink() or not p.is_dir()}
    e.require(actual == set(release['files']) | {'RELEASE.json'}, 'extra/missing candidate member')
    expected = sources()
    for name, sha in release['files'].items():
        raw = e.read(folder/name)
        e.require(e.digest(raw) == sha and raw == expected[name], 'candidate content differs: '+name)
        e.require((folder/name).stat().st_mode & 0o777 == 0o600, 'candidate source mode differs')
    for path in (folder, *(p for p in folder.rglob('*') if p.is_dir())):
        e.private_directory(path)
    return release


def build(folder):
    e.require(folder.is_absolute() and not folder.exists() and not folder.is_symlink(), 'new absolute output directory required')
    e.require(not any(p.is_symlink() for p in folder.parents), 'candidate parent aliases')
    before = sources()
    folder.mkdir(mode=0o700)
    for name, raw in sorted(before.items()):
        write(folder/name, raw)
    release = dict(schema_version=1, protocol=e.REMOTE.name, files={n:e.digest(raw) for n, raw in sorted(before.items())})
    raw = e.wire(release)
    write(folder/'RELEASE.json', raw)
    e.require(before == sources(), 'sources changed during build')
    verify(folder, e.digest(raw))
    return e.digest(raw)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('build','verify'))
    parser.add_argument('folder')
    parser.add_argument('release_sha256', nargs='?')
    args = parser.parse_args()
    os.umask(0o077)
    folder = Path(args.folder).absolute()
    if args.mode == 'build':
        e.require(args.release_sha256 is None, 'build cannot accept an existing release')
        result = build(folder)
    else:
        verify(folder, args.release_sha256)
        result = args.release_sha256
    print(json.dumps(dict(status='LOCAL_EXECUTION_CANDIDATE_VERIFIED', release_sha256=result,
        files=len(e.required_files()), folder=str(folder), resource_approval=False, inputs_frozen=False,
        production_model_loaded=False, ready_for_gpu=False, jobs_submitted=0)))
