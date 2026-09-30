"""Local E1 release builder. Refuses overwrite; no network or scheduler calls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from e1_entry import canonical,identity,verify_package,SCOPE,BUDGET
from e1_inputs import HERE,build_contract,BANK_SHA,checked
from e1_execution import execution_spec,ALPHA_GRID,PREVIOUS_ALPHA_GRID,PROVENANCE_FIELDS_REQUIRED

DECISION_DOCS={'e0_readout_memo':'26_E0_SCIENTIFIC_READOUT_746603_20260927.md',
               'decision_draft':'27_E1_REVISION_DECISION_DRAFT_20260927.md',
               'statistics_contract_v2':'28_E1_STATISTICS_CONTRACT_V2_20260927.md',
               'statistics_contract_v3_correction':'29_E1_CONTRACT_V3_RESIDUAL_CORRECTION_20260927.md'}

def decision_record():
    docs={}
    for key,name in DECISION_DOCS.items():
        p=HERE/name
        if p.is_symlink() or not p.is_file(): raise ValueError('DECISION_DOC_MISSING: '+name)
        docs[key]=dict(file=name,**identity(p))
    return dict(decided='2026-09-27',decided_by='user, following the assistant recommendation in doc 27 §9; advisor review pending',
        A_formula='keep g_alpha = 1 - alpha*(1 - g); E0 acceptance (job 746603) remains valid',
        B_grid=dict(previous=PREVIOUS_ALPHA_GRID,current=ALPHA_GRID,note='.875 replaces .25; three negative controls stay at alpha .5; predictions unchanged'),
        C_overlap='keep the 19 E0/E1 overlapping trials (5 clean); disclose, flag, report a sensitivity version excluding them',
        D_probe='no additional probe before E1',
        E_budget='candidate cap unchanged (1 A100, 8 CPU, 64 GiB, 180 min); separate approval still required',
        statistics_contract_signoff='PENDING: external signoff must bind BOTH statistics_contract_v2 and statistics_contract_v3_correction; no GPU authorization',
        provenance_fields_required=list(PROVENANCE_FIELDS_REQUIRED),documents=docs)

FILES=('e1_entry.py','production_e1.py','submit_e1_once.py','run_e1.sbatch',
       'e1_inputs.py','e1_input_check.py','e1_execution.py','e1_audited_session.py',
       'e1_provider.py','e1_clean_input_v2.py','e1_supervisor.py','e1_worker_archive.py',
       'snapshot_source_import.py','native_batch_provider.py','loaded_model_adapter.py',
       'gain_formula_check.py','architecture_adapter.py','alpha_gain.py',
       'e0_layout_reference.py','check_e0_proposal.py','e1_artifacts.py',
       'E1_DATA_FREEZE_20260926_v1.json','E1_CANDIDATE_2000_20260926.json')

def build(destination):
    destination=Path(destination)
    c=build_contract()
    core=HERE.parent/'same_bank_compare_2026_09_19_full_v3/eager_compare.py'
    checked(core,'09cb0c4816d001d172215ead49a1a0c9efde07b794125da4980dd822883a4d5b')
    bank=HERE.parent/'docs/superpowers/evidence/p05-confirmation-set-20260919/frozen_bank.tsv'
    checked(bank,BANK_SHA)
    destination.mkdir(mode=0o700,parents=False,exist_ok=False)
    for name in FILES:
        if (HERE/name).is_symlink(): raise ValueError('SOURCE_SYMLINK')
        shutil.copyfile(HERE/name,destination/name)
    shutil.copyfile(core,destination/'eager_compare.py')
    shutil.copyfile(bank,destination/'frozen_bank.tsv')
    with (destination/'E1_CONTRACT.json').open('xb') as f: f.write(canonical(c))
    if build_contract(destination)!=c: raise ValueError('PORTABLE_CONTRACT')
    release=dict(schema_version=1,scope=SCOPE,budget=BUDGET,predictions=38400,
                 contract_sha256=hashlib.sha256(canonical(c)).hexdigest(),execution=execution_spec(c),
                 submission='held_once_manual_review_required',
                 scientific_status='CONTRACT_V3_CORRECTION_BOUND_SIGNOFF_PENDING',
                 decision_record=decision_record(),
                 authorization='THIS_MANIFEST_IS_NOT_GPU_AUTHORIZATION',
                 files={p.name:identity(p) for p in sorted(destination.iterdir())})
    with (destination/'RELEASE.json').open('xb') as f: f.write(canonical(release))
    digest=identity(destination/'RELEASE.json')['sha256']
    verify_package(destination,digest)
    return dict(package=str(destination),release_sha256=digest,
                entry=identity(destination/'e1_entry.py'),runner=identity(destination/'run_e1.sbatch'),
                contract_sha256=release['contract_sha256'],jobs_submitted=0)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination')
    print(json.dumps(build(p.parse_args().destination),indent=2))
