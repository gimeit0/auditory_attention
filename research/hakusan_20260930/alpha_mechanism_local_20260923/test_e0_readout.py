import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from e0_readout_746603 import (CONDITIONS, load_bank, readout, run, recomputed_nll)

CLASSES=800
LABELS={0:5,1:17,2:799,3:0}          # class indices; target_index below is deliberately different
KINDS={0:'mixed',1:'mixed',2:'clean',3:'clean'}
CORRECT_IDS=[0,1,2,3]
CONTROL_IDS=[0,1]

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_bank(path):
    lines=['manifest_version\ttrial_id\tscene_kind\ttarget_index\ttarget_label\ttarget_norm']
    for t in CORRECT_IDS: lines.append(f'1\t{t}\t{KINDS[t]}\t{100+t}\t{LABELS[t]}\tword{t}')
    Path(path).write_text('\n'.join(lines)+'\n')
    return sha(path)

def logits_for(ids,hit_rows,seed,scale=1.):
    rng=np.random.default_rng(seed)
    x=(rng.standard_normal((len(ids),CLASSES))*scale).astype(np.float32)
    for k,t in enumerate(ids):
        x[k,LABELS[t]]+=10. if k in hit_rows else -10.
    return x

def arrays_for(name,seed,nll_shift=0.):
    """original/alpha_1: correct hits rows 0,1,2 (acc .75), shuffled hits row 0 (acc .5).
    alpha_0: correct rows 0,1 reused bitwise as shuffled (cue independence), no hits."""
    if name in ('original','alpha_1'):
        correct=logits_for(CORRECT_IDS,(0,1,2),seed); shuffled=logits_for(CONTROL_IDS,(0,),seed+1)
    else:
        correct=logits_for(CORRECT_IDS,(),seed,scale=30.); shuffled=correct[:2].copy()
    out={}
    for c,l,ids in (('correct',correct,CORRECT_IDS),('shuffled',shuffled,CONTROL_IDS),
                    ('silent',logits_for(CONTROL_IDS,(),seed+2),CONTROL_IDS),
                    ('distractor',logits_for(CONTROL_IDS,(1,),seed+3),CONTROL_IDS)):
        labels=np.array([LABELS[t] for t in ids])
        out[c+'_ids']=np.array(ids,dtype=np.int64); out[c+'_logits']=l
        out[c+'_nll']=(recomputed_nll(l,labels)+nll_shift).astype(np.float32)
    return out

def build(root,*,b_flip=False,nll_shift=0.,break_manifest=False):
    root=Path(root); state=root/'state'; state.mkdir(parents=True)
    bank_sha=write_bank(root/'bank.tsv')
    plan={'A':['original','alpha_1','alpha_0','alpha_05_observed'],'B':['original','alpha_1','alpha_0']}
    for label,names in plan.items():
        d=state/label; d.mkdir()
        passes=[]
        for i,name in enumerate(names):
            # original and alpha_1 share one seed so they are bitwise identical, as in the real E0 endpoint.
            arrays=arrays_for('alpha_0' if name=='alpha_05_observed' else name,
                              seed=7 if name in ('original','alpha_1') else 7+i,nll_shift=nll_shift)
            if b_flip and label=='B' and name=='alpha_0':
                arrays['correct_logits']=arrays['correct_logits'].copy()
                arrays['correct_logits'].view(np.uint32)[0,0]^=1
            filename=f'{i:02d}_{name}.npz'
            with (d/filename).open('xb') as f: np.savez(f,**arrays)
            passes.append(dict(name=name,file=filename,sha256=sha(d/filename),size=(d/filename).stat().st_size))
        if break_manifest and label=='A': passes[0]['sha256']='0'*64
        (d/'WORKER.json').write_text(json.dumps(dict(label=label,pid=100+len(label),scope='TEST',passes=passes)))
        (d/'PROVENANCE.json').write_text('{}')
    (state/'E0_COMPLETE.json').write_text(json.dumps(dict(status='E0_ENDPOINT_PASS',job_id='746603',
        scientific_alpha_result=False,release_sha256='r'*64,
        verification=dict(evaluation_role='REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST'))))
    return state,root/'bank.tsv',bank_sha

