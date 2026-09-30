#!/bin/bash
# Build an independent project tree for the new-seed retrain. Never writes to the original tree.
set -Eeuo pipefail
OLD=/home/s2510040/selective_listening_repro/code/auditory_attention
NEW=/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928
SEED=20260928
REF_MANIFEST=$OLD/selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/snapshot/manifest.json
PY=/home/s2510040/miniconda3/envs/attn/bin/python
[ -e "$NEW" ] && { echo "STOP: $NEW exists"; exit 3; }
rsync -a \
  --exclude=/cv_train --exclude=/cv_clips --exclude=/.git --exclude=/attn_cue_models --exclude=/notebooks \
  --exclude=/.venv --exclude=/selftrain/experiments --exclude=/selftrain/numerics_preflight_runs \
  --exclude=/selftrain/preflight_runs --exclude=/selftrain/hakusan/logs --exclude=__pycache__ \
  "$OLD/" "$NEW/"
ln -s "$OLD/cv_train" "$NEW/cv_train"
ln -s "$OLD/cv_clips" "$NEW/cv_clips"
mkdir -p "$NEW/selftrain/experiments/runs" "$NEW/selftrain/hakusan/logs" "$NEW/selftrain/numerics_preflight_runs"
echo "== copy fidelity: NEW manifest vs formal40 snapshot manifest (before edits) =="
cd "$NEW"
PYTHONPATH="$NEW" "$PY" -I -B - "$NEW" "$REF_MANIFEST" <<'PY'
import sys, json, importlib.util, pathlib
spec=importlib.util.spec_from_file_location("ri", pathlib.Path(sys.argv[1])/"selftrain/scripts/run_integrity.py"); ri=importlib.util.module_from_spec(spec); spec.loader.exec_module(ri)
m=ri.build_manifest(sys.argv[1]); ref=json.load(open(sys.argv[2]))
print("semantic", m["semantic_combined_sha256"], "equal" if m["semantic_combined_sha256"]==ref["semantic_combined_sha256"] else "DIFFERENT")
print("provenance", m["provenance_combined_sha256"], "equal" if m["provenance_combined_sha256"]==ref["provenance_combined_sha256"] else "DIFFERENT")
if m["semantic_combined_sha256"]!=ref["semantic_combined_sha256"] or m["provenance_combined_sha256"]!=ref["provenance_combined_sha256"]:
    a={e["path"]:e["sha256"] for e in ref["provenance_files"]}; b={e["path"]:e["sha256"] for e in m["provenance_files"]}
    print("missing",sorted(set(a)-set(b))[:10],"added",sorted(set(b)-set(a))[:10],"changed",[k for k in a if k in b and a[k]!=b[k]][:10]); sys.exit(4)
PY
echo "== apply edits (exact-count guarded) =="
"$PY" -I -B - "$NEW" "$OLD" "$SEED" <<'PY'
import sys, pathlib
new, old, seed = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
edits = {
 "selftrain/configs/full.yaml": [("  seed: 20260721\n", f"  seed: {seed}\n", 1)],
 "selftrain/hakusan/run_training.sbatch": [("--random_seed 20260721", f"--random_seed {seed}", 1), (old+"/", str(new)+"/", 2), (f'"{old}"', f'"{new}"', 1), ("--chdir="+old+"\n", "--chdir="+str(new)+"\n", 1)],
 "selftrain/hakusan/run_numerics_preflight.sbatch": [("--random_seed 20260721", f"--random_seed {seed}", 1), (old+"/", str(new)+"/", 2), (f'"{old}"', f'"{new}"', 1), ("--chdir="+old+"\n", "--chdir="+str(new)+"\n", 1)],
 "selftrain/hakusan/run_full_pilot_eval.sbatch": [(old+"/", str(new)+"/", 2), (f'"{old}"', f'"{new}"', 1), ("--chdir="+old+"\n", "--chdir="+str(new)+"\n", 1)],
 "selftrain/hakusan/submit_training.sh": [(f'"{old}"', f'"{new}"', 1)],
}
for rel, subs in edits.items():
    p = new/rel; s = p.read_text(encoding="utf-8")
    for a, b, n in subs:
        c = s.count(a)
        if c != n: raise SystemExit(f"EDIT_COUNT {rel}: {a!r} found {c}, expected {n}")
        s = s.replace(a, b)
    if old in s: raise SystemExit(f"OLD_PATH_REMAINS {rel}")
    p.write_text(s, encoding="utf-8"); print("edited", rel)
PY
echo "== diff vs original =="
for f in selftrain/configs/full.yaml selftrain/hakusan/run_training.sbatch selftrain/hakusan/run_numerics_preflight.sbatch selftrain/hakusan/run_full_pilot_eval.sbatch selftrain/hakusan/submit_training.sh; do diff -u "$OLD/$f" "$NEW/$f" || true; done
echo "== new manifest after edits =="
PYTHONPATH="$NEW" "$PY" -I -B -c "import sys,importlib.util,pathlib;spec=importlib.util.spec_from_file_location('ri','$NEW/selftrain/scripts/run_integrity.py');ri=importlib.util.module_from_spec(spec);spec.loader.exec_module(ri);m=ri.build_manifest('$NEW');print('semantic',m['semantic_combined_sha256']);print('provenance',m['provenance_combined_sha256'])"
echo "== original tree untouched check =="
PYTHONPATH="$OLD" "$PY" -I -B -c "import sys,json,importlib.util;spec=importlib.util.spec_from_file_location('ri','$OLD/selftrain/scripts/run_integrity.py');ri=importlib.util.module_from_spec(spec);spec.loader.exec_module(ri);m=ri.build_manifest('$OLD');r=json.load(open('$REF_MANIFEST'));print('original semantic equal:',m['semantic_combined_sha256']==r['semantic_combined_sha256'],'provenance equal:',m['provenance_combined_sha256']==r['provenance_combined_sha256'])"
