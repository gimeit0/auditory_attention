"""Offline V4 anchor check: alpha 0.50 and 0.75 must reproduce job 756262 bit for bit. Local only.

V4 block A holds alpha_0500 and block B holds alpha_0750; in 756262 both were in block C. Every domain and
condition must match exactly in trial_ids, logits and nll. Arrays are SHA-checked against their WORKER.json.
"""
import numpy as np

CONDITIONS = {'main': ('correct', 'shuffled', 'silent', 'distractor'), 'clean': ('correct_cue', 'zero_cue')}
ANCHORS = {'alpha_0500': ('A', 'C'), 'alpha_0750': ('B', 'C')}   # pass: (V4 block, 756262 block)


def compare(v4_blocks, old_blocks):
    """v4_blocks/old_blocks: {block: {(block, domain, pass, condition): {'trial_ids','logits','nll'}}}."""
    rows = []
    for p, (new_block, old_block) in ANCHORS.items():
        for domain, conds in CONDITIONS.items():
            for cond in conds:
                a = v4_blocks[new_block][new_block, domain, p, cond]; b = old_blocks[old_block][old_block, domain, p, cond]
                same = {k: bool(np.asarray(a[k]).dtype == np.asarray(b[k]).dtype and np.asarray(a[k]).shape == np.asarray(b[k]).shape
                                and np.asarray(a[k]).tobytes() == np.asarray(b[k]).tobytes()) for k in ('trial_ids', 'logits', 'nll')}
                diff = (float(np.abs(np.asarray(a['logits'], np.float64) - np.asarray(b['logits'], np.float64)).max())
                        if np.asarray(a['logits']).shape == np.asarray(b['logits']).shape else None)
                rows.append(dict(pass_name=p, domain=domain, condition=cond, bitwise=all(same.values()), fields=same,
                                 max_abs_logit_difference=diff))
    passed = all(r['bitwise'] for r in rows)
    return dict(status='V4_ANCHORS_BITWISE_EQUAL_756262' if passed else 'V4_ANCHOR_MISMATCH_756262',
                passed=passed, arrays_compared=len(rows), rows=rows)
