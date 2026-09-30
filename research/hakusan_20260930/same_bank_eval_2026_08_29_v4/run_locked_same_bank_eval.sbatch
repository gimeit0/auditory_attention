#!/bin/bash
# Locked v4 project-external evaluator
# for the reused 10k validation bank.
# v4 preserves the frozen Job584990 SNR contract and the v3 cross-node
# identity policy while keeping frozen imports alive through inference.
#
# This runner intentionally supports only GPU-consuming commands.  Run
# audit-inputs, freeze-inputs, and check-only on the login node as documented
# in README.md before submitting this file.
#
# Required submission environment:
#   EVAL_ACTION=smoke|run-audit
#   EXTERNAL_ROOT=/home/.../audattn_external_eval/same_bank_2026-08-29_v4
#   INPUT_MANIFEST=$EXTERNAL_ROOT/input_freeze.json
#   EXPECTED_MANIFEST_SHA256=<64 lower-case hex characters>
#
# Example:
#   sbatch --export=EVAL_ACTION=smoke,EXTERNAL_ROOT=...,INPUT_MANIFEST=...,EXPECTED_MANIFEST_SHA256=... \
#     run_locked_same_bank_eval.sbatch
#SBATCH -J audattn_samebank_v4
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 24:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4
#SBATCH --output=/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/logs/%x_%j.log
#SBATCH --error=/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -Eeuo pipefail
trap 'rc=$?; echo "ERROR: line $LINENO exited with $rc" >&2; exit "$rc"' ERR

readonly EXPECTED_ROLE="formal40-primary__valbest33-secondary__author-external"
readonly ANALYSIS_STATUS="REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
readonly EXPECTED_PROTOCOL_ID="fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1"
readonly EXPECTED_FILESYSTEM_IDENTITY_POLICY="cross_invocation_path_size_sha_exact__dev_inode_diagnostic"

: "${SLURM_JOB_ID:?This file must be executed by Slurm}"
: "${EVAL_ACTION:?Set EVAL_ACTION=smoke or EVAL_ACTION=run-audit}"
: "${EXTERNAL_ROOT:?Set the absolute project-external evaluation root}"
: "${INPUT_MANIFEST:?Set the absolute frozen input_freeze.json path}"
: "${EXPECTED_MANIFEST_SHA256:?Set the reviewed frozen-manifest SHA-256}"

case "$EVAL_ACTION" in
    smoke|run-audit) ;;
    *)
        echo "EVAL_ACTION must be smoke or run-audit; got: $EVAL_ACTION" >&2
        exit 2
        ;;
esac

