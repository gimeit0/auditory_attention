"""Combine native main-layout provider and the accepted clean-v2 paired path."""
import torch
from native_batch_provider import NativeBatchProvider
from e1_clean_input_v2 import CleanBatchProvider
from e0_layout_reference import require

class E1Provider:
    def __init__(self,base,bank,hashes,c,clips,cache_class,raw,correct,role):
        layout=dict(batches=c['main_batches'],condition_batches={
            k:c['main_batches'] if k=='correct' else c['control_batches']
            for k in ('correct','shuffled','silent','distractor')})
        self.main=NativeBatchProvider(base,bank,hashes,layout,clips,cache_class,raw,correct,role)
        self.clean=CleanBatchProvider(bank,c['clean_batches'],cache_class(max_items=128),clips,
                                    raw_scene_batch=raw,role_batch=role)
        self.clean_pending=None
    def __call__(self,domain,bi,condition,ids):
        if domain=='main':
            require(self.clean_pending is None,'CLEAN_PAIR_INCOMPLETE')
            return self.main(bi,condition,ids)
        require(domain=='clean','DOMAIN')
        if condition=='correct_cue':
            require(self.clean_pending is None,'CLEAN_PAIR_INCOMPLETE')
            pair=self.clean(bi,ids)
            self.clean_pending=(bi,list(ids),pair['target_only_zero_cue'])
            scene,cue,labels=pair['target_only_correct_cue']
        else:
            require(condition=='zero_cue' and self.clean_pending is not None,'CLEAN_PAIR_ORDER')
            k,wanted,payload=self.clean_pending
            require((bi,list(ids))==(k,wanted),'CLEAN_PAIR_IDS')
            scene,cue,labels=payload; self.clean_pending=None
        return scene,cue,labels,torch.zeros_like(labels)
