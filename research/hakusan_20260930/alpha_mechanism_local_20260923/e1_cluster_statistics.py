"""Contract 28+29 paired target-speaker cluster bootstrap, no GPU/network."""
import hashlib
import numpy as np

SEED = 20260926
REPLICATES = 10000
OVERLAP = frozenset((3,11,15,2257,2259,2264,4517,4518,4527,6753,6757,6758,
                     6761,6764,9007,9008,9015,9018,9023))

def bootstrap(speakers, columns):
    """All columns share exactly the same 10000 draws; point means weight trials.

    Sorted speaker IDs match numpy.unique ordering. Each analysis unit calls
    this once, initializing its own PCG64 generator with the contract seed.
    Accuracy columns should be supplied in percentage points; NLL in nats.
    """
    if not speakers or any(type(s) is not str or not s.strip() for s in speakers):
        raise ValueError('MISSING_SPEAKER')
    if not columns or any(not isinstance(k,str) or not k for k in columns):
        raise ValueError('METRIC_NAMES')
    names = list(columns)
    vectors = [np.asarray(columns[k],dtype=np.float64) for k in names]
    if any(v.shape != (len(speakers),) or not np.isfinite(v).all() for v in vectors):
        raise ValueError('METRIC_SHAPE_OR_FINITE')
    values = np.column_stack(vectors)
    unique, index, counts = np.unique(speakers,return_inverse=True,return_counts=True)
    sums = np.zeros((len(unique),len(names)),dtype=np.float64)
    np.add.at(sums,index,values)
    info = dict(trials=len(speakers),clusters=len(unique),
                cluster_size_min=int(counts.min()),cluster_size_median=float(np.median(counts)),
                cluster_size_max=int(counts.max()),numpy_version=np.__version__,seed=SEED,
                replicates=REPLICATES,generator='PCG64',quantile_method='linear',
                weighting='trial_weighted',cluster_order='lexicographic_numpy_unique',
                dependence_limit='target_speaker only; donor/cue/distractor sharing not absorbed')
    metrics = {k:dict(estimate=float(values[:,j].mean()),ci95=None) for j,k in enumerate(names)}
    if len(unique)<2:
        return dict(info=info,metrics=metrics,status='CI_NOT_COMPUTED_FEWER_THAN_TWO_CLUSTERS')
    rng=np.random.default_rng(SEED)
    draws=np.empty((REPLICATES,len(names)))
    checksum=hashlib.sha256()
    for b in range(REPLICATES):
        sampled=rng.integers(0,len(unique),size=len(unique))
        checksum.update(sampled.astype('<i8').tobytes())
        draws[b]=sums[sampled].sum(axis=0)/counts[sampled].sum()
    interval=np.quantile(draws,[.025,.975],axis=0,method='linear')
    for j,k in enumerate(names): metrics[k]['ci95']=interval[:,j].tolist()
    info['shared_draw_indices_sha256']=checksum.hexdigest()
    return dict(info=info,metrics=metrics,status='PAIRED_CLUSTER_BOOTSTRAP_COMPLETE')

def paired_columns(terms):
    """No assumed-zero baseline. Columns all use the same aligned trial order."""
    names=('alpha_0','alpha_05','alpha_075','alpha_875','alpha_1')
    if set(terms)!=set(names): raise ValueError('ALPHA_GRID')
    effects={k:np.asarray(terms[k]['accuracy_difference'],dtype=np.float64) for k in names}
    shape=effects['alpha_0'].shape
    if len(shape)!=1 or shape[0]==0 or any(v.shape!=shape or not np.isin(v,[-1,0,1]).all() for v in effects.values()):
        raise ValueError('PAIRED_INDICATORS')
    columns={'D_pp':100*(effects['alpha_1']-effects['alpha_0']),
             'c1_pp':100*effects['alpha_1'],'r0_pp':100*effects['alpha_0']}
    for k in names:
        nll=np.asarray(terms[k]['nll_difference'],dtype=np.float64)
        if nll.shape!=shape or not np.isfinite(nll).all(): raise ValueError('NLL_DIFFERENCE')
        columns[k+'/D_pp']=100*(effects[k]-effects['alpha_0'])
        columns[k+'/cue_effect_pp']=100*effects[k]
        columns[k+'/nll_correct_minus_shuffled']=nll
    return columns
