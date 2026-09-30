#!/bin/bash
# Continuation after build_newseed_tree.sh stopped on a false-positive path check
# (the new path has the old path as a prefix). full.yaml was already edited.
set -Eeuo pipefail
OLD=/home/s2510040/selective_listening_repro/code/auditory_attention
NEW=/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928
SEED=20260928
REF_MANIFEST=$OLD/selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/snapshot/manifest.json
PY=/home/s2510040/miniconda3/envs/attn/bin/python
"$PY" -I -B - "$NEW" "$OLD" "$SEED" <<'PY'
import sys, pathlib, re
new, old, seed = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
# full.yaml must differ from the original only by the seed line
a=(pathlib.Path(old)/"selftrain/configs/full.yaml").read_text(encoding="utf-8")
b=(new/"selftrain/configs/full.yaml").read_text(encoding="utf-8")
assert a.replace("  seed: 20260721\n", f"  seed: {seed}\n")==b, "full.yaml not exactly seed-edited"
print("full.yaml: seed-only edit confirmed")
stale=re.compile(re.escape(old)+r"(?!_seed)")
edits = {
 "selftrain/hakusan/run_training.sbatch": [("--random_seed 20260721", f"--random_seed {seed}", 1)],
 "selftrain/hakusan/run_numerics_preflight.sbatch": [("--random_seed 20260721", f"--random_seed {seed}", 1)],
 "selftrain/hakusan/run_full_pilot_eval.sbatch": [],
 "selftrain/hakusan/submit_training.sh": [],
}
expected_path_hits={"selftrain/hakusan/run_training.sbatch":4,"selftrain/hakusan/run_numerics_preflight.sbatch":4,
                    "selftrain/hakusan/run_full_pilot_eval.sbatch":4,"selftrain/hakusan/submit_training.sh":1}
for rel, subs in edits.items():
    p = new/rel; s = p.read_text(encoding="utf-8")
    if s != (pathlib.Path(old)/rel).read_text(encoding="utf-8"): raise SystemExit("NOT_PRISTINE "+rel)
    for x, y, n in subs:
        c = s.count(x)
        if c != n: raise SystemExit(f"EDIT_COUNT {rel}: {x!r} {c}!={n}")
        s = s.replace(x, y)
    hits = len(stale.findall(s))
    if hits != expected_path_hits[rel]: raise SystemExit(f"PATH_COUNT {rel}: {hits}")
    s = stale.sub(str(new), s)
    if stale.search(s): raise SystemExit("OLD_PATH_REMAINS "+rel)
    p.write_text(s, encoding="utf-8"); print("edited", rel, "paths replaced:", hits)
PY
echo "== diff vs original =="
for f in selftrain/configs/full.yaml selftrain/hakusan/run_training.sbatch selftrain/hakusan/run_numerics_preflight.sbatch selftrain/hakusan/run_full_pilot_eval.sbatch selftrain/hakusan/submit_training.sh; do diff -u "$OLD/$f" "$NEW/$f" || true; done
echo "== remaining 20260721 / old-path mentions in the 5 edited files =="
grep -n -E "20260721|code/auditory_attention([^_]|$)" $NEW/selftrain/configs/full.yaml $NEW/selftrain/hakusan/{run_training.sbatch,run_numerics_preflight.sbatch,run_full_pilot_eval.sbatch,submit_training.sh} || echo "none"
echo "== manifests =="
PYTHONPATH="$NEW" "$PY" -I -B -c "import importlib.util;spec=importlib.util.spec_from_file_location('ri','$NEW/selftrain/scripts/run_integrity.py');ri=importlib.util.module_from_spec(spec);spec.loader.exec_module(ri);m=ri.build_manifest('$NEW');print('NEW semantic',m['semantic_combined_sha256']);print('NEW provenance',m['provenance_combined_sha256'])"
PYTHONPATH="$OLD" "$PY" -I -B -c "import json,importlib.util;spec=importlib.util.spec_from_file_location('ri','$OLD/selftrain/scripts/run_integrity.py');ri=importlib.util.module_from_spec(spec);spec.loader.exec_module(ri);m=ri.build_manifest('$OLD');r=json.load(open('$REF_MANIFEST'));print('ORIGINAL tree semantic equal:',m['semantic_combined_sha256']==r['semantic_combined_sha256'],'provenance equal:',m['provenance_combined_sha256']==r['provenance_combined_sha256'])"
ls -la "$NEW" | head -8; ls -l "$NEW/cv_train" "$NEW/cv_clips"; du -sh --exclude=cv_train --exclude=cv_clips "$NEW" 2>/dev/null
