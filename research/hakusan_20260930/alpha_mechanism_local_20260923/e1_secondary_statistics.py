"""Descriptive statistics under contracts 28+29; does not declare completion."""
import numpy as np
from e1_cluster_statistics import bootstrap, OVERLAP
from analyze_e1_primary import align

ALPHAS=('alpha_0','alpha_05','alpha_075','alpha_875','alpha_1')
NEGATIVES=('uniform_05','conv_only_05','fc_mean_preserved_05')

def summarize(logits,nll,labels):
    x=np.asarray(logits,dtype=np.float64)
    nll=np.asarray(nll,dtype=np.float64); labels=np.asarray(labels)
    if x.ndim!=2 or not len(x) or nll.shape!=(len(x),) or labels.shape!=(len(x),):
        raise ValueError('SUMMARY_SHAPE')
    if not np.isfinite(x).all() or not np.isfinite(nll).all(): raise ValueError('NONFINITE')
    if not np.issubdtype(labels.dtype,np.integer) or (labels<0).any() or (labels>=x.shape[1]).any():
        raise ValueError('LABEL_RANGE')
    pred=x.argmax(1); classes,counts=np.unique(pred,return_counts=True)
    maximum=x.max(1)
    recomputed=maximum+np.log(np.exp(x-maximum[:,None]).sum(1))-x[np.arange(len(x)),labels]
    rms=np.sqrt(np.mean(x*x,axis=1))
    return dict(n=len(x),accuracy=float(np.mean(pred==labels)),mean_nll=float(nll.mean()),
        logit_max_abs=float(np.abs(x).max()),predicted_classes=len(classes),
        most_frequent_classes=classes[counts==counts.max()].tolist(),most_frequent_count=int(counts.max()),
        nll_float64_recompute_max_abs=float(np.abs(recomputed-nll).max()),
        sample_logit_rms_mean=float(rms.mean()),sample_logit_rms_max=float(rms.max()))

def collapse(row,original):
    # Strict inequalities from contract; no ratios/division-by-zero shortcuts.
    low=row['accuracy'] < .5*original['accuracy']
    high=row['logit_max_abs'] > 10*original['logit_max_abs']
    return dict(collapse=bool(low or high),accuracy_below_half_original=bool(low),
                logit_above_ten_times_original=bool(high))

def get(arrays,domain,p,condition,ids,bank):
    a=arrays[domain,p,condition]
    logits=align(a['trial_ids'],ids,a['logits'])
    nll=align(a['trial_ids'],ids,a['nll'].astype(np.float64))
    labels=np.array([int(bank[i]['target_label']) for i in ids])
    return (logits.argmax(1)==labels).astype(np.float64),nll,logits

def unit(ids,columns,bank):
    r=bootstrap([bank[i]['target_speaker'] for i in ids],columns)
    r['trial_ids']=ids
    r['e0_overlap_trial_ids']=[i for i in ids if i in OVERLAP]
    r['inference']='DESCRIPTIVE_NO_CONFIRMATORY_CLAIM'
    return r

def control_columns(arrays,ids,bank):
    columns={}; effects={}; correct={}
    for p in (*ALPHAS,*NEGATIVES):
        correct[p]=get(arrays,'main',p,'correct',ids,bank)
        c,nc,_=correct[p]
        for cond in ('correct','shuffled','silent','distractor'):
            a,n,_=get(arrays,'main',p,cond,ids,bank)
            columns[p+'/'+cond+'/accuracy_pp']=100*a
            columns[p+'/'+cond+'/nll']=n
            if cond!='correct':
                effects[p,cond]=c-a
                columns[p+'/correct_minus_'+cond+'/accuracy_pp']=100*(c-a)
                columns[p+'/correct_minus_'+cond+'/nll']=nc-n
    for p in ALPHAS:
        columns[p+'/D_pp']=100*(effects[p,'shuffled']-effects['alpha_0','shuffled'])
    columns['D_pp']=columns['alpha_1/D_pp']
    columns['c1_pp']=100*effects['alpha_1','shuffled']
    columns['r0_pp']=100*effects['alpha_0','shuffled']
    for p in NEGATIVES:
        columns['negative/'+p+'/C_alpha05_minus_C_p_pp']=100*(effects['alpha_05','shuffled']-effects[p,'shuffled'])
    return columns

