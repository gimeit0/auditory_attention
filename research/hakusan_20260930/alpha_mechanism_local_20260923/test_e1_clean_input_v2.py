"""Pinned native function bodies with synthetic cache; not GPU acceptance."""
import ast
import __future__
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import torch
from e1_clean_input_v2 import clean_pair,CleanBatchProvider

BASE=Path(__file__).resolve().parent.parent

def functions(path,digest,names,env):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest: raise ValueError('TEST_SOURCE_SHA')
    tree=ast.parse(raw)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes}!=set(names): raise ValueError('FUNCTIONS')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec',
                 flags=__future__.annotations.compiler_flag),env)
    return env

class CleanTests(unittest.TestCase):
    def setUp(self):
        env=functions(Path('/Users/gigi/projects/auditory_attention/selftrain/data/diotic_attention.py'),
                      '26b5cf965aec1652f2d77be517f867bb284a2f53c2f53706b2c5aa2cc0ad9e8a',
                      ['crop_centered'],dict(np=np,SAMPLE_RATE=44100,CROP_SAMPLES=110250,HALF_CROP=55125))
        module=types.ModuleType('selftrain.data.diotic_attention')
        module.crop_centered=env['crop_centered']; module.CROP_SAMPLES=110250
        module.sum_equal_rms=lambda *_: self.fail('clean must not mix distractors')
        self.patch=patch.dict(sys.modules,{'selftrain.data.diotic_attention':module})
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.env=functions(BASE/'patch_stage_next/selftrain/scripts/eval_full_pilot.py',
                          '29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b',
                          ['_raw_scene_batch','_role_batch','_correct_cue_batch'],dict(np=np))
        self.frame=pd.DataFrame([dict(trial_id=i,scene_kind='clean',distractor_count=0,control_subset=0,
            target_speaker='s',correct_cue_speaker='s',target_path='t.mp3',correct_cue_path='c.mp3',
            target_label=2,target_anchor_center_s=1.5,correct_cue_anchor_center_s=1.5) for i in range(2)])
        self.cache=types.SimpleNamespace(get=lambda p: np.full(132300,1. if p.name=='t.mp3' else 2.,np.float32))
        self.kw=dict(raw_scene_batch=self.env['_raw_scene_batch'],role_batch=self.env['_role_batch'])
    def run_pair(self,**overrides):
        return clean_pair(self.frame,[0,1],self.cache,Path('/unused'),**(self.kw|overrides))
    def test_old_zero_new_nonzero_exact_target(self):
        old=self.env['_correct_cue_batch'](self.frame,self.cache,Path('/unused'))
        self.assertFalse(torch.any(old))
        pair=self.run_pair(); s,c,l=pair['target_only_correct_cue']; z,zero,_=pair['target_only_zero_cue']
        self.assertTrue(torch.all(c==2) and torch.all(s==1) and torch.equal(s,z))
        self.assertTrue(torch.equal(zero,old)); c.zero_(); s.zero_()
        self.assertTrue(torch.all(z==1))
    def test_accidental_zeroing_rejected(self):
        def wrong(f,r,c,p): return self.env['_correct_cue_batch'](f,c,p)
        with self.assertRaisesRegex(ValueError,'CUE_ZEROED'): self.run_pair(role_batch=wrong)
    def test_metadata_mutation_rejected(self):
        def wrong(f,r,c,p):
            t=self.env['_role_batch'](f,r,c,p); f.loc[0,'target_label']=3; return t
        with self.assertRaisesRegex(ValueError,'FRAME_MUTATED'): self.run_pair(role_batch=wrong)
    def test_wrong_order(self):
        with self.assertRaisesRegex(ValueError,'TRIAL_ORDER'):
            clean_pair(self.frame,[1,0],self.cache,Path('/unused'),**self.kw)
    def test_mixed_rejected(self):
        self.frame.loc[0,'scene_kind']='mixed'
        with self.assertRaisesRegex(ValueError,'CLEAN_ONLY'): self.run_pair()
    def test_cue_same_recording_rejected(self):
        self.frame.loc[0,'correct_cue_path']='t.mp3'
        with self.assertRaisesRegex(ValueError,'CUE_PAIR'): self.run_pair()
    def test_tail_and_repeat(self):
        p=CleanBatchProvider(self.frame,[[0],[1]],self.cache,Path('/unused'),**self.kw)
        for _ in range(2):
            for i in range(2): self.assertEqual(p(i,[i])['target_only_correct_cue'][0].shape,(1,2,110250))
    def test_provider_wrong_batch(self):
        p=CleanBatchProvider(self.frame,[[0],[1]],self.cache,Path('/unused'),**self.kw)
        with self.assertRaisesRegex(ValueError,'BATCH_ORDER'): p(1,[1])

if __name__=='__main__': unittest.main()
