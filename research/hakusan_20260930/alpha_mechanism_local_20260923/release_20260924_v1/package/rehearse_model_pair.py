"""Two fresh CPU model workers. Synthetic inputs/weights only, no remote work."""
import json
import os
from pathlib import Path
import sys
import tempfile
import numpy as np
from e0_archive_harness import identity,write_json,layout,schedule
from e0_layout_reference import CONDITIONS,condition_ids,validate_logits,require
from two_process_supervisor import run_pair

HERE=Path(__file__).resolve().parent
SCOPE='TWO_PROCESS_RANDOM_SMALL_MODEL_ONLY'

def worker(label,directory):
    from test_gain_observer_and_stages import fixture,provider
    from model_stage_driver import execute_stages
    spec=layout()
    f=fixture()
    rows=[]
    def sink(process,name,payload,events):
        filename=f'{len(rows):02d}_{name}.npz'
        arrays={}
        for c in CONDITIONS:
            arrays[c+'_ids']=np.array(payload[c]['trial_ids'],dtype=np.int64)
            arrays[c+'_logits']=payload[c]['logits']
            arrays[c+'_nll']=payload[c]['nll']
        with (directory/filename).open('xb') as out: np.savez(out,**arrays)
        rows.append(dict(name=name,file=filename,**identity(directory/filename)))
        if events: write_json(directory/'OBSERVER.json',events)
    summary=execute_stages(f.core,f.base,f.outer,f.arch,f.gain,spec,label,provider(spec),f.device,sink,
                           deadline_seconds=60)
    write_json(directory/'STAGES.json',summary)
    write_json(directory/'WORKER.json',dict(scope=SCOPE,label=label,pid=os.getpid(),passes=rows,
               stages=identity(directory/'STAGES.json'),observer=identity(directory/'OBSERVER.json') if label=='A' else None))

def verify(root,records,*,scope=SCOPE,extra_files=()):
    spec=layout()
    outputs={}
    total=0
    manifest_hashes={}
    for record in records:
        label=record['label']
        d=root/label
        require(all(p.is_file() and not p.is_symlink() for p in d.iterdir()),'PAIR_FILE_TYPE')
        require(sum(p.stat().st_size for p in d.iterdir())<64*1024**2,'PAIR_ARCHIVE_SIZE')
        manifest=json.loads((d/'WORKER.json').read_text())
        require(manifest['scope']==scope and manifest['label']==label and manifest['pid']==record['pid'],'WORKER_IDENTITY')
        require(identity(d/'STAGES.json')==manifest['stages'],'STAGE_REPORT_SHA')
        summary=json.loads((d/'STAGES.json').read_text())
        wanted=[n for p,n in schedule(spec) if p==label]
        require([r['name'] for r in manifest['passes']]==wanted,'PAIR_PASSES')
        require(summary['process_label']==label and summary['passes']==len(wanted),'STAGE_IDENTITY')
        formula=summary['gain_formula_reports']
        require(len(formula)==len(wanted),'G5_REPORT_COUNT')
        for name,g in zip(wanted,formula):
            require(g['status']=='G5_FIXED_FEATURE_PASS' and len(g['checks'])==32
                    and g['pass_name']==('alpha_05' if name=='alpha_05_observed' else name)
                    and g['atol']==g['rtol']==2e-6,'G5_REPORT')
        expected_files={'stdout.log','stderr.log','LAUNCH.json','WORKER.json','STAGES.json'}
        expected_files.update(extra_files)
        for i,row in enumerate(manifest['passes']):
            filename=f'{i:02d}_{row["name"]}.npz'
            require(row['file']==filename,'PAIR_FILENAME')
            expected_files.add(filename)
            require(identity(d/filename)=={k:row[k] for k in ('size','sha256')},'PAIR_OUTPUT_SHA')
            with np.load(d/filename,allow_pickle=False) as z:
                require(set(z.files)=={c+s for c in CONDITIONS for s in ('_ids','_logits','_nll')},'PAIR_ARRAY_KEYS')
                for c in CONDITIONS:
                    ids=condition_ids(spec,c)
                    require(z[c+'_ids'].dtype==np.int64 and z[c+'_ids'].tolist()==ids,'PAIR_IDS')
                    labels=np.array([spec['target_labels'][str(i)] for i in ids])
                    validate_logits(z[c+'_logits'],ids,labels,z[c+'_nll'])
                    outputs[label,row['name'],c]=(z[c+'_logits'].tobytes(),z[c+'_nll'].tobytes())
                    total+=len(ids)
        if label=='A':
            expected_files.add('OBSERVER.json')
            require(identity(d/'OBSERVER.json')==manifest['observer'],'OBSERVER_SHA')
            events=json.loads((d/'OBSERVER.json').read_text())
            require(len(events)==144 and manifest['observer']['size']<=262144,'OBSERVER_BUDGET')
        require({p.name for p in d.iterdir()}==expected_files,'PAIR_FILE_INVENTORY')
        manifest_hashes[label]=identity(d/'WORKER.json')
    for name in spec['passes']:
        for c in CONDITIONS: require(outputs['A',name,c]==outputs['B',name,c],'PAIR_REPEAT_BITS')
    for label in ('A','B'):
        for c in CONDITIONS:
            for left,right in (('original','alpha_1'),('explicit_bypass','alpha_0')):
                require(outputs[label,left,c]==outputs[label,right,c],'PAIR_ENDPOINT_BITS')
    for c in CONDITIONS: require(outputs['A','alpha_05',c]==outputs['A','alpha_05_observed',c],'PAIR_OBSERVER_BITS')
    require(total==6048,'PAIR_PREDICTIONS')
    return dict(verified=True,scope=scope,predictions=total,worker_manifests=manifest_hashes,
                qualification='array/inventory checks only; caller must verify provenance')

def main():
    parent=Path(tempfile.mkdtemp(prefix='e0-two-model-processes-',dir=HERE))
    root=parent/'attempt'
    result=run_pair(root,lambda label,d:[sys.executable,'-B',str(Path(__file__).resolve()),'worker',label,str(d)],
                    verify,timeout_seconds=60)
    print(json.dumps(dict(root=str(root),status=result['status'],verification=result['verification']),indent=2))

if __name__=='__main__':
    if len(sys.argv)==1: main()
    else:
        require(len(sys.argv)==4 and sys.argv[1]=='worker' and sys.argv[2] in ('A','B'),'WORKER_ARGUMENTS')
        worker(sys.argv[2],Path(sys.argv[3]))
