"""SYNTHETIC ONLY. Separate test driver, deliberately excluded from release.

Runs packaged worker scheduling/sinks and archive verifier in three processes.
Strict loading, tensors/audio and gain evaluations are fixtures, NOT GPU evidence.
"""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('package',type=Path);p.add_argument('digest')
    p.add_argument('--mode',choices=['parent','A','B','verify'],default='parent')
    p.add_argument('--attempt',type=Path)
    a=p.parse_args()
    sys.path.insert(0,str(a.package))
    from e1_entry import verify_package,load_contract
    release=verify_package(a.package,a.digest);c=load_contract(a.package,release)
    from e1_artifacts import write_json,identity
    if a.mode=='parent':
        from e1_supervisor import run_e1
        parent=Path(tempfile.mkdtemp(prefix='e1-release-rehearsal-',dir=Path(__file__).parent))
        attempt=parent/'attempt'
        def command(mode):
            return [sys.executable,'-I','-B',str(Path(__file__).absolute()),str(a.package),a.digest,
                    '--mode',mode,'--attempt',str(attempt)]
        def verify_command(root,d,records):
            write_json(root/'VERIFY_REQUEST.json',records)
            return command('verify')
        result=run_e1(attempt,lambda label,d:command(label),verify_command,seconds=60)
        summary=dict(status='E1_PACKAGED_SYNTHETIC_PIPELINE_PASS',scope='synthetic only; not native or GPU acceptance',
            release_sha256=a.digest,predictions=result['verification']['array_verification']['predictions'],
            process_ids=[r['pid'] for r in result['records']],pipeline=identity(attempt/'PROCESS_COMPLETE.json'),
            checkpoint_loaded=False,cuda_initialized=False,jobs_submitted=0,production_ready=False)
        write_json(parent/'SUMMARY.json',summary)
        print(json.dumps(dict(summary,evidence=str(parent)),indent=2));return
    from e1_worker_archive import worker,verify_archive,verify_provenance
    if a.mode=='verify':
        records=json.loads((a.attempt/'VERIFY_REQUEST.json').read_bytes())
        # Harness-only relaxation; production archive entry always uses strict mode.
        with patch('e1_worker_archive.verify_provenance',side_effect=lambda m,s,p:verify_provenance(m,s,p,production=False)):
            result=verify_archive(a.attempt,c,records,'900001')
        write_json(a.attempt/'VERIFY/VERIFIED.json',result);return
    import os
    import numpy as np
    import torch
    from architecture_adapter import NAMES
    os.environ['SLURM_JOB_ID']='900001' # fixture only, no scheduler called
    base=SimpleNamespace(_tensor_hashes=lambda x:[str(v) for v in x.tolist()])
    core=SimpleNamespace(predict=lambda base,outer,s,c,l,p,d:(
        dict(nll=np.full(len(l),np.log(800),np.float32)),np.zeros((len(l),800),np.float32)))
    def provider(domain,bi,condition,ids):
        return torch.tensor(ids),torch.tensor(ids),torch.tensor([c['labels'][str(i)] for i in ids]),torch.zeros(len(ids),dtype=torch.int64)
    def formula(model,name):
        return dict(status='G5_FIXED_FEATURE_PASS',pass_name=name,reference='numpy_float64_independent',atol=2e-6,rtol=2e-6,
            checks=[dict(path='model_dict.'+n,mixture=m,masked=b,max_abs=0.,mean_max_abs=0.)
                    for n in NAMES for m in ('ones','signed') for b in (False,True)])
    ctx=dict(core=core,base=base,outer=SimpleNamespace(model=None),architecture_type=None,gain_type=None,
             device='cpu',batch_provider=provider,checkpoint_sha=c['checkpoint_sha256'],load_report=dict(
             loaded_trainable_numel_ratio=1.,trainable_numel=10,loaded_trainable_numel=10,
             native_preprocessing='selftrain_singleton_per_example_leveling'))
    with patch('e1_worker_archive.audited_e1_session',return_value=nullcontext(ctx)),\
         patch('e1_worker_archive.accept_loaded_formal40'),\
         patch('loaded_model_adapter.pass_context',side_effect=lambda *args:nullcontext()),\
         patch('gain_formula_check.check_installed_gains',side_effect=formula):
        worker(a.attempt/a.mode,c,a.mode,seconds=30,release_sha256=a.digest)
    if torch.cuda.is_initialized():raise ValueError('SYNTHETIC_INITIALIZED_CUDA')

if __name__=='__main__':main()