def analyze(arrays,bank):
    main=list(map(int,arrays['main','original','correct']['trial_ids']))
    control=list(map(int,arrays['main','original','shuffled']['trial_ids']))
    clean=list(map(int,arrays['clean','original','correct_cue']['trial_ids']))
    if (len(main),len(control),len(clean))!=(2000,400,200): raise ValueError('UNIT_SIZES')
    summaries={}
    for (domain,p,cond),a in arrays.items():
        ids=list(map(int,a['trial_ids']))
        labels=np.array([int(bank[i]['target_label']) for i in ids])
        summaries['/'.join((domain,p,cond))]=summarize(a['logits'],a['nll'],labels)
    partitions={}
    for domain,correct in [('main','correct'),('clean','correct_cue')]:
        original=summaries[f'{domain}/original/{correct}']
        for d,p,c in arrays:
            if d==domain and c==correct:
                partitions[f'{domain}/{p}']=collapse(summaries[f'{domain}/{p}/{correct}'],original)
    units={}
    columns=control_columns(arrays,control,bank)
    units['control_full']=unit(control,columns,bank)
    mask=np.array([i not in OVERLAP for i in control])
    units['control_excluding_e0_overlap']=unit(np.array(control)[mask].tolist(),{k:v[mask] for k,v in columns.items()},bank)
    clean_columns={}
    for p in ALPHAS:
        ca,cn,_=get(arrays,'clean',p,'correct_cue',clean,bank)
        za,zn,_=get(arrays,'clean',p,'zero_cue',clean,bank)
        for cond,a,n in [('correct_cue',ca,cn),('zero_cue',za,zn)]:
            clean_columns[p+'/'+cond+'/accuracy_pp']=100*a
            clean_columns[p+'/'+cond+'/nll']=n
        clean_columns[p+'/correct_minus_zero/accuracy_pp']=100*(ca-za)
        clean_columns[p+'/correct_minus_zero/nll']=cn-zn
    units['clean_full']=unit(clean,clean_columns,bank)
    mask=np.array([i not in OVERLAP for i in clean])
    units['clean_excluding_e0_overlap']=unit(np.array(clean)[mask].tolist(),{k:v[mask] for k,v in clean_columns.items()},bank)
    main_columns={}
    for p in (*ALPHAS,*NEGATIVES):
        a,n,_=get(arrays,'main',p,'correct',main,bank)
        main_columns[p+'/accuracy_pp']=100*a
        main_columns[p+'/nll']=n
    units['main_correct_all']=unit(main,main_columns,bank)
    for kind in ('clean','mixed'):
        mask=np.array([bank[i]['scene_kind']==kind for i in main])
        units['main_correct_'+kind]=unit(np.array(main)[mask].tolist(),{k:v[mask] for k,v in main_columns.items()},bank)
    strata={}
    for snr in range(5):
        for count in range(1,5):
            name=f'snr{snr}_distractors{count}'
            select=lambda ids: np.array([int(bank[i]['snr_bin'])==snr and int(bank[i]['distractor_count'])==count for i in ids])
            cm=select(control); mm=select(main)
            if cm.sum()!=20: raise ValueError('CONTROL_STRATUM_QUOTA')
            strata[name]=dict(control=unit(np.array(control)[cm].tolist(),{k:v[cm] for k,v in columns.items()},bank),
                              main_correct=unit(np.array(main)[mm].tolist(),{k:v[mm] for k,v in main_columns.items()},bank))
    agreement={}
    _,_,base=get(arrays,'main','alpha_05','correct',main,bank)
    for p in NEGATIVES:
        _,_,other=get(arrays,'main',p,'correct',main,bank)
        agreement[p]=dict(top1_agreement=float(np.mean(base.argmax(1)==other.argmax(1))),
                          max_abs_logit_difference=float(np.abs(base.astype(np.float64)-other.astype(np.float64)).max()))
    return dict(status='E1_SECONDARY_STATISTICS_PARTIAL_NOT_DEV_COMPLETE',scientific_labels=[],
                summaries=summaries,collapse=partitions,units=units,strata=strata,negative_agreement=agreement,
                q3_status='Q3_NOT_INTERPRETABLE_COLLAPSE' if partitions['main/alpha_05']['collapse'] else 'Q3_REQUIRES_FINAL_RULES',
                remaining=['error_structure','full_P1_P9_report','complete_independent_recomputation','conclusion_gate'])