class E0ReadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        cls.state,cls.bank,cls.bank_sha=build(Path(cls.tmp.name)/'clean')
        cls.result=readout(cls.state,cls.bank,cls.bank_sha)

    def row(self,process,name):
        return next(r for r in self.result['passes'] if r['process']==process and r['pass_name']==name)

    def test_bank_label_is_class_not_target_index(self):
        bank=load_bank(self.bank,self.bank_sha)
        self.assertEqual(bank['labels'],LABELS); self.assertEqual(bank['kinds'],KINDS); self.assertEqual(bank['rows'],4)

    def test_accuracy_nll_and_scene_split(self):
        c=self.row('A','original')['conditions']
        self.assertEqual(c['correct']['n'],4); self.assertAlmostEqual(c['correct']['accuracy'],0.75)
        self.assertEqual(c['correct']['by_scene_kind'],{'clean':dict(n=2,accuracy=0.5,correct_count=1),
                                                       'mixed':dict(n=2,accuracy=1.0,correct_count=2)})
        self.assertAlmostEqual(c['shuffled']['accuracy'],0.5); self.assertAlmostEqual(c['silent']['accuracy'],0.)
        self.assertAlmostEqual(c['distractor']['accuracy'],0.5)
        with np.load(self.state/'A'/'00_original.npz') as z:
            labels=np.array([LABELS[int(t)] for t in z['correct_ids']])
            expected=recomputed_nll(z['correct_logits'],labels)
            self.assertAlmostEqual(c['correct']['nll_saved_mean'],float(z['correct_nll'].mean()),places=6)
            self.assertAlmostEqual(c['correct']['nll_recomputed_float64_mean'],float(expected.mean()),places=9)
            self.assertAlmostEqual(c['correct']['logit_abs_max'],float(np.abs(z['correct_logits']).max()),places=9)
        self.assertLess(c['correct']['nll_max_abs_err'],1e-4); self.assertTrue(c['correct']['nll_within_e0_tolerance'])
        self.assertTrue(all(c[k]['finite'] for k in CONDITIONS))
        self.assertEqual(self.result['sample'],dict(correct_trials=4,control_trials=dict(shuffled=2,silent=2,distractor=2),
                         clean_trials=2,mixed_trials=2,clean_trial_ids=[2,3],total_predictions=7*10))

    def test_control_pairing_and_cue_independence(self):
        a0=self.row('A','alpha_0')['control_pairing']
        self.assertEqual(a0,dict(n=2,correct_accuracy_on_control=0.,shuffled_accuracy=0.,
                                 correct_minus_shuffled_accuracy=0.,rows_correct_equals_shuffled_bitwise=2))
        orig=self.row('A','original')['control_pairing']
        self.assertAlmostEqual(orig['correct_minus_shuffled_accuracy'],0.5); self.assertEqual(orig['rows_correct_equals_shuffled_bitwise'],0)
        pair=next(p for p in self.result['pass_pairs_process_a'] if (p['left'],p['right'])==('original','alpha_1'))
        self.assertTrue(pair['bitwise_equal']); self.assertEqual(pair['argmax_agreement'],1.); self.assertEqual(pair['max_abs_logit_diff'],0.)
        # Predefined pairs whose members are absent from the fixture are skipped, not invented.
        self.assertEqual([(p['left'],p['right']) for p in self.result['pass_pairs_process_a']],[('original','alpha_1')])

    def test_bitwise_a_vs_b_and_a_only(self):
        ab=self.result['a_vs_b']
        self.assertEqual([r['pass_name'] for r in ab['shared_passes']],['original','alpha_1','alpha_0'])
        self.assertTrue(ab['all_shared_bitwise_equal']); self.assertEqual(ab['a_only'],['alpha_05_observed']); self.assertEqual(ab['b_only'],[])
        self.assertIsNone(self.row('A','alpha_05_observed')['a_equals_b']); self.assertTrue(self.row('B','alpha_0')['a_equals_b'])
        state,bank,bank_sha=build(Path(self.tmp.name)/'flip',b_flip=True)
        flipped=readout(state,bank,bank_sha)['a_vs_b']
        self.assertEqual({r['pass_name']:r['bitwise_equal'] for r in flipped['shared_passes']},
                         {'original':True,'alpha_1':True,'alpha_0':False})
        self.assertFalse(flipped['all_shared_bitwise_equal'])

    def test_most_frequent_class_reports_ties(self):
        # A unique mode is named; tied modes are listed and the single-class field is None, never one arbitrary member.
        for r in self.result['passes']:
            for c in CONDITIONS:
                v=r['conditions'][c]
                self.assertEqual(len(v['most_frequent_predicted_classes'])>=1,True)
                self.assertTrue(all(isinstance(x,int) for x in v['most_frequent_predicted_classes']))
                if len(v['most_frequent_predicted_classes'])==1:
                    self.assertEqual(v['most_frequent_predicted_class'],v['most_frequent_predicted_classes'][0])
                else:
                    self.assertIsNone(v['most_frequent_predicted_class'])
        with np.load(self.state/'A'/'00_original.npz') as z:
            values,counts=np.unique(z['correct_logits'].argmax(1),return_counts=True)
        v=self.row('A','original')['conditions']['correct']
        self.assertEqual(v['most_frequent_predicted_count'],int(counts.max()))
        self.assertEqual(v['most_frequent_predicted_classes'],sorted(int(x) for x in values[counts==counts.max()]))

    def test_bank_sha_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,'BANK_SHA'): readout(self.state,self.bank,'0'*64)

    def test_worker_sha_mismatch_rejected(self):
        state,bank,bank_sha=build(Path(self.tmp.name)/'manifest',break_manifest=True)
        with self.assertRaisesRegex(ValueError,'PASS_SHA:A/00_original.npz'): readout(state,bank,bank_sha)

    def test_nll_mismatch_flagged_not_hidden(self):
        state,bank,bank_sha=build(Path(self.tmp.name)/'shift',nll_shift=1.)
        c=readout(state,bank,bank_sha)['passes'][0]['conditions']['correct']
        self.assertFalse(c['nll_within_e0_tolerance']); self.assertAlmostEqual(c['nll_max_abs_err'],1.,places=4)

    def test_outputs_written_once(self):
        out=Path(self.tmp.name)/'out'
        summary=run(self.state,self.bank,out,self.bank_sha)
        self.assertEqual(set(summary['written']),{'E0_READOUT.json','e0_readout_table.csv'})
        data=json.loads((out/'E0_READOUT.json').read_text())
        module=Path(__file__).resolve().parent/'e0_readout_746603.py'
        self.assertEqual(data['script']['sha256'],sha(module)); self.assertEqual(data['inputs']['bank']['sha256'],self.bank_sha)
        self.assertEqual(data['acceptance']['status'],'E0_ENDPOINT_PASS'); self.assertIs(data['acceptance']['scientific_alpha_result'],False)
        self.assertEqual(data['inputs']['bank']['rows'],4); self.assertIn('E0_COMPLETE.json',data['inputs']['state'])
        lines=(out/'e0_readout_table.csv').read_text().splitlines()
        self.assertEqual(len(lines),1+7); self.assertTrue(lines[0].startswith('process,pass_name,file,sha256,'))
        with self.assertRaises(FileExistsError): run(self.state,self.bank,out,self.bank_sha)

if __name__=='__main__': unittest.main()
