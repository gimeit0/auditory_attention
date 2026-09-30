"""Bounded, eager-only summaries at exactly eight alpha=.5 gain outputs.

No activation tensors retained, no hook output replacement, no global hooks.
Statistics perform reductions/device synchronization: GPU overhead is unmeasured.
"""
from contextlib import contextmanager
import json
import math
import torch
from architecture_adapter import NAMES, InterventionGain

class GainObserver:
    def __init__(self,model,max_events=144,max_bytes=262144,max_tensor_numel=64000000):
        if any(type(n) is not int or n<=0 for n in (max_events,max_bytes,max_tensor_numel)):
            raise ValueError('OBSERVER_BUDGET')
        self.model=model
        self.max_events,self.max_bytes,self.max_tensor_numel=max_events,max_bytes,max_tensor_numel
        self.records=[]
        self.handles=[]
        self.active=None
        self.bytes=0
        self.used=False

    def summary(self,t):
        if (not isinstance(t,torch.Tensor) or t.dtype!=torch.float32 or t.ndim!=4
            or not 0<t.numel()<=self.max_tensor_numel or t.requires_grad):
            raise ValueError('OBSERVER_TENSOR')
        x=t.detach()
        with torch.no_grad():
            if not torch.isfinite(x).all(): raise ValueError('OBSERVER_NONFINITE')
            values=[float(x.min()),float(x.max()),float(x.mean(dtype=torch.float64))]
        if not all(math.isfinite(v) for v in values): raise ValueError('OBSERVER_NONFINITE_SUMMARY')
        return dict(shape=list(t.shape),dtype=str(t.dtype),device=str(t.device),
                    minimum=values[0],maximum=values[1],mean=values[2])

    def hook(self,name):
        def record(module,args,output):
            if self.active is None: raise ValueError('OBSERVER_OUTSIDE_BATCH')
            index=self.active['events']
            if index>=8 or NAMES[index]!=name: raise ValueError('OBSERVER_EVENT_ORDER')
            if len(self.records)>=self.max_events: raise ValueError('OBSERVER_EVENT_BUDGET')
            # Check a conservative per-record reservation before reductions.
            if self.bytes+4096>self.max_bytes: raise ValueError('OBSERVER_BYTE_BUDGET')
            if len(args)!=3: raise ValueError('OBSERVER_ARGUMENTS')
            cue,mixture,mask=args
            if mask is not None: raise ValueError('OBSERVER_EXPECTED_NATIVE_NONE_MASK')
            if len(self.active['trial_ids'])!=mixture.shape[0]: raise ValueError('OBSERVER_BATCH_SIZE')
            item=dict(batch_index=self.active['batch_index'],condition=self.active['condition'],
                      trial_ids=list(self.active['trial_ids']),path='model_dict.'+name,
                      cue=self.summary(cue),mixture=self.summary(mixture),output=self.summary(output))
            size=len(json.dumps(item,sort_keys=True,allow_nan=False).encode())
            if size>4096: raise ValueError('OBSERVER_RECORD_BUDGET')
            self.records.append(item)
            self.bytes+=size
            self.active['events']+=1
            return None  # PyTorch hook must not replace the original output.
        return record

    def __enter__(self):
        if self.used: raise ValueError('OBSERVER_SINGLE_USE')
        self.used=True
        modules=[self.model.model_dict[n] for n in NAMES]
        if len({id(m) for m in modules})!=8: raise ValueError('OBSERVER_ALIASED_GAIN')
        if any(type(m) is not InterventionGain or m.mode!='alpha' or m.alpha!=.5 or m.training
               or m._forward_hooks or m._forward_pre_hooks or m._backward_hooks for m in modules):
            raise ValueError('OBSERVER_UNSUPPORTED_GAIN_OR_HOOK')
        try:
            for name,m in zip(NAMES,modules): self.handles.append(m.register_forward_hook(self.hook(name)))
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        for handle in self.handles: handle.remove()
        self.handles=[]
        self.active=None

    def __exit__(self,exc_type,exc,tb):
        self.close()
        return False

    @contextmanager
    def batch(self,batch_index,condition,trial_ids):
        if not self.handles or self.active is not None: raise ValueError('OBSERVER_BATCH_CONTEXT')
        if (type(batch_index) is not int or batch_index<0 or condition not in ('correct','shuffled','silent','distractor')
            or type(trial_ids) is not list or not 0<len(trial_ids)<=16
            or any(type(i) is not int or i<0 for i in trial_ids) or len(set(trial_ids))!=len(trial_ids)):
            raise ValueError('OBSERVER_BATCH_IDENTITY')
        self.active=dict(batch_index=batch_index,condition=condition,trial_ids=tuple(trial_ids),events=0)
        try:
            yield
            if self.active['events']!=8: raise ValueError('OBSERVER_MISSING_EVENT')
        finally:
            self.active=None
