"""Fine-grid body and independent arrays. Provider/strict loading owned by session."""
import hashlib
import platform
import resource
import time
import numpy as np
import torch
from e0_layout_reference import validate_logits, require
from e1_artifacts import canonical
from e1_execution import utc_now
from fine_alpha_contract import CONDITIONS, BLOCKS, passes, batches, inventory
from fine_alpha_gain import context, check_formula

def same(a, b, label='FINE_BITS'):
    require(a['trial_ids'] == b['trial_ids'], 'FINE_COMPARISON_IDS')
    for field in ('logits', 'nll'):
        x, y = a[field], b[field]
        require(x.dtype == y.dtype and x.shape == y.shape and x.tobytes() == y.tobytes(), label)

def bridge(records, block, reference):
    for domain, conditions in CONDITIONS.items():
        for cond in conditions:
            original = records[(block, domain, 'original', cond)]
            observed = records[(block, domain, 'reference', cond)]
            same(original, observed, 'FINE_NATIVE_ALPHA1_BITS')
            same(observed, reference[('completed_epochs_40', domain, 'alpha_1', cond)], 'FINE_HISTORY_BITS')

def verify_arrays(layout, records, block=None, *, reference=None):
    expected = inventory(layout, block)
    require(set(records) == set(expected), 'FINE_INVENTORY')
    for key, ids in expected.items():
        row = records[key]
        require(row['trial_ids'] == ids, 'FINE_TRIAL_ORDER')
        require(row['nll'].dtype == np.float32, 'FINE_NLL_DTYPE')
        validate_logits(row['logits'], ids, np.array([layout['labels'][str(i)] for i in ids]), row['nll'])
    for b in BLOCKS if block is None else (block,):
        if reference is not None:
            bridge(records, b, reference)
        for domain, conditions in CONDITIONS.items():
            for cond in conditions:
                same(records[(b, domain, 'original', cond)], records[(b, domain, 'reference', cond)])
                if block is None:
                    same(records[(BLOCKS[0], domain, 'reference', cond)], records[(b, domain, 'reference', cond)], 'FINE_COLD_BITS')
    # V4 has no alpha=0 or alpha=1 science pass, so the V1-V3 bypass/alpha=1/clean-zero identities do not apply.
    # alpha=0.50 and 0.75 are bitwise anchors to job 756262, checked offline in the readout.
    return dict(status='FINE_ALPHA_ARRAYS_VERIFIED_NOT_PROVENANCE', predictions=sum(map(len, expected.values())),
                records=len(records), production_verified=False)

def execute(layout, block, ctx, sink, *, reference, seconds=7200, clock=time.monotonic):
    require(type(seconds) in (int, float) and 0 < seconds <= 7800, 'FINE_TIME_BUDGET')
    core, base, outer = ctx['core'], ctx['base'], ctx['outer']
    provider, device = ctx['batch_provider'], ctx['device']
    started = clock(); start_utc = utc_now(); identities = {}; formulas = []; resources = []
    saved_references = {}; predictions = 0
    use_cuda = str(device).startswith('cuda')
    def check():
        if clock() - started >= seconds:
            raise TimeoutError('FINE_WORKER_DEADLINE')
    for pass_name in passes(block):
        for domain, conditions in CONDITIONS.items():
            check(); stamp = utc_now(); pstart = clock()
            if use_cuda: torch.cuda.reset_peak_memory_stats(device)
            payload = {cond: dict(trial_ids=[], logits=[], nll=[]) for cond in conditions}
            with context(core, outer, ctx['architecture_type'], ctx['gain_type'], pass_name):
                formulas.append(dict(domain=domain, pass_name=pass_name, report=check_formula(outer.model, pass_name)))
                for bi in range(len(batches(layout, domain, conditions[0]))):
                    for cond in conditions:
                        ids = batches(layout, domain, cond)[bi]
                        if not ids: continue
                        check()
                        scene, cue, labels, probes = provider(domain, bi, cond, list(ids))
                        require(labels.tolist() == [layout['labels'][str(i)] for i in ids], 'FINE_LABELS')
                        require(len(scene) == len(cue) == len(labels) == len(probes) == len(ids), 'FINE_BATCH_SIZE')
                        observed = (tuple(base._tensor_hashes(scene)), tuple(base._tensor_hashes(cue)))
                        ident = (domain, bi, cond); identities.setdefault(ident, observed)
                        require(identities[ident] == observed, 'FINE_INPUT_CHANGED')
                        values, logits = core.predict(base, outer, scene, cue, labels, probes, device)
                        check(); p = payload[cond]; p['trial_ids'].extend(ids)
                        p['logits'].append(logits); p['nll'].append(values['nll'])
            for cond, p in payload.items():
                p['logits'] = np.concatenate(p['logits']); p['nll'] = np.concatenate(p['nll'])
                require(p['nll'].dtype == np.float32, 'FINE_NLL_DTYPE')
                validate_logits(p['logits'], p['trial_ids'], np.array([layout['labels'][str(i)] for i in p['trial_ids']]), p['nll'])
                key = (block, domain, pass_name, cond)
                if pass_name in ('original', 'reference'): saved_references[key] = p
                check(); sink(key, p); check(); predictions += len(p['trial_ids'])
            resources.append(dict(domain=domain, pass_name=pass_name, started_utc=stamp, finished_utc=utc_now(),
                elapsed_seconds=clock()-pstart,
                cuda_max_memory_allocated_bytes=int(torch.cuda.max_memory_allocated(device)) if use_cuda else None,
                cuda_max_memory_reserved_bytes=int(torch.cuda.max_memory_reserved(device)) if use_cuda else None,
                host_max_rss_ru_maxrss=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
                ru_maxrss_unit='bytes' if platform.system() == 'Darwin' else 'KiB'))
        if pass_name == 'reference':
            bridge(saved_references, block, reference)  # Fail BEFORE science passes, not only at final verification.
    input_rows = [dict(key=list(k), hashes=v) for k, v in sorted(identities.items())]
    return dict(status='FINE_ALPHA_BODY_FINISHED_NOT_QUALIFIED', predictions=predictions,
                gain_formula_reports=formulas, runtime_values=core.runtime_values(),
                process_started_utc=start_utc, process_finished_utc=utc_now(), pass_resources=resources,
                input_identity_sha256=hashlib.sha256(canonical(input_rows)).hexdigest(),
                historical_bridge_completed=True)
