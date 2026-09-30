"""Export once from verified Job728520; load without the original archive path."""
import hashlib
import json
from pathlib import Path
import numpy as np
from e0_layout_reference import CONDITIONS,canonical,condition_ids,reference,validate_logits,require

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def export_reference(directory,layout):
    refs=reference(layout)  # Revalidates original archive hashes before extraction.
    directory=Path(directory)
    directory.mkdir(mode=0o700,exist_ok=False)
    arrays={}
    for c,r in refs.items():
        arrays[c+'_ids']=np.array(r['trial_ids'],dtype=np.int64)
        arrays[c+'_logits']=r['logits']
        arrays[c+'_nll']=r['nll'].astype(np.float32)
    with (directory/'reference.npz').open('xb') as f: np.savez(f,**arrays)
    manifest=dict(schema_version=1,reference_job_id='728520',model_id='formal40',
                  checkpoint_sha256=layout['checkpoint_sha256'],layout_sha256=hashlib.sha256(canonical(layout)).hexdigest(),
                  original_archive_sha256=layout['reference_sha256'],file='reference.npz',
                  sha256=sha(directory/'reference.npz'),size=(directory/'reference.npz').stat().st_size)
    with (directory/'REFERENCE.json').open('xb') as f: f.write(canonical(manifest))
    digest=sha(directory/'REFERENCE.json')
    load_reference(directory,layout,digest)
    return digest

def load_reference(directory,layout,expected_sha):
    directory=Path(directory)
    require(not directory.is_symlink(),'REFERENCE_DIRECTORY')
    mpath=directory/'REFERENCE.json'
    require(mpath.is_file() and not mpath.is_symlink() and mpath.stat().st_size<16384,'REFERENCE_MANIFEST')
    require(sha(mpath)==expected_sha,'REFERENCE_MANIFEST_SHA')
    m=json.loads(mpath.read_text())
    require(m['reference_job_id']=='728520' and m['model_id']=='formal40'
            and m['checkpoint_sha256']==layout['checkpoint_sha256']
            and m['original_archive_sha256']==layout['reference_sha256']
            and m['layout_sha256']==hashlib.sha256(canonical(layout)).hexdigest(),'REFERENCE_BINDING')
    require(m['file']=='reference.npz','REFERENCE_FILENAME')
    path=directory/m['file']
    require(path.is_file() and not path.is_symlink() and path.stat().st_size==m['size']<2*1024**2,'REFERENCE_SIZE')
    require(sha(path)==m['sha256'],'REFERENCE_DATA_SHA')
    refs={}
    with np.load(path,allow_pickle=False) as z:
        require(set(z.files)=={c+s for c in CONDITIONS for s in ('_ids','_logits','_nll')},'REFERENCE_KEYS')
        for c in CONDITIONS:
            ids=condition_ids(layout,c)
            require(z[c+'_ids'].dtype==np.int64 and z[c+'_ids'].tolist()==ids,'REFERENCE_IDS')
            labels=np.array([layout['target_labels'][str(i)] for i in ids])
            require(z[c+'_nll'].dtype==np.float32,'REFERENCE_NLL_DTYPE')
            validate_logits(z[c+'_logits'],ids,labels,z[c+'_nll'])
            refs[c]=dict(trial_ids=ids,logits=z[c+'_logits'].copy(),nll=z[c+'_nll'].copy())
    return refs
