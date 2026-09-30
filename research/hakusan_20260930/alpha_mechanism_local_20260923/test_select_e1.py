import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from select_e1 import BANK, BANK_SHA, PILOT, PILOT_SHA, checked, select, validate, O

class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=list(csv.DictReader(io.StringIO(checked(BANK,BANK_SHA).decode()),delimiter='\t'))
        cls.pilot=set(json.loads(checked(PILOT,PILOT_SHA))['speakers'])
        cls.result=select(cls.rows,cls.pilot)

    def test_deterministic_and_input_order_independent(self):
        other=select(list(reversed(self.rows)),self.pilot)
        self.assertEqual(self.result['trial_ids'],other['trial_ids'])

    def test_quotas_and_layout(self):
        r=self.result
        self.assertEqual(len(r['capacities']),82)
        self.assertTrue(all(x['available']>=x['required'] for x in r['capacities']))
        self.assertEqual(len(set(r['trial_ids'])),2000)
        self.assertFalse(set(r['trial_ids'])&O)
        self.assertEqual(list(map(len,r['batches'])),[16]*125)
        self.assertEqual(sum(map(len,r['control_batches'])),400)
        self.assertEqual(list(map(len,r['clean_batches'])),[16]*12+[8])
        self.assertFalse(r['inputs_frozen'])

    def test_missing_role_rejected(self):
        r=copy.deepcopy(self.rows[0]); del r['shuffled_cue_speaker']
        with self.assertRaisesRegex(ValueError,'ROLE_SCHEMA'): validate(r)

    def test_duplicate_id_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ID'): select(self.rows+[self.rows[0]],self.pilot)

    def test_infeasible_report(self):
        r=select([x for x in self.rows if x['scene_kind']=='clean'],self.pilot)
        self.assertEqual(r['status'],'SELECTION_INFEASIBLE')
        self.assertNotIn('trial_ids',r)

    def test_pilot_shuffled_role_excluded(self):
        r=select(self.rows,{self.rows[0]['shuffled_cue_speaker']})
        self.assertTrue(any('PILOT_ROLE' in x['reasons'] for x in r['excluded']))

    def test_bad_donor_rejected(self):
        rows=copy.deepcopy(self.rows); rows[0]['shuffled_source_trial_id']='999999'
        with self.assertRaisesRegex(ValueError,'DONOR_MISSING'): select(rows,self.pilot)

    def test_wrong_speaker_rejected(self):
        r=copy.deepcopy(self.rows[9000]); r['correct_cue_speaker']='different'
        with self.assertRaisesRegex(ValueError,'CUE_SPEAKER'): validate(r)

    def test_same_recording_rejected(self):
        r=copy.deepcopy(self.rows[9000]); r['correct_cue_path']=r['target_path']
        with self.assertRaisesRegex(ValueError,'CUE_NOT_INDEPENDENT'): validate(r)

    def test_bad_hash_rejected(self):
        with self.assertRaisesRegex(ValueError,'INPUT_SHA'): checked(PILOT,'0'*64)

    def test_nonfinite_center_rejected(self):
        r=copy.deepcopy(self.rows[9000]); r['correct_cue_anchor_center_s']='nan'
        with self.assertRaisesRegex(ValueError,'ANCHOR'): validate(r)

if __name__=='__main__': unittest.main()
