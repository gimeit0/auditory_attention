"""Paired target-only inputs, explicit correct/zero cue semantics.

Caller binds source-verified native callbacks and frozen bank/layout. This module
does not load a model, authenticate arbitrary callbacks, or authorize submission.
"""
import torch

def require(ok, message):
    if not ok: raise ValueError(message)

def tensor_ok(t, n, name):
    require(isinstance(t,torch.Tensor) and t.device.type=='cpu' and
            t.dtype==torch.float32 and tuple(t.shape)==(n,2,110250), name+'_SHAPE_DTYPE')
    require(bool(torch.isfinite(t).all()),name+'_NONFINITE')
    require(bool(torch.any(t!=0,dim=(1,2)).all()),name+'_ZEROED')

def clean_pair(frame, expected_ids, cache, clips_dir, *, raw_scene_batch, role_batch):
    """One matched layout for new correct cue and old zero cue; no clean flag edit."""
    require(len(expected_ids)>0 and len(set(expected_ids))==len(expected_ids),'IDS')
    require(frame.trial_id.tolist()==list(expected_ids),'TRIAL_ORDER')
    require(bool((frame.scene_kind=='clean').all()) and
            bool((frame.distractor_count==0).all()) and
            bool((frame.control_subset==0).all()),'CLEAN_ONLY')
    require(bool((frame.target_speaker==frame.correct_cue_speaker).all()) and
            bool((frame.target_path!=frame.correct_cue_path).all()),'CUE_PAIR')
    require(bool(frame.target_label.between(0,799).all()),'LABELS')
    work=frame.copy(deep=True)
    before=work.to_csv(index=False)
    scene=raw_scene_batch(work,cache,clips_dir)
    tensor_ok(scene,len(work),'SCENE')
    saved=scene.clone()
    # Deliberately invoke _role_batch, NEVER _correct_cue_batch (which zeros clean).
    cue=role_batch(work,'correct_cue',cache,clips_dir)
    tensor_ok(cue,len(work),'CUE')
    require(torch.equal(scene,saved),'SCENE_MUTATED_BY_CUE')
    require(work.to_csv(index=False)==before,'FRAME_MUTATED')
    labels=torch.tensor(work.target_label.tolist(),dtype=torch.int64)
    # Independent storage across variants, preserving exact target bytes.
    return {'target_only_correct_cue':(saved.clone(),cue.clone(),labels.clone()),
            'target_only_zero_cue':(saved.clone(),torch.zeros_like(cue),labels.clone())}

class CleanBatchProvider:
    def __init__(self,bank,batches,cache,clips_dir,*,raw_scene_batch,role_batch):
        require(bank.trial_id.is_unique,'DUPLICATE_BANK_ID')
        flat=[i for b in batches for i in b]
        require(bool(flat) and len(set(flat))==len(flat) and all(0<len(b)<=16 for b in batches),'LAYOUT')
        self.bank=bank.set_index('trial_id',drop=False).copy(deep=True)
        require(set(flat)<=set(self.bank.index),'UNKNOWN_TRIAL')
        self.batches=[list(b) for b in batches]
        self.cache,self.clips=cache,clips_dir
        self.raw,self.role=raw_scene_batch,role_batch
        self.position=0

    def __call__(self,batch_index,ids):
        require(batch_index==self.position and list(ids)==self.batches[self.position],'BATCH_ORDER')
        result=clean_pair(self.bank.loc[ids],ids,self.cache,self.clips,
                          raw_scene_batch=self.raw,role_batch=self.role)
        self.position=(self.position+1)%len(self.batches)
        return result
