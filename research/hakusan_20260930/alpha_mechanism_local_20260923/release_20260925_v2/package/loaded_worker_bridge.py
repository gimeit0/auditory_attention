"""Local worker-body seam for an already loaded model, not a launch program.

The production caller still owns strict-load provenance, audio inputs, pinned
imports, independent processes and watchdog. No CLI or implicit remote actions.
"""
import numpy as np
from e0_layout_reference import CONDITIONS, reference, bitwise_bridge, require
from loaded_model_adapter import accept_loaded_formal40, pinned_core, FORMAL_SHA
from model_stage_driver import execute_stages

def bridging_sink(reference_data,sink,checks):
    def checked(process,name,payload,events):
        if name in ('original','alpha_1'):
            for condition in CONDITIONS:
                actual=payload[condition]
                expected=reference_data[condition]
                bitwise_bridge(expected,actual['trial_ids'],actual['logits'])
                # Archive CSV stores FP32 NLL as decimals; restore that dtype.
                nll=np.asarray(expected['nll'],dtype=np.float32)
                require(actual['nll'].dtype==np.float32 and actual['nll'].shape==nll.shape,
                        'HISTORICAL_NLL_SHAPE_DTYPE')
                require(actual['nll'].tobytes()==nll.tobytes(),'HISTORICAL_NLL_BITS')
            checks.append(dict(process=process,pass_name=name,status='HISTORICAL_ENDPOINT_BITS_PASS'))
        sink(process,name,payload,events)
    return checked

def run_loaded_worker(base,outer,load_report,checkpoint_sha,architecture_type,gain_type,
                      layout,process,batch_provider,device,sink,*,deadline_seconds=1500,
                      reference_directory=None,reference_sha256=None):
    # Real pinned historical archive is mandatory here, not a caller-provided baseline.
    require(checkpoint_sha==FORMAL_SHA,'WORKER_MODEL_IDENTITY')
    if reference_directory is None:
        require(reference_sha256 is None,'REFERENCE_ARGUMENTS')
        refs=reference(layout)
    else:
        from portable_reference import load_reference
        refs=load_reference(reference_directory,layout,reference_sha256)
    core=pinned_core()
    acceptance=accept_loaded_formal40(core,outer,load_report,'formal40',checkpoint_sha,
                                    architecture_type,gain_type)
    checks=[]
    result=execute_stages(core,base,outer,architecture_type,gain_type,layout,process,
                          batch_provider,device,bridging_sink(refs,sink,checks),
                          deadline_seconds=deadline_seconds)
    require(len(checks)==2,'HISTORICAL_BRIDGE_INCOMPLETE')
    return dict(status='LOADED_WORKER_BRIDGE_FINISHED_NOT_QUALIFIED',stage=result,
                acceptance=acceptance,historical_checks=checks,reference_job_id='728520',
                production_verified=False)
