"""Freeze data identities only, never a runnable GPU/analysis contract."""
import hashlib
import json
from pathlib import Path
import sys
from select_e1 import HERE,BANK,BANK_SHA,PILOT,PILOT_SHA,checked,require
from check_e1_clean_audio import CANDIDATE_SHA,ANCHOR_SHA

def identity(p):
    require(p.is_file() and not p.is_symlink(),'FREEZE_FILE')
    raw=p.read_bytes()
    return dict(path=str(p.resolve()),size=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def verify_audio(local,remote):
    require(local['candidate_sha256']==remote['candidate_sha256']==CANDIDATE_SHA,'CANDIDATE')
    require(remote['status']=='REMOTE_AUDIO_BYTES_PASS','REMOTE_STATUS')
    require(local['files']==[{k:r[k] for k in ('name','size','sha256')} for r in remote['files']],'AUDIO_MISMATCH')
    require(all(r['match'] is True for r in remote['files']),'AUDIO_MATCH_FLAG')

def main():
    audit=HERE/'e1-audio-remote-20260926-v1'
    local=json.loads((audit/'LOCAL_INVENTORY.json').read_text())
    remote=json.loads((audit/'REMOTE_INVENTORY.json').read_text())
    verify_audio(local,remote)
    candidate=json.loads(checked(HERE/'E1_CANDIDATE_2000_20260926.json',CANDIDATE_SHA))
    checked(BANK,BANK_SHA); checked(PILOT,PILOT_SHA)
    checked(HERE/'E1_REMOTE_VALIDATION_ANCHORS_20260926.tsv.gz',ANCHOR_SHA)
    require(identity(HERE/'select_e1.py')['sha256']==candidate['sources']['selector_sha256'],'SELECTOR_CHANGED')
    decode=json.loads((HERE/'E1_CLEAN_DECODE_20260926.json').read_text())
    require(decode['status']=='E1_PINNED_ANCHOR_AND_LOCAL_DECODE_PASS' and decode['candidate_sha256']==CANDIDATE_SHA,'DECODE')
    files=[BANK,PILOT,HERE/'E1_CANDIDATE_2000_20260926.json',HERE/'E1_REMOTE_VALIDATION_ANCHORS_20260926.tsv.gz',
           HERE/'E1_CLEAN_DECODE_20260926.json',HERE/'select_e1.py',HERE/'e1_clean_input.py',
           HERE/'test_e1_clean_input.py',HERE/'check_e1_clean_audio.py',HERE/'test_e1_clean_audio.py',
           HERE/'verify_e1_remote_audio.py',Path(__file__).resolve()]
    files += [audit/n for n in ('LOCAL_INVENTORY.json','REMOTE_INVENTORY.json','REQUEST.json','TRANSPORT.json','VERIFIED.json')]
    manifest=dict(schema_version=1,status='E1_DATA_IDENTITIES_FROZEN_PRODUCTION_NOT_READY',
        scope='data selection, order, anchor and audio bytes; NOT full executable input contract',
        trial_count=2000,clean_trials=200,mixed_trials=1800,control_trials=400,
        candidate_sha256=CANDIDATE_SHA,files=[identity(p) for p in files],audio_files=local['files'],
        remote_audio_root=remote['root'],batch_size=16,batches=candidate['batches'],
        control_batches=candidate['control_batches'],clean_batches=candidate['clean_batches'],
        evaluation_role='REUSED_VALIDATION_BANK_DEVELOPMENT_NOT_INDEPENDENT_TEST',
        production_ready=False,jobs_submitted=0,
        pending=['native real-audio clean input path validation','complete E1 worker and offline verifier',
                 'final prediction count, statistical contract and GPU budget approval'])
    out=Path(sys.argv[1])
    with out.open('x') as f: json.dump(manifest,f,sort_keys=True,indent=2)
    print(json.dumps(dict(status=manifest['status'],manifest_sha256=identity(out)['sha256'],audio_files=len(local['files']))))

if __name__=='__main__': main()
