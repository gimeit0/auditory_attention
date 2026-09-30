"""Bounded adapter preserving historical raw scene/cue construction order.

Caller must supply source-verified callbacks and a verified full bank. Keeps only
one scene batch and its controls, regenerating at each pass; never caches a bank.
"""
import numpy as np
import torch
from e0_layout_reference import CONDITIONS,require

class NativeBatchProvider:
    def __init__(self,base,bank,historical_hashes,layout,clips_dir,cache_class,
                 raw_scene_batch,correct_cue_batch,role_batch):
        require(bank.trial_id.is_unique,'NATIVE_DUPLICATE_TRIAL')
        self.bank=bank.set_index('trial_id',drop=False).copy(deep=True)
        self.layout=layout
        self.base,self.hashes,self.clips=base,historical_hashes,clips_dir
        self.cache=cache_class(max_items=128)
        self.raw,self.correct,self.role=raw_scene_batch,correct_cue_batch,role_batch
        self.schedule=[(k,c,list(ids)) for k in range(len(layout['batches']))
                       for c in CONDITIONS if (ids:=layout['condition_batches'][c][k])]
        self.position=0
        self.payloads=None
        self.snr_max_abs=0.
        self.regenerated_batches=0

    def __call__(self,batch_index,condition,ids):
        require((batch_index,condition,ids)==self.schedule[self.position],'NATIVE_CALL_ORDER')
        if condition=='correct':
            frame=self.bank.loc[ids].copy(deep=True)
            before=frame.to_csv(index=False)
            errors=[]
            scene=self.raw(frame,self.cache,self.clips,snr_errors=errors)
            cue=self.correct(frame,self.cache,self.clips)
            require(self.base._tensor_hashes(scene)==[self.hashes[i] for i in ids],'NATIVE_SCENE_HASH')
            labels=torch.tensor(frame.target_label.to_numpy(dtype=np.int64))
            probes=torch.tensor(np.where(frame.scene_kind=='mixed',frame.distractor_1_label,0).astype(np.int64))
            selected=np.flatnonzero(frame.control_subset.to_numpy(dtype=int)==1)
            control=frame.iloc[selected]
            self.payloads={'correct':(scene,cue,labels,probes)}
            for c in CONDITIONS[1:]:
                require(control.trial_id.tolist()==self.layout['condition_batches'][c][batch_index],
                        'NATIVE_CONTROL_LAYOUT')
            if len(selected):
                cues={'shuffled':self.role(control,'shuffled_cue',self.cache,self.clips),
                      'silent':torch.zeros_like(cue[selected]),
                      'distractor':self.role(control,'probe_distractor_cue',self.cache,self.clips)}
                self.payloads.update({c:(scene[selected],v,labels[selected],probes[selected]) for c,v in cues.items()})
            require(frame.to_csv(index=False)==before,'NATIVE_BANK_MUTATION')
            require(all(np.isfinite(errors)),'NATIVE_NONFINITE_SNR')
            self.snr_max_abs=max([self.snr_max_abs]+[abs(float(e)) for e in errors])
            self.regenerated_batches+=1
        result=self.payloads[condition]
        self.position=(self.position+1)%len(self.schedule)
        return result
