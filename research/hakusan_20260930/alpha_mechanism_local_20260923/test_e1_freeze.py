import copy
import unittest
from freeze_e1_data import verify_audio,CANDIDATE_SHA

class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.local=dict(candidate_sha256=CANDIDATE_SHA,files=[dict(name='x.mp3',size=3,sha256='a'*64)])
        self.remote=dict(candidate_sha256=CANDIDATE_SHA,status='REMOTE_AUDIO_BYTES_PASS',
                         files=[dict(self.local['files'][0],match=True)])
    def test_pass(self): verify_audio(self.local,self.remote)
    def test_digest(self):
        self.remote['files'][0]['sha256']='b'*64
        with self.assertRaises(ValueError): verify_audio(self.local,self.remote)
    def test_missing(self):
        self.remote['files']=[]
        with self.assertRaises(ValueError): verify_audio(self.local,self.remote)
    def test_false_flag(self):
        self.remote['files'][0]['match']=False
        with self.assertRaises(ValueError): verify_audio(self.local,self.remote)
    def test_binding(self):
        self.remote['candidate_sha256']='bad'
        with self.assertRaises(ValueError): verify_audio(self.local,self.remote)

if __name__=='__main__': unittest.main()
