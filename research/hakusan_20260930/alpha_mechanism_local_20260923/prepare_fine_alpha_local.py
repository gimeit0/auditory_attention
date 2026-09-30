"""Local regression, immutable-package audit and candidate build. No networking."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from e1_artifacts import write_json
from fine_alpha_entry import identity
from build_fine_alpha_package import build

HERE = Path(__file__).absolute().parent
LEGACY = ('release_20260925_v2/package', 'release_e1_20260927_v3/package_ready',
          'release_e2_20260928_candidate_v1', 'release_e2_pilot_20260928_candidate_v1',
          'release_fine_alpha_20260928_candidate_v1/package',
          'release_fine_alpha_20260928_candidate_v2/package',
          'release_fine_alpha_20260928_candidate_v3/package')

def legacy_audit():
    records = []
    for relative in LEGACY:
        root = HERE/relative; manifest = json.loads((root/'RELEASE.json').read_text())
        if relative == 'release_fine_alpha_20260928_candidate_v1/package':
            if identity(root/'RELEASE.json')['sha256'] != 'b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f':
                raise ValueError('FROZEN_FINE_V1_RELEASE_CHANGED')
        if relative == 'release_fine_alpha_20260928_candidate_v2/package':
            if identity(root/'RELEASE.json')['sha256'] != 'a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0':
                raise ValueError('FROZEN_FINE_V2_RELEASE_CHANGED')
        if relative == 'release_fine_alpha_20260928_candidate_v3/package':
            if identity(root/'RELEASE.json')['sha256'] != '1644b8bd3e9eea855476f123e904707f82c9d1465f4345f43432c847893e87d7':
                raise ValueError('FROZEN_FINE_V3_RELEASE_CHANGED')
        for filename, wanted in manifest['files'].items():
            if identity(root/filename) != wanted: raise ValueError('LEGACY_FILE_CHANGED: '+relative+'/'+filename)
        records.append(dict(package=relative, release=identity(root/'RELEASE.json'), files=len(manifest['files'])))
    return records

def run(argv, root, name, timeout):
    start = time.monotonic(); logfile = root/(name+'.log')
    with logfile.open('xb') as out:
        completed = subprocess.run(argv, stdout=out, stderr=subprocess.STDOUT, cwd=HERE.parent, timeout=timeout)
    result = dict(argv=argv, returncode=completed.returncode, elapsed_seconds=time.monotonic()-start, log=identity(logfile))
    write_json(root/(name+'.json'), result)
    if completed.returncode: raise RuntimeError('LOCAL_CHECK_FAILED: '+name)
    return result

def prepare(destination):
    root = Path(destination); root.mkdir(mode=0o700, exist_ok=False)
    before = legacy_audit(); write_json(root/'LEGACY_BEFORE.json', before)
    tests = run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(HERE), '-v'], root, 'regression', 900)
    summary = re.search(r'Ran (\d+) tests in ([\d.]+)s\s+OK(?: \(skipped=(\d+)\))?\s*$', (root/'regression.log').read_text())
    if not summary: raise ValueError('REGRESSION_NOT_COMPLETE')
    skipped = int(summary.group(3) or 0)
    # Only the post-freeze driver-test modules of THIS candidate may be skipped (they need the built package).
    skipped_names = re.findall(r'^(\S+) \(unittest\.loader\.ModuleSkipped\.\S+\) \.\.\. skipped', (root/'regression.log').read_text(), re.M)
    if skipped != len(skipped_names) or any(not n.startswith('test_fine_alpha_') or 'v4' not in n for n in skipped_names):
        raise ValueError('UNEXPECTED_SKIPPED_TESTS')
    package = build(root/'package'); write_json(root/'BUILD.json', package)
    check = run([sys.executable, '-I', '-B', str(root/'package/fine_alpha_entry.py'), 'check', package['release_sha256']],
                root, 'package-check', 60)
    run(['/bin/bash', '-n', str(root/'package/run_fine_alpha.sbatch')], root, 'runner-syntax', 10)
    after = legacy_audit(); write_json(root/'LEGACY_AFTER.json', after)
    if before != after: raise ValueError('LEGACY_CHANGED_DURING_PREPARE')
    report = dict(status='FINE_ALPHA_LOCAL_CANDIDATE_VERIFIED_NOT_GPU_AUTHORIZED',
        release_sha256=package['release_sha256'], tests=int(summary.group(1)), regression=tests,
        skipped_until_frozen=skipped_names,
        package_check=check, legacy_files_verified=sum(p['files'] for p in before),
        source_files={p.name: identity(p) for p in sorted(HERE.glob('*fine_alpha*')) if p.is_file()},
        network_access=False, production_checkpoint_loaded=False, gpu_jobs_submitted=0,
        scientific_results_obtained=False, pending=['remote_publish', 'native_source_check', 'gpu_budget', 'single_held_submit',
                                                  'resource_review', 'separate_release_authorization', 'inference', 'offline_verification', 'science_readout'])
    write_json(root/'LOCAL_ACCEPTANCE.json', report)
    print(json.dumps(dict(status=report['status'], tests=report['tests'], release_sha256=package['release_sha256'],
                          legacy_files_verified=report['legacy_files_verified'], directory=str(root)), indent=2))

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('destination'); args = p.parse_args()
    prepare(Path(args.destination).absolute())
