"""Stage-specific CPU loading seam; audited production construction is external.

No selftrain compile-key rewrites, non-strict load or identity substitution.
Caller must supply a contract-bound checkpoint record and verified constructor.
This module alone does not attest snapshot imports or production authorization.
"""
import torch
from e2_archive_loader import load_bound_archive
from e2_stage_inspection import stage_summary
from e2_catalog import validate_record

NATIVE_SIGNATURE='289c4ac10e04b6b09533c0b8de2d38d04aa81ac8aa971750e4a92cb920ef6faa'
FORMAL_SHA='2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff'

def apply_exact_state(model,state):
    expected=model.state_dict()
    if set(state)!=set(expected): raise ValueError('STATE_KEYS')
    for name,value in state.items():
        if not isinstance(value,torch.Tensor) or value.device.type!='cpu':
            raise ValueError('CPU_STATE_REQUIRED')
        if value.shape!=expected[name].shape or value.dtype!=expected[name].dtype:
            raise ValueError('STATE_SHAPE_DTYPE')
        if not torch.isfinite(value).all(): raise ValueError('NONFINITE_STATE')
    result=model.load_state_dict(state,strict=True)
    if result.missing_keys or result.unexpected_keys: raise ValueError('INCOMPLETE_LOAD')
    params=dict(model.named_parameters())
    if not params or not set(params)<=set(state): raise ValueError('PARAMETER_COVERAGE')
    model.eval()
    for p in model.parameters(): p.requires_grad_(False)
    return dict(loaded_trainable_numel_ratio=1.0,trainable_numel=sum(p.numel() for p in params.values()),
                loaded_trainable_numel=sum(p.numel() for p in params.values()),
                strict=True,key_rewrite=False)

def load_stage(raw,record,constructor):
    validate_record(record)
    rounds=record['completed_epochs_candidate']
    if type(rounds) is not int or rounds not in (0,1,2,4,8,16,24,40): raise ValueError('STAGE')
    checkpoint=load_bound_archive(raw,record['sha256'])
    final=record['filename']=='formal-final.ckpt'
    if final and (rounds!=40 or record['sha256']!=FORMAL_SHA): raise ValueError('FORMAL_IDENTITY')
    summary=stage_summary(checkpoint,rounds,final_after_fit=final)
    if summary['state_signature_sha256']!=NATIVE_SIGNATURE: raise ValueError('NATIVE_STATE_SIGNATURE')
    model=constructor()
    report=apply_exact_state(model,checkpoint['state_dict'])
    model.on_load_checkpoint(checkpoint)
    # The callback may restore RNG/metadata, but must not change loaded weights.
    for name,value in model.state_dict().items():
        if not torch.equal(value,checkpoint['state_dict'][name]): raise ValueError('CALLBACK_CHANGED_STATE')
    model.eval()
    for p in model.parameters(): p.requires_grad_(False)
    report.update(stage_id='completed_epochs_'+str(rounds),completed_epochs=rounds,
                  checkpoint_sha256=record['sha256'],stage_summary=summary,
                  native_preprocessing='selftrain_singleton_per_example_leveling',
                  production_provenance_verified=False)
    return model,report
