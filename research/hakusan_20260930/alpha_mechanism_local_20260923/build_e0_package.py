"""Local immutable package builder. No uploads or job submission."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from e0_archive_harness import layout,identity,write_json
from portable_reference import export_reference
from e0_entry import verify_package

HERE=Path(__file__).resolve().parent
FILES=('e0_entry.py','production_e0.py','submit_e0_once.py','run_e0.sbatch',
       'portable_reference.py','audited_model_session.py','snapshot_source_import.py','native_batch_provider.py',
       'loaded_worker_bridge.py','loaded_model_adapter.py','model_stage_driver.py',
       'gain_formula_check.py','gain_observer.py','architecture_adapter.py','alpha_gain.py',
       'e0_layout_reference.py','check_e0_proposal.py','e0_archive_harness.py',
       'two_process_supervisor.py','rehearse_model_pair.py','E0_LAYOUT_96.json')

def build(destination):
    destination=Path(destination)
    destination.mkdir(mode=0o700,exist_ok=False)
    for name in FILES: shutil.copyfile(HERE/name,destination/name)
    core=HERE.parent/'same_bank_compare_2026_09_19_full_v3/eager_compare.py'
    if hashlib.sha256(core.read_bytes()).hexdigest()!='09cb0c4816d001d172215ead49a1a0c9efde07b794125da4980dd822883a4d5b':
        raise ValueError('PINNED_CORE_CHANGED')
    shutil.copyfile(core,destination/'eager_compare.py')
    reference_sha=export_reference(destination/'reference',layout())
    files={str(p.relative_to(destination)):identity(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    release=dict(schema_version=1,scope='E0_FORMAL40_NATIVE_20260925_V2',files=files,
                 reference_sha256=reference_sha,wall_minutes=30,gpus=1,cpus=8,host_memory_gib=64,
                 coordinator_deadline_seconds=1500,submission='held_once_manual_review_required')
    write_json(destination/'RELEASE.json',release)
    digest=hashlib.sha256((destination/'RELEASE.json').read_bytes()).hexdigest()
    verify_package(destination,digest)
    return dict(package=str(destination),release_sha256=digest,reference_sha256=reference_sha,jobs_submitted=0)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('destination')
    print(json.dumps(build(parser.parse_args().destination),indent=2))
