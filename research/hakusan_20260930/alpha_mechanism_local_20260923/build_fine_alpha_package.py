"""Local-only portable candidate builder. No GPU authority is created here."""
import argparse
import json
from pathlib import Path
import shutil
from e1_inputs import HERE, build_contract, checked, BANK_SHA
from e1_artifacts import canonical
from e2_history_bridge import read_reference, DEFAULT_ROOT
from fine_alpha_contract import contract, check_production_counts, REMOTE, BUDGET, SCOPE, PREDICTIONS, SCIENCE_PREDICTIONS
from fine_alpha_entry import identity, verify_package

FILES = ('fine_alpha_contract.py', 'fine_alpha_gain.py', 'fine_alpha_execution.py',
         'fine_alpha_archive.py', 'fine_alpha_pipeline.py', 'fine_alpha_entry.py', 'fine_alpha_submit_once.py',
         'fine_alpha_submission_queue.py',
         'e1_inputs.py', 'e1_execution.py', 'e1_audited_session.py', 'e1_provider.py', 'e1_clean_input_v2.py',
         'e1_worker_archive.py', 'e1_artifacts.py', 'e2_history_bridge.py', 'e2_matrix.py', 'e2_catalog.py',
         'e2_process.py', 'e2_submit_once.py', 'e2_entry.py', 'snapshot_source_import.py',
         'native_batch_provider.py', 'loaded_model_adapter.py', 'gain_formula_check.py', 'architecture_adapter.py',
         'alpha_gain.py', 'e0_layout_reference.py', 'check_e0_proposal.py',
         'E1_DATA_FREEZE_20260926_v1.json', 'E1_CANDIDATE_2000_20260926.json')

def build(destination):
    destination = Path(destination); c = build_contract(); read_reference()
    core = HERE.parent/'same_bank_compare_2026_09_19_full_v3/eager_compare.py'
    checked(core, '09cb0c4816d001d172215ead49a1a0c9efde07b794125da4980dd822883a4d5b')
    bank = HERE.parent/'docs/superpowers/evidence/p05-confirmation-set-20260919/frozen_bank.tsv'
    checked(bank, BANK_SHA)
    destination.mkdir(mode=0o700, exist_ok=False)
    for name in FILES:
        identity(HERE/name); shutil.copyfile(HERE/name, destination/name)
    shutil.copyfile(core, destination/'eager_compare.py'); shutil.copyfile(bank, destination/'frozen_bank.tsv')
    reference = destination/'reference'; reference.mkdir(mode=0o700)
    shutil.copyfile(DEFAULT_ROOT/'WORKER.json', reference/'WORKER.json')
    for row in json.loads((reference/'WORKER.json').read_text())['outputs']:
        if row['key'][2] == 'alpha_1': shutil.copyfile(DEFAULT_ROOT/row['file'], reference/row['file'])
    if build_contract(destination) != c: raise ValueError('PORTABLE_INPUTS')
    read_reference(reference)
    runner = (HERE/'run_fine_alpha.sbatch').read_text().replace('@REMOTE_ROOT@', REMOTE)
    (destination/'run_fine_alpha.sbatch').write_text(runner)
    release = dict(schema_version=1, scope=SCOPE, contract=check_production_counts(contract(c)), predictions=PREDICTIONS, budget=BUDGET,
        status='LOCAL_CANDIDATE_NOT_GPU_AUTHORIZED', production_validated=False,
        files={str(p.relative_to(destination)): identity(p) for p in sorted(destination.rglob('*')) if p.is_file()})
    (destination/'RELEASE.json').write_bytes(canonical(release))
    digest = identity(destination/'RELEASE.json')['sha256']; verify_package(destination, digest)
    return dict(status='FINE_ALPHA_LOCAL_PACKAGE_BUILT', package=str(destination), release_sha256=digest,
                files=len(release['files']), predictions=PREDICTIONS, science_predictions=SCIENCE_PREDICTIONS, jobs_submitted=0)

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('destination'); a = p.parse_args()
    print(json.dumps(build(a.destination), indent=2))
