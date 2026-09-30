"""Evidence-bound E1 delivery, with a fail-closed contract completion gate."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from analyze_e1_primary import BASE,RELEASE,PACKAGE,COLLECTED,DIGEST,identity

INPUTS={
 'primary':'primary-analysis-750474-f4ao34wq/REPORT.json',
 'secondary':'secondary-analysis-750474-mo1tlyrm/REPORT.json',
 'errors':'error-analysis-750474-0tkyayan/REPORT.json',
 'numeric_audit':'independent-stat-audit-750474-epr_1shm/RESULT.json',
 'error_audit':'independent-error-audit-750474-66dqor7h/RESULT.json'}
REQUIRED={'execution','primary','secondary','errors','independent_arithmetic','P1','P2','P3','P4','P5','P6','P7','P8','P9'}

def completion_gate(matrix):
    if set(matrix)!=REQUIRED: raise ValueError('COVERAGE_MATRIX_KEYS')
    failures=[k for k,v in matrix.items() if v['status']!='PASS']
    return dict(status='E1_CONTRACT_COMPLETE' if not failures else 'E1_ANALYSIS_DELIVERED_CONTRACT_INCOMPLETE',
                E1_DEV_COMPLETE=not failures,unclosed_requirements=failures,
                scientific_labels=[],scientific_labels_evaluated=False)

def interval(m):
    return f"{m['estimate']:.2f} [{m['ci95'][0]:.2f}, {m['ci95'][1]:.2f}]" if m['ci95'] else f"{m['estimate']:.2f} [CI unavailable]"

def main():
    out=Path(tempfile.mkdtemp(prefix='delivery-750474-',dir=RELEASE)); print('OUTPUT='+str(out),flush=True)
    data={}; sources={}
    for name,rel in INPUTS.items():
        p=RELEASE/rel; sources[str(p)]=identity(p); data[name]=json.loads(p.read_bytes())
        for file,want in data[name].get('sources',{}).items():
            if identity(Path(file))!=want: raise ValueError('STALE_EVIDENCE: '+file)
    if data['numeric_audit']['status']!='INDEPENDENT_PRIMARY_SECONDARY_ARITHMETIC_PASS' or data['error_audit']['status']!='INDEPENDENT_ERROR_STRUCTURE_PASS':
        raise ValueError('INDEPENDENT_AUDIT')
    for audit,keys in [('numeric_audit',('primary','secondary')),('error_audit',('errors',))]:
        for key in keys:
            path=str(RELEASE/INPUTS[key])
            if data[audit]['sources'][path]!=sources[path]: raise ValueError('AUDIT_REPORT_BINDING')
    signoff_path=BASE.parent/'docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json'
    signoff=json.loads(signoff_path.read_bytes()); sources[str(signoff_path)]=identity(signoff_path)
    if signoff['release_sha256']!=DIGEST or signoff['delta_percentage_points']!=2: raise ValueError('SIGNOFF')
    for r in signoff['contracts']:
        p=BASE/r['file']; sources[str(p)]=identity(p)
        if sources[str(p)]!={k:r[k] for k in ('size','sha256')}: raise ValueError('CONTRACT_HASH')
    with (out/'offline-check.json').open('xb') as stdout,(out/'offline-check.stderr').open('xb') as stderr:
        subprocess.run([sys.executable,'-I','-B',str(PACKAGE/'e1_entry.py'),'offline-check',DIGEST,
                        str(COLLECTED/'state/attempt'),'750474'],stdout=stdout,stderr=stderr,check=True,timeout=180)
    with (out/'tests.stdout').open('xb') as stdout,(out/'tests.stderr').open('xb') as stderr:
        subprocess.run([sys.executable,'-B','-m','unittest','test_e1_cluster_statistics','test_e1_secondary_statistics',
                        'test_e1_error_structure','test_e1_independent_audit','test_e1_delivery'],cwd=BASE,
                       stdout=stdout,stderr=stderr,check=True,timeout=180)
    matrix={k:dict(status='PASS',basis='') for k in REQUIRED}
    matrix['execution']['basis']='Frozen package offline-check; 38400 predictions; endpoints and A/B cold repeat.'
    matrix['primary']['basis']='400 control, observed r0, D and sensitivity386; report primary.'
    matrix['secondary']['basis']='Absolute accuracy/NLL, strata, collapse, clean195/200, negative controls; report secondary.'
    matrix['errors']['basis']='All38400 rows, collision/raw flags, clean/mixed, CI; report errors.'
    matrix['independent_arithmetic']['basis']='Independent raw-array recomputation, bound to exact current report hashes.'
    resources={}
    for proc in ('A','B'):
        folder=COLLECTED/'state/attempt'/proc
        w=json.loads((folder/'WORKER.json').read_bytes()); s=json.loads((folder/'STAGES.json').read_bytes())
        rows=s['pass_resources']
        resources[proc]=dict(environment=w['environment'],runtime=s['runtime_values'],
            execution_window_start_utc=s['process_started_utc'],execution_window_finish_utc=s['process_finished_utc'],
            full_process_utc_start=None,full_process_utc_finish=None,pass_resources=rows,
            allocated_peak_bytes=max(r['cuda_max_memory_allocated_bytes'] for r in rows),
            reserved_peak_bytes=max(r['cuda_max_memory_reserved_bytes'] for r in rows),
            rss_peak_KiB=max(r['host_max_rss_ru_maxrss'] for r in rows))
        for p in (folder/'WORKER.json',folder/'STAGES.json'): sources[str(p)]=identity(p)
    for k in ('P1','P2','P3','P4'): matrix[k]['basis']='A/B worker and stage actual records, production offline-check plus RESOURCE_SUMMARY.json.'
    matrix['P5']=dict(status='PARTIAL_EXECUTION_WINDOW_ONLY',basis='UTC fields start inside execute_loaded, after model loading. Full child-process UTC creation/exit missing; not reconstructed from mtime.')
    collection=json.loads((COLLECTED/'COLLECTION_MANIFEST.json').read_bytes())
    scheduling=RELEASE/'release-750474/remote.jsonl'
    lines=[json.loads(l) for l in scheduling.read_text().splitlines() if l.strip()]
    if not any('ReqTRES=cpu=8,mem=64G' in r.get('stdout','') and 'nvidia_a100' in r.get('stdout','') for r in lines): raise ValueError('SCONTROL')
    if '750474|COMPLETED|0:0|' not in collection['sacct']: raise ValueError('SACCT')
    sources[str(scheduling)]=identity(scheduling); sources[str(COLLECTED/'COLLECTION_MANIFEST.json')]=identity(COLLECTED/'COLLECTION_MANIFEST.json')
    matrix['P6']['basis']='Terminal sacct plus historical pre/post-release scontrol (not terminal scontrol).'
    release=json.loads((PACKAGE/'RELEASE.json').read_bytes())
    matrix['P7']['basis']='Frozen execution.pass_map / alpha_grid validated by offline-check; included in RESOURCE_SUMMARY.'
    matrix['P8']['basis']='Frozen execution.pilot_exposure: E0 746603,19 trial IDs,5 clean; docs26/27 hashes bound.'
    matrix['P9']['basis']='External user SIGNOFF binds contracts28+29 and delta2 to this release; frozen earlier PENDING retained; advisor NOT_RECORDED.'
    gate=completion_gate(matrix)
    summary=dict(job_id='750474',release_sha256=DIGEST,scope='PILOT_DRIVEN_REUSED_VALIDATION_BANK_EXPLORATORY_DEVELOPMENT',
                 gate=gate,matrix=matrix,code=identity(Path(__file__)),sources=sources,
                 analysis_reports=INPUTS,new_gpu_jobs=0,automatic_retry=False)
    (out/'RESOURCE_SUMMARY.json').write_text(json.dumps(dict(workers=resources,sacct=collection['sacct'],
             pass_map=release['execution']['pass_map'],pilot_exposure=release['execution']['pilot_exposure'],
             external_signoff=signoff),indent=2)+'\n')
    # Tabular complete results, not only selected significant rows.
    rows=[]
    for name,report in data.items():
        if name not in ('primary','secondary'): continue
        units=dict(report['units'])
        for key,group in report.get('strata',{}).items():
            units.update({key+'/'+k:v for k,v in group.items()})
        for unit,value in units.items():
            for metric,v in value['metrics'].items():
                ci=v['ci95'] or [None,None]
                rows.append(dict(report=name,unit=unit,metric=metric,n=value['info']['trials'],
                                 clusters=value['info']['clusters'],estimate=v['estimate'],ci_low=ci[0],ci_high=ci[1]))
    with (out/'ALL_METRICS.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for name,report in data.items(): (out/(name+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    p=data['primary']; s=data['secondary']; residual=p['residual']
    text=['# E1 750474 统一交付报告','',
      '**数值分析及独立复算已完成；合同全项验收未完成（P5）。** 不标 E1_DEV_COMPLETE，不赋科学候选/机制标签。',
      '', '## 身份与试点动机','',
      '这是单 formal40、复用验证 bank、试点驱动的探索性 α 扫描，不是独立测试，也不是再次进行作者 checkpoint 总体比较。',
      'E0 作业746603 的96条试点显示低 α 崩溃，因而在E1运行前用 .875 替换 .25；保留公式 gα=1−α(1−g)、19条暴露样本及排除它们的敏感性分析。依据：26号科学读数、27号决策稿、28+29号合同；参见来源清单及 RESOURCE_SUMMARY 的 pilot_exposure。',
      '', '## 主对比','', '| 单位 | D（百分点，95%CI） |','| --- | --- |']
    for k in p['units']: text.append(f"| {k} | {interval(p['units'][k]['metrics']['D_pp'])} |")
    text+=['','D=c1−r0，按trial对齐，不强制r0为零。此次α=0正确指示残差全零且预测类别不一致数为0；不能推广成批形状不影响浮点输出。',
           f"α=0 NLL correct−shuffled：mean={residual['nll_mean']:.9f}，std(ddof=0)={residual['nll_std_ddof0']:.9f}，max_abs={residual['nll_max_abs']:.9f}。",'',
           '## 预定剂量扫描（main correct，2000条）','', '| α | 准确率 %（95%CI） | NLL均值 | 崩溃区 |','| --- | --- | ---: | --- |']
    for key,alpha in [('alpha_0','0'),('alpha_05','.5'),('alpha_075','.75'),('alpha_875','.875'),('alpha_1','1')]:
        a=s['units']['main_correct_all']['metrics'][key+'/accuracy_pp']; v=s['summaries']['main/'+key+'/correct']
        text.append(f"| {alpha} | {interval(a)} | {v['mean_nll']:.4f} | {s['collapse']['main/'+key]['collapse']} |")
    text+=['','准确率低于original一半或最大绝对logit超过其十倍即为崩溃区，阈值未事后修改。这里只列采样点，不挑最优α，不外推点间形状。绝对NLL用表格呈现，没有误用线性跨量级图。','',
      '## clean 与负对照','',
      '新clean正确cue与零cue分开；main clean的correct名称实际仍为零cue。',
      'α=1新clean correct_cue−zero_cue准确率差（百分点）：'+interval(s['units']['clean_full']['metrics']['alpha_1/correct_minus_zero/accuracy_pp'])+'。不能据此声称提升、损害或±2pp等效。',
      'Q3_NOT_INTERPRETABLE_COLLAPSE：α=.5本身崩溃，三个同α负对照只作描述，不据此归因层或幅度、不称已排除lapse。完整CI、负对照一致率与最大logit差见secondary.json和ALL_METRICS.csv。',
      '', '## 完整统计与核验','',
      '全部绝对准确率/NLL、20格SNR×干扰数、clean/mixed、排除重叠敏感性、错误类型/标签碰撞分列均交付为JSON与CSV；B冷重复不当新增样本。',
      'bootstrap固定seed20260926、PCG64、10000次、target_speaker簇配对、trial加权、linear percentile 95%CI；同单位各统计共享抽样。簇数少于2不给CI。依赖限制：未吸收cue/distractor/shuffled donor共享带来的全部关联。所有次要比较均为描述性，未作多重校正，不据此作确认性主张。',
      '独立复算：49单位、3170指标、54摘要、17崩溃规则与3负对照摘要；错误结构38400条、131汇总、655区间。浮点容差1e−10，不夸称逐位一致。',
      '', '## 来源限制与下一决策','',
      'A100作业750474 COMPLETED/0:0，用时57:59。P1–P4、P6–P9证据见RESOURCE_SUMMARY与COVERAGE；P9后续用户签署由外部记录覆盖显示，冻结历史PENDING文字未改。',
      '**P5未关闭**：记录的UTC起止覆盖模型加载后的执行窗口，不是完整子进程生命周期。原归档无法补出缺失时间，不能根据mtime伪造，也不自动重跑GPU。',
      '下一步需对这项可追溯性偏差作明确处置：如接受带限制交付，应另立偏差决定并保留原合同和原始证据；否则未来重跑须先修正记录器并另行批准GPU预算。当前报告不代替该决定。',
      '本次没有新增GPU、改网格或放宽门槛。原checkpoint比较结果不因本E1来源限制而被自动撤销；这也是两个不同阶段。','']
    (out/'REPORT.md').write_text('\n'.join(text))
    if any(identity(Path(p))!=v for p,v in sources.items()): raise ValueError('SOURCE_CHANGED')
    (out/'COVERAGE.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    manifest={p.name:identity(p) for p in out.iterdir() if p.is_file()}
    (out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(gate,ensure_ascii=False))

if __name__=='__main__': main()
