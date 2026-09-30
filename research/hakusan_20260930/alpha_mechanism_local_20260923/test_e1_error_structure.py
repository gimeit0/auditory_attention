import unittest
import numpy as np
from e1_error_structure import classify,analyze_errors

class ErrorTests(unittest.TestCase):
    def row(self,**kw):
        r=dict(target_label='3',distractor_count='1',distractor_1_label='4',scene_kind='mixed',
               correct_cue_label='5',shuffled_cue_label='6',probe_distractor_cue_label='7')
        r.update(kw); return r

    def test_target_priority_over_cue(self):
        r=classify(self.row(correct_cue_label='3'),3,'main','correct')
        self.assertEqual(r['category'],'target'); self.assertTrue(r['cue_label_hit'])

    def test_collision_separate_even_if_prediction_other(self):
        for pred in (3,9):
            r=classify(self.row(distractor_1_label='3'),pred,'main','correct')
            self.assertEqual(r['category'],'label_collision')

    def test_distractor_cue_overlap_preserved(self):
        r=classify(self.row(shuffled_cue_label='4'),4,'main','shuffled')
        self.assertEqual(r['category'],'distractor'); self.assertTrue(r['distractor_cue_overlap_hit'])

    def test_actual_cue_condition(self):
        for cond,pred in [('correct',5),('shuffled',6),('distractor',7)]:
            self.assertEqual(classify(self.row(),pred,'main',cond)['category'],'cue_word')
        self.assertEqual(classify(self.row(),5,'main','silent')['category'],'other')

    def test_old_clean_not_correct_cue(self):
        r=self.row(distractor_count='0',scene_kind='clean')
        self.assertEqual(classify(r,5,'main','correct')['category'],'other')
        self.assertEqual(classify(r,5,'clean','correct_cue')['category'],'cue_word')
        self.assertEqual(classify(r,5,'clean','zero_cue')['category'],'other')

    def test_invalid_domain_or_label_rejected(self):
        with self.assertRaises(ValueError): classify(self.row(),800,'main','correct')
        with self.assertRaises(ValueError): classify(self.row(),1,'clean','correct_cue')
        with self.assertRaises(ValueError): classify(self.row(),1,'other','correct')

    def test_scene_partition_retains_totals(self):
        bank={1:self.row(target_speaker='s1'),2:self.row(distractor_count='0',scene_kind='clean',target_speaker='s2')}
        a={('main','alpha_1','correct'):dict(trial_ids=np.array([1,2]),logits=np.eye(8)[[3,5]])}
        r=analyze_errors(a,bank)
        self.assertEqual(r['scene_summaries']['main/alpha_1/correct/scene_mixed']['counts']['target'],1)
        self.assertEqual(r['scene_summaries']['main/alpha_1/correct/scene_clean']['counts']['other'],1)
        self.assertEqual(sum(s['trials'] for s in r['scene_summaries'].values()),2)

if __name__=='__main__': unittest.main()
