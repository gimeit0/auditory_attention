"""Bounded local decode + pinned anchor comparison; no inference or remote writes."""
import csv
import gzip
import hashlib
import io
import json
import signal
from pathlib import Path
import sys
import numpy as np
import soundfile as sf
from select_e1 import HERE, checked, require

ANCHOR_SHA='b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65'
CANDIDATE_SHA='be2011fdd6489777521a5f54af8d8f4fc39a73b14c6669b636e674f844bbb69b'

def anchor_check(row,role,anchors):
    i=int(row[role+'_index'])
    require(0<=i<len(anchors),'ANCHOR_INDEX')
    a=anchors[i]
    for key in ('path','speaker','norm','label'):
        require(row[role+'_'+key]==a[key], 'ANCHOR_'+key)
    require(float(row[role+'_anchor_center_s'])==float(a['anchor_center_s']),'ANCHOR_CENTER')
    return a

def decode(data):
    with sf.SoundFile(io.BytesIO(data)) as f:
        rate,frames,channels=f.samplerate,f.frames,f.channels
        require(0<rate<=192000 and 0<channels<=8 and 0<frames<=rate*300,'AUDIO_LIMIT')
        count,energy,peak=0,0.,0.
        for block in f.blocks(blocksize=65536,dtype='float32',always_2d=True):
            require(np.isfinite(block).all(),'NONFINITE_AUDIO')
            count+=len(block)
            require(count<=frames,'DECODE_LENGTH')
            mono=block.astype(np.float64).mean(1)
            energy+=float(np.square(mono).sum())
            peak=max(peak,float(np.abs(mono).max()))
        require(count==frames and peak>0,'EMPTY_OR_SILENT')
    return dict(frames=frames,sample_rate=rate,channels=channels,duration_s=frames/rate,
                mono_rms=(energy/frames)**.5,mono_peak=peak,status='LOCAL_DECODE_PASS')

def crop_check(center,duration):
    center=float(center)
    require(np.isfinite(center),'NONFINITE_CENTER')
    start=round(center*44100)-55125
    end=start+110250
    require(start>=0 and end/44100<=duration,'CROP_DURATION_BOUNDS')
    return dict(start_sample_44100=start,end_sample_44100=end,
                status='DURATION_BOUNDS_PASS_NOT_NATIVE_RESAMPLE_CHECK')

def main():
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('DECODE_300S')))
    signal.alarm(300)
    candidate=json.loads(checked(HERE/'E1_CANDIDATE_2000_20260926.json',CANDIDATE_SHA))
    raw=checked(HERE/'E1_REMOTE_VALIDATION_ANCHORS_20260926.tsv.gz',ANCHOR_SHA)
    anchors=list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode()),delimiter='\t'))
    inventory=json.loads((HERE/'E1_CLEAN_SOURCE_AUDIT_20260926.json').read_text())
    require(inventory['candidate_sha256']==CANDIDATE_SHA,'CANDIDATE_BINDING')
    decoded={}
    for record in inventory['clips']:
        data=checked(Path(record['path']),record['sha256'])
        decoded[Path(record['path']).name]=dict(decode(data),sha256=record['sha256'])
    checks=[]
    for row in candidate['clean_sources']:
        for role in ('target','correct_cue'):
            a=anchor_check(row,role,anchors)
            clip=decoded[a['path']]
            bounds=crop_check(a['anchor_center_s'],clip['duration_s'])
            checks.append(dict(trial_id=int(row['trial_id']),role=role,anchor_index=int(row[role+'_index']),
                               clip=a['path'],anchor_center_s=float(a['anchor_center_s']),**bounds))
    report=dict(status='E1_PINNED_ANCHOR_AND_LOCAL_DECODE_PASS',candidate_sha256=CANDIDATE_SHA,
                anchor_sha256=ANCHOR_SHA,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                clean_trials=200,anchor_role_checks=len(checks),decoded_clips=len(decoded),
                clips=decoded,checks=checks,inputs_frozen=False,jobs_submitted=0,
                limitations=['remote_audio_bytes_not_verified','native_resampling_not_executed',
                             'new_clean_model_input_path_not_accepted'])
    with Path(sys.argv[1]).open('x') as f: json.dump(report,f,sort_keys=True,indent=2)
    signal.alarm(0)
    print(json.dumps({k:report[k] for k in ('status','clean_trials','anchor_role_checks','decoded_clips','inputs_frozen')}))

if __name__=='__main__': main()