case "$EXTERNAL_ROOT" in
    /*) ;;
    *) echo "EXTERNAL_ROOT must be absolute" >&2; exit 2 ;;
esac
case "$INPUT_MANIFEST" in
    /*) ;;
    *) echo "INPUT_MANIFEST must be absolute" >&2; exit 2 ;;
esac

if [[ ! "$SLURM_JOB_ID" =~ ^[0-9]+$ ]]; then
    echo "Unexpected SLURM_JOB_ID: $SLURM_JOB_ID" >&2
    exit 2
fi
if [[ ! "$EXPECTED_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "EXPECTED_MANIFEST_SHA256 must be 64 lower-case hex characters" >&2
    exit 2
fi

readonly USER_HOME="/home/s2510040"
readonly EXPECTED_EXTERNAL_ROOT="$USER_HOME/audattn_external_eval/same_bank_2026-08-29_v4"
readonly SHA256SUM="/usr/bin/sha256sum"
readonly PROJECT_ROOT="$USER_HOME/selective_listening_repro/code/auditory_attention"
readonly RUN_ID="fullpilot4_accum9_20260815_181000"
readonly RUN_ROOT="$PROJECT_ROOT/selftrain/experiments/runs/$RUN_ID"
readonly PYTHON="$USER_HOME/miniconda3/envs/attn/bin/python"
readonly TOOL="$EXTERNAL_ROOT/tools/locked_same_bank_eval.py"
readonly LIVE_RUNNER="$EXTERNAL_ROOT/tools/run_locked_same_bank_eval.sbatch"
readonly LOCK_FILE="$EXTERNAL_ROOT/state/evaluation.lock"
readonly SUBMITTED_RUNNER_DIR="$EXTERNAL_ROOT/submitted_runners"
readonly SUBMITTED_RUNNER="$SUBMITTED_RUNNER_DIR/${SLURM_JOB_ID}.sbatch"
readonly ENVIRONMENT_FINGERPRINT_PATH="$SUBMITTED_RUNNER_DIR/${SLURM_JOB_ID}.environment.json"

if [ "$EXTERNAL_ROOT" != "$EXPECTED_EXTERNAL_ROOT" ]; then
    echo "EXTERNAL_ROOT must equal the reviewed fresh v4 root: $EXPECTED_EXTERNAL_ROOT" >&2
    exit 2
fi

# Sanitize before the first external command.  Slurm explicit-export mode may
# still resolve a login environment on the execution node; none of its Python,
# Conda, loader, or PATH values are trusted here.
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PROMPT_MODIFIER VIRTUAL_ENV
unset LD_PRELOAD LD_LIBRARY_PATH CUDA_HOME CUDA_PATH
export HOME="$USER_HOME"
export PATH="$USER_HOME/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONNOUSERSITE=1

if [ ! -x "$SHA256SUM" ]; then
    echo "Missing reviewed SHA-256 implementation: $SHA256SUM" >&2
    exit 2
fi

sha256_path () {
    local output digest
    output=$("$SHA256SUM" -- "$1") || return
    digest=${output%% *}
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        echo "Invalid SHA-256 output for: $1" >&2
        return 2
    fi
    printf '%s' "$digest"
}

# The evaluation tree must have been created deliberately by freeze-inputs.
# Refuse to create it from a GPU job: a typo must not produce a second tree.
for required_dir in \
    "$EXTERNAL_ROOT" \
    "$EXTERNAL_ROOT/logs" \
    "$EXTERNAL_ROOT/state" \
    "$EXTERNAL_ROOT/attempts" \
    "$SUBMITTED_RUNNER_DIR" \
    "$EXTERNAL_ROOT/tools"
do
    if [ ! -d "$required_dir" ] || [ -L "$required_dir" ]; then
        echo "Missing or symbolic-link evaluation directory: $required_dir" >&2
        exit 2
    fi
done

if [ "$EXTERNAL_ROOT" = "$PROJECT_ROOT" ] \
    || [[ "$EXTERNAL_ROOT/" == "$PROJECT_ROOT/"* ]] \
    || [[ "$PROJECT_ROOT/" == "$EXTERNAL_ROOT/"* ]]; then
    echo "EXTERNAL_ROOT must be disjoint from PROJECT_ROOT" >&2
    exit 2
fi
if [ "$INPUT_MANIFEST" != "$EXTERNAL_ROOT/input_freeze.json" ]; then
    echo "INPUT_MANIFEST must be the canonical frozen path under EXTERNAL_ROOT" >&2
    exit 2
fi

for required_file in \
    "$TOOL" \
    "$LIVE_RUNNER" \
    "$INPUT_MANIFEST" \
    "$LOCK_FILE" \
    "$RUN_ROOT/snapshot/manifest.json" \
    "$RUN_ROOT/state/COMPLETE" \
    "$RUN_ROOT/state/COMPLETE_RECOVERY.json"
do
    if [ ! -f "$required_file" ] || [ -L "$required_file" ]; then
        echo "Missing, non-regular, or symbolic-link input: $required_file" >&2
        exit 2
    fi
done
if [ ! -x "$PYTHON" ]; then
    echo "Missing attn Python: $PYTHON" >&2
    exit 2
fi

ACTUAL_MANIFEST_SHA256=$(sha256_path "$INPUT_MANIFEST")
readonly ACTUAL_MANIFEST_SHA256
if [ "$ACTUAL_MANIFEST_SHA256" != "$EXPECTED_MANIFEST_SHA256" ]; then
    echo "Frozen evaluation-input manifest SHA-256 mismatch" >&2
    exit 75
fi

# Slurm executes an immutable spool copy.  Close its provenance transitively:
# it must equal the live runner whose SHA is bound by input_freeze.json, and
# smoke/run-audit revalidate that manifest before doing work.
LIVE_RUNNER_SHA256=$(sha256_path "$LIVE_RUNNER")
readonly LIVE_RUNNER_SHA256
SUBMITTED_RUNNER_SHA256=$(sha256_path "$0")
readonly SUBMITTED_RUNNER_SHA256
if [ "$SUBMITTED_RUNNER_SHA256" != "$LIVE_RUNNER_SHA256" ]; then
    echo "Submitted Slurm spool copy does not match the frozen live runner" >&2
    exit 75
fi

# Bootstrap trust without executing the evaluator being checked.  This code is
# embedded in (and therefore frozen with) the submitted runner.  It reads the
# exact bytes whose digest was approved at submission, rejects non-canonical
# JSON/path/hash records, and binds both live executable files to those records.
readonly TRUST_BOOTSTRAP_PROGRAM='
import hashlib
import json
import os
import re
import stat
import sys

(
    manifest_path,
    expected_manifest_sha256,
    external_root,
    runner_path,
    evaluator_path,
    expected_evaluation_role,
    expected_role_confirmation,
    expected_protocol_id,
    expected_filesystem_identity_policy,
) = sys.argv[1:10]
sha_pattern = re.compile(r"[0-9a-f]{64}")
nofollow = getattr(os, "O_NOFOLLOW", 0)

def stable_regular_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | nofollow)
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError("not a regular file: " + path)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise RuntimeError("file identity changed while opening: " + path)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise RuntimeError("file changed while reading: " + path)
        return b"".join(chunks)
    finally:
        os.close(descriptor)

def reject_constant(value):
    raise ValueError("non-finite JSON constant: " + value)

if not sha_pattern.fullmatch(expected_manifest_sha256):
    raise RuntimeError("expected manifest digest is not canonical")
external_root = os.path.abspath(external_root)
canonical_manifest = os.path.join(external_root, "input_freeze.json")
canonical_runner = os.path.join(
    external_root, "tools", "run_locked_same_bank_eval.sbatch"
)
canonical_evaluator = os.path.join(
    external_root, "tools", "locked_same_bank_eval.py"
)
if manifest_path != canonical_manifest:
    raise RuntimeError("manifest path is not canonical")
if runner_path != canonical_runner or evaluator_path != canonical_evaluator:
    raise RuntimeError("tool path is not canonical")
manifest_bytes = stable_regular_bytes(manifest_path)
actual_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
if actual_manifest_sha256 != expected_manifest_sha256:
    raise RuntimeError("reviewed manifest digest mismatch")
manifest = json.loads(
    manifest_bytes.decode("utf-8"),
    parse_constant=reject_constant,
)
if not isinstance(manifest, dict):
    raise RuntimeError("manifest root is not an object")
if manifest.get("schema_version") != 1 or manifest.get("status") != "FROZEN":
    raise RuntimeError("manifest status/schema boundary mismatch")
if manifest.get("evaluation_role") != expected_evaluation_role:
    raise RuntimeError("manifest evaluation role mismatch")
if manifest.get("role_confirmation") != expected_role_confirmation:
    raise RuntimeError("manifest model-role confirmation mismatch")
if manifest.get("protocol_id") != expected_protocol_id:
    raise RuntimeError("manifest protocol ID mismatch")
if manifest.get("filesystem_identity_policy") != expected_filesystem_identity_policy:
    raise RuntimeError("manifest filesystem identity policy mismatch")
roots = manifest.get("roots")
if not isinstance(roots, dict) or roots.get("external_root") != external_root:
    raise RuntimeError("manifest external root mismatch")
inputs = manifest.get("inputs")
if not isinstance(inputs, dict):
    raise RuntimeError("manifest inputs are missing")

def validate_input_record(key, expected_path):
    record = inputs.get(key)
    if not isinstance(record, dict):
        raise RuntimeError("missing frozen input record: " + key)
    digest = record.get("sha256")
    if not isinstance(digest, str) or not sha_pattern.fullmatch(digest):
        raise RuntimeError("non-canonical frozen digest: " + key)
    if record.get("path") != expected_path:
        raise RuntimeError("non-canonical frozen path: " + key)
    payload = stable_regular_bytes(expected_path)
    if len(payload) != record.get("size"):
        raise RuntimeError("frozen size mismatch: " + key)
    if hashlib.sha256(payload).hexdigest() != digest:
        raise RuntimeError("frozen digest mismatch: " + key)
    return digest

runner_sha256 = validate_input_record("sbatch", canonical_runner)
evaluator_sha256 = validate_input_record("evaluator", canonical_evaluator)
print(json.dumps({
    "evaluator_sha256": evaluator_sha256,
    "filesystem_identity_policy": expected_filesystem_identity_policy,
    "manifest_sha256": actual_manifest_sha256,
    "protocol_id": expected_protocol_id,
    "runner_sha256": runner_sha256,
}, sort_keys=True, separators=(",", ":")))
'
TRUST_BOOTSTRAP_RECORD=$(
    "$PYTHON" -I -c "$TRUST_BOOTSTRAP_PROGRAM" \
        "$INPUT_MANIFEST" \
        "$EXPECTED_MANIFEST_SHA256" \
        "$EXTERNAL_ROOT" \
        "$LIVE_RUNNER" \
        "$TOOL" \
        "$ANALYSIS_STATUS" \
        "$EXPECTED_ROLE" \
        "$EXPECTED_PROTOCOL_ID" \
        "$EXPECTED_FILESYSTEM_IDENTITY_POLICY"
)
readonly TRUST_BOOTSTRAP_RECORD
TOOL_SHA256=$(sha256_path "$TOOL")
readonly TOOL_SHA256
TRUST_BOOTSTRAP_HASH_LINE=$(printf '%s' "$TRUST_BOOTSTRAP_RECORD" | "$SHA256SUM")
TRUST_BOOTSTRAP_RECORD_SHA256=${TRUST_BOOTSTRAP_HASH_LINE%% *}
if [[ ! "$TRUST_BOOTSTRAP_RECORD_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Invalid trust-bootstrap record SHA-256" >&2
    exit 2
fi
readonly TRUST_BOOTSTRAP_RECORD_SHA256

# Store the exact spool bytes as an immutable evidence artifact.  The embedded
# Python is part of this frozen sbatch file.  It writes a private temp file,
# fsyncs it, publishes with an atomic hard link (which cannot replace an
# existing path), removes the temp name, and fsyncs the parent directory.
# There is deliberately no heredoc and no cp/mv overwrite fallback.
readonly EXCLUSIVE_COPY_PROGRAM='
import os
import stat
import sys
import uuid

source, destination = sys.argv[1:3]
parent = os.path.dirname(destination)
name = os.path.basename(destination)
if not name or name in {".", ".."}:
    raise SystemExit("invalid destination basename")
nofollow = getattr(os, "O_NOFOLLOW", 0)
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
source_fd = os.open(source, os.O_RDONLY | nofollow)
directory_fd = os.open(parent, directory_flags)
temp_name = "." + name + ".tmp." + str(os.getpid()) + "." + uuid.uuid4().hex
temp_created = False
try:
    source_stat = os.fstat(source_fd)
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError("submitted runner source is not a regular file")
    destination_fd = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
        0o400,
        dir_fd=directory_fd,
    )
    temp_created = True
    try:
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                view = view[written:]
        os.fsync(destination_fd)
    finally:
        os.close(destination_fd)
    try:
        os.link(
            temp_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        print("refusing to overwrite submitted runner: " + destination, file=sys.stderr)
        raise SystemExit(73)
    os.unlink(temp_name, dir_fd=directory_fd)
    temp_created = False
    os.fsync(directory_fd)
finally:
    if temp_created:
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
    os.close(directory_fd)
    os.close(source_fd)
'
"$PYTHON" -I -c "$EXCLUSIVE_COPY_PROGRAM" "$0" "$SUBMITTED_RUNNER"
ARCHIVED_RUNNER_SHA256=$(sha256_path "$SUBMITTED_RUNNER")
readonly ARCHIVED_RUNNER_SHA256
if [ "$ARCHIVED_RUNNER_SHA256" != "$SUBMITTED_RUNNER_SHA256" ]; then
    echo "Archived submitted runner SHA-256 mismatch" >&2
    exit 75
fi

export CV_CLIPS="$PROJECT_ROOT/cv_train/clips"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=8
export TOKENIZERS_PARALLELISM=false

ENVIRONMENT_FINGERPRINT=$(
    "$PYTHON" -I -c 'import json, os, platform, sys; import torch; print(json.dumps({"cuda_available": torch.cuda.is_available(), "cuda_runtime": torch.version.cuda, "cudnn": torch.backends.cudnn.version(), "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, "hostname": platform.node(), "python": sys.version.split()[0], "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "torch": torch.__version__}, sort_keys=True, separators=(",", ":")))'
)
readonly ENVIRONMENT_FINGERPRINT

# Persist the exact environment evidence before invoking the evaluator.  The
# archived bytes are canonical JSON followed by one newline; an atomic hard
# link publishes the private fsynced temp file and can never replace an
# existing job record.  The evaluator receives both this path and the SHA of
# these exact bytes, so a digest printed only in the log cannot stand in for
# independently re-readable evidence.
readonly EXCLUSIVE_JSON_PROGRAM='
import hashlib
import json
import os
import stat
import sys
import uuid

payload_text, destination = sys.argv[1:3]
parent = os.path.dirname(destination)
name = os.path.basename(destination)
if not name or name in {".", ".."}:
    raise SystemExit("invalid destination basename")

def reject_constant(value):
    raise ValueError("non-finite JSON constant: " + value)

payload = json.loads(payload_text, parse_constant=reject_constant)
if not isinstance(payload, dict):
    raise RuntimeError("environment fingerprint must be a JSON object")
canonical = (
    json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    + "\n"
).encode("utf-8")

nofollow = getattr(os, "O_NOFOLLOW", 0)
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
directory_fd = os.open(parent, directory_flags)
temp_name = "." + name + ".tmp." + str(os.getpid()) + "." + uuid.uuid4().hex
temp_created = False
try:
    destination_fd = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
        0o400,
        dir_fd=directory_fd,
    )
    temp_created = True
    try:
        view = memoryview(canonical)
        while view:
            written = os.write(destination_fd, view)
            view = view[written:]
        os.fsync(destination_fd)
    finally:
        os.close(destination_fd)
    try:
        os.link(
            temp_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        print(
            "refusing to overwrite environment fingerprint: " + destination,
            file=sys.stderr,
        )
        raise SystemExit(73)
    os.unlink(temp_name, dir_fd=directory_fd)
    temp_created = False
    os.fsync(directory_fd)
finally:
    if temp_created:
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
    os.close(directory_fd)

print(hashlib.sha256(canonical).hexdigest())
'
ENVIRONMENT_ARCHIVE_SHA256=$(
    "$PYTHON" -I -c "$EXCLUSIVE_JSON_PROGRAM" \
        "$ENVIRONMENT_FINGERPRINT" \
        "$ENVIRONMENT_FINGERPRINT_PATH"
)
readonly ENVIRONMENT_ARCHIVE_SHA256
ENVIRONMENT_FINGERPRINT_SHA256=$(sha256_path "$ENVIRONMENT_FINGERPRINT_PATH")
if [[ ! "$ENVIRONMENT_FINGERPRINT_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Invalid environment fingerprint SHA-256" >&2
    exit 2
fi
readonly ENVIRONMENT_FINGERPRINT_SHA256
if [ "$ENVIRONMENT_FINGERPRINT_SHA256" != "$ENVIRONMENT_ARCHIVE_SHA256" ]; then
    echo "Archived environment fingerprint SHA-256 mismatch" >&2
    exit 75
fi

echo "EVAL_ACTION=$EVAL_ACTION"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "EXTERNAL_ROOT=$EXTERNAL_ROOT"
echo "INPUT_MANIFEST_SHA256=$ACTUAL_MANIFEST_SHA256"
echo "LIVE_RUNNER_SHA256=$LIVE_RUNNER_SHA256"
echo "SUBMITTED_RUNNER_SHA256=$SUBMITTED_RUNNER_SHA256"
echo "ARCHIVED_RUNNER_SHA256=$ARCHIVED_RUNNER_SHA256"
echo "TOOL_SHA256=$TOOL_SHA256"
echo "TRUST_BOOTSTRAP_RECORD=$TRUST_BOOTSTRAP_RECORD"
echo "TRUST_BOOTSTRAP_RECORD_SHA256=$TRUST_BOOTSTRAP_RECORD_SHA256"
echo "ENVIRONMENT_FINGERPRINT=$ENVIRONMENT_FINGERPRINT"
echo "ENVIRONMENT_FINGERPRINT_PATH=$ENVIRONMENT_FINGERPRINT_PATH"
echo "ENVIRONMENT_FINGERPRINT_SHA256=$ENVIRONMENT_FINGERPRINT_SHA256"
echo "MODEL_ROLES=$EXPECTED_ROLE"
echo "ANALYSIS_STATUS=$ANALYSIS_STATUS"
echo "WARNING: these results are NOT an independent test result."

# The Python tool owns the existing NFS-visible lock for the complete command.
# Do not take a second shell flock here: doing so would deadlock a non-reentrant
# exclusive lock.  The tool also creates a new attempt directory with O_EXCL,
# writes an in-progress record before inference, and atomically publishes only
# after validation.  Partial attempts are never resumed or overwritten.
common_args=(
    --external-root "$EXTERNAL_ROOT"
    --manifest "$INPUT_MANIFEST"
    --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
    --attempt-id "slurm-${SLURM_JOB_ID}"
    --job-id "$SLURM_JOB_ID"
    --submitted-runner "$SUBMITTED_RUNNER"
    --submitted-runner-sha256 "$SUBMITTED_RUNNER_SHA256"
    --environment-fingerprint "$ENVIRONMENT_FINGERPRINT_PATH"
    --environment-fingerprint-sha256 "$ENVIRONMENT_FINGERPRINT_SHA256"
    --confirm-role "$EXPECTED_ROLE"
)

case "$EVAL_ACTION" in
    smoke)
        "$PYTHON" -u "$TOOL" smoke "${common_args[@]}"
        ;;
    run-audit)
        "$PYTHON" -u "$TOOL" run-audit "${common_args[@]}"
        ;;
esac

echo "COMMAND FINISHED: $EVAL_ACTION"
echo "Interpret only an atomically published marker whose hashes revalidate."
echo "MODEL_ROLES=$EXPECTED_ROLE"
echo "ANALYSIS_STATUS=$ANALYSIS_STATUS"
