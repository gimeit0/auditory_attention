import copy
import json
import unittest
import torch
from experiment_contract import contract,bind,verify,validate

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(alpha=.5,mode='alpha',source_sha256='1'*64,config_sha256='2'*64,
                     layout_sha256='3'*64,synthetic_state_sha256='4'*64,torch_version=torch.__version__)
        self.c=contract(**self.kw)
        self.ids=[7,2]
        self.x=torch.tensor([[1.,2.,3.],[4.,5.,6.]])
        self.r=bind(self.c,self.ids,self.x)

    def test_json_roundtrip(self):
        self.assertEqual(verify(json.loads(json.dumps(self.r)),json.loads(json.dumps(self.c)),self.ids,self.x),
                         'LOCAL_OUTPUT_BINDING_PASS')

    def test_alpha_mode_source_layout_state_runtime_mismatch(self):
        for key,value in dict(alpha=.25,mode='uniform',source_sha256='5'*64,
                config_sha256='5'*64,layout_sha256='5'*64,synthetic_state_sha256='5'*64,
                torch_version='different').items():
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'MISMATCH'):
                verify(self.r,contract(**dict(self.kw,**{key:value})),self.ids,self.x)

    def test_order_payload_dtype_and_record_tamper(self):
        for ids,x in (([2,7],self.x),(self.ids,self.x+1),(self.ids,self.x.double())):
            with self.assertRaises(ValueError): verify(self.r,self.c,ids,x)
        changed=copy.deepcopy(self.r)
        changed['logits']['sha256']='0'*64
        with self.assertRaises(ValueError): verify(changed,self.c,self.ids,self.x)

    def test_invalid_trials_and_outputs(self):
        for ids in ([],[7,7],[True,2],[-1,2],(7,2)):
            with self.assertRaises(ValueError): bind(self.c,ids,self.x)
        for x in (self.x[:1],self.x[:,0],self.x.long(),self.x*float('nan')):
            with self.assertRaises(ValueError): bind(self.c,self.ids,x)

    def test_production_or_unknown_fields_rejected(self):
        for key,value in (('scope','PRODUCTION'),('production_authorized',True),
                          ('production_authorized',0),('schema_version',True),('extra',1)):
            with self.assertRaises(ValueError): validate(dict(self.c,**{key:value}))
        for value in (True,float('nan'),2):
            with self.assertRaises((ValueError,TypeError)): contract(**dict(self.kw,alpha=value))
        with self.assertRaises(ValueError): contract(**dict(self.kw,source_sha256='bad'))
