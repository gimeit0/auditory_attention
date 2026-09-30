"""Local source inventory only; does not substitute local anchors for frozen ones."""
import hashlib
import json
from pathlib import Path
import sys
from select_e1 import HERE

EXPECTED_ANCHOR='b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65'
CORPUS=Path('/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/clips')

def main():
    candidate=HERE/'E1_CANDIDATE_2000_20260926.json'
    raw=candidate.read_bytes()
    obj=json.loads(raw)
    anchors=[]
    for version in ('artifacts','artifacts.before_hakusan_491636'):
        p=Path('/Users/gigi/projects/auditory_attention/selftrain')/version/'anchors/validation_anchors.tsv.gz'
        digest=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        anchors.append(dict(path=str(p),sha256=digest,expected_sha256=EXPECTED_ANCHOR,match=digest==EXPECTED_ANCHOR))
    clips=[]
    for name in sorted({r[role+'_path'] for r in obj['clean_sources'] for role in ('target','correct_cue')}):
        p=CORPUS/name
        record=dict(path=str(p),regular_file=p.is_file() and not p.is_symlink())
        if record['regular_file']:
            before=p.stat()
            if not 0<before.st_size<=10*1024**2: raise ValueError('CLIP_SIZE')
            data=p.read_bytes()
            after=p.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino): raise ValueError('CLIP_CHANGED')
            record.update(size=len(data),sha256=hashlib.sha256(data).hexdigest())
        clips.append(record)
    report=dict(status='E1_CLEAN_LOCAL_SOURCE_AUDIT_NOT_FREEZE',candidate_sha256=hashlib.sha256(raw).hexdigest(),
                audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                clean_trials=len(obj['clean_sources']),clips=clips,anchors=anchors,
                unique_clips=len(clips),present=sum(c['regular_file'] for c in clips),
                audio_decoded=False,remote_bytes_verified=False,inputs_frozen=False)
    with Path(sys.argv[1]).open('x') as f: json.dump(report,f,sort_keys=True,indent=2)
    print(json.dumps({k:report[k] for k in ('status','clean_trials','unique_clips','present','inputs_frozen')}))

if __name__=='__main__': main()
