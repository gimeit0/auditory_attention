import io
import unittest
import numpy as np
import soundfile as sf
from check_e1_clean_audio import decode,crop_check,anchor_check

class AudioTests(unittest.TestCase):
    def test_valid_decode(self):
        b=io.BytesIO(); sf.write(b,np.ones(8000)*.1,8000,format='WAV')
        self.assertEqual(decode(b.getvalue())['frames'],8000)
    def test_silence(self):
        b=io.BytesIO(); sf.write(b,np.zeros(8000),8000,format='WAV')
        with self.assertRaisesRegex(ValueError,'SILENT'): decode(b.getvalue())
    def test_corrupt(self):
        with self.assertRaises(Exception): decode(b'not audio')
    def test_crop(self):
        self.assertEqual(crop_check(1.25,2.5)['start_sample_44100'],0)
        for center,duration in ((1.,3.),(2.,3.),(float('nan'),3.)):
            with self.assertRaises(ValueError): crop_check(center,duration)
    def test_anchor_mismatch(self):
        row={'target_index':'0','target_path':'wrong'}
        with self.assertRaisesRegex(ValueError,'ANCHOR_path'): anchor_check(row,'target',[{'path':'right'}])
    def test_anchor_out_of_bounds(self):
        with self.assertRaisesRegex(ValueError,'ANCHOR_INDEX'): anchor_check({'target_index':'-1'},'target',[])

if __name__=='__main__': unittest.main()
