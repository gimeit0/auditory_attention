# 同一冻结 bank 的项目外评估 v4（2026-08-29）

v4 保留 v3 已审定的 NFS portable identity、Job584990 CSV ULP 边界和全部科学合同，只修正 Job642803 暴露的冻结导入生命周期：冻结 `eval_full_pilot.py` 的场景函数会在推理时延迟导入 `selftrain`，因此同一个冻结导入上下文现在覆盖模型加载、场景生成和 smoke 的两次推理。任务、bank、checkpoint 角色和科学边界均不变。

v4 的精确协议边界为：

```text
protocol_id=fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1
filesystem_identity_policy=cross_invocation_path_size_sha_exact__dev_inode_diagnostic
```

跨 invocation/跨节点的权威绑定是 canonical path、basename、size 和 SHA-256；`st_dev/st_ino` 仅是诊断值，只在同一进程内用于 fd↔path TOCTOU 检查。这是已审定的边界 B。
历史 SNR 身份仍严格使用 `SNR_IDENTITY_ATOL_DB = 1e-12`，不得因 NFS 修复而放宽。

这套工具用于让三个已冻结模型在完全相同的 10k bank 上重新预测，并按 SNR 和干扰者数量分层：

- 本次 full 训练的 `formal-final.ckpt`（协议终点）；
- `epoch=33-step=59024.ckpt`（由现有 validation accuracy 选择，只作次要分析）；
- 作者 checkpoint（任务/分布不完全一致的外部参照）。

## 最重要的边界

这个 10k bank 来自已经用过的 validation-speaker / pilot4 评估资产。因此所有输入 manifest、运行记录和结果都必须带上以下精确标签：

```text
REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST
```

它可以回答“在同一批题上，各模型随 SNR/干扰数怎样变化”，但不能当作最终独立 test accuracy，也不能将作者 checkpoint 与我们 checkpoint 的总正确率简单解释为模型谁更好。

## 安全模型

- 工具、manifest、日志和结果都放在项目外的 `$HOME/audattn_external_eval/same_bank_2026-08-29_v4`。不向 live project 或训练 run snapshot 写入文件。
- runner 在执行首个外部命令前会把 `EXTERNAL_ROOT` 硬限定为 `$HOME/audattn_external_eval/same_bank_2026-08-29_v4`；任何 v1、v2、v3 或其他根都必须以退出码 2 拒绝。
- v3 失败根 `$HOME/audattn_external_eval/same_bank_2026-08-29_v3` 只作取证保留。Job `642803`（`audattn_samebank_v3`）的状态是 `FAILED 1:0`；attempt 为 `attempts/smoke/slurm-642803/`，包含 `RUNNING.json` 与 `FAILED.json`，而 `SMOKE_PASS.json` 不存在。三个模型已加载，但首批音频场景在任何预测前因 `ModuleNotFoundError: No module named 'selftrain'` 失败。environment artifact 的 SHA-256 为 `38493aa274bc9f707ab11fb195bcfa9d10dd68cde95f83d47ed1c3744bc0dc15`。禁止删除、retry、覆盖、重新 freeze，或把 v3 manifest、lock、attempt、工具复制/硬链接到 v4。
- v2 失败根 `$HOME/audattn_external_eval/same_bank_2026-08-29_v2` 只作取证保留。Job `637966` 的状态是 `FAILED 2:0`。其 log `$HOME/audattn_external_eval/same_bank_2026-08-29_v2/logs/audattn_samebank_v2_637966.log` 的 SHA-256 为 `f98220239dd61542b557c536d213715a60338b158d1225ae530ed7ca5c5b4683`，environment artifact `$HOME/audattn_external_eval/same_bank_2026-08-29_v2/submitted_runners/637966.environment.json` 的 SHA-256 为 `3f0687eae80701cb95b222f6e90e3f4213cf340037fad0b0bd12c41da126356b`，submitted runner archive `$HOME/audattn_external_eval/same_bank_2026-08-29_v2/submitted_runners/637966.sbatch` 的 SHA-256 为 `fe28d02c695b36608fcdd2d2e5796c6bbb985471850866aa355a6a327efb960e`。禁止删除、retry、覆盖、重新 freeze 或将任何 v2 文件复制/硬链接到 v4。
- v1 失败根 `$HOME/audattn_external_eval/same_bank_2026-08-29` 也只作取证保留：不删除、不覆盖、不执行 `freeze-inputs`，也不把其任何文件硬链接或复制到 v4。
- 旧 `PILOT4_BANK_FROZEN.json` 和 `frozen_bank.tsv` 只读引用；本工具不冒充它们原先的 freeze 绑定。
- `freeze-inputs` 是唯一创建冻结输入和锁文件的步骤，而且拒绝覆盖。
- `check-only` 绝对不得创建目录、`state/evaluation.lock` 或任何状态。
- `smoke` 和 `run-audit` 由 Python 工具全程持有同一把 NFS 可见锁。每次 Slurm 作业创建唯一 attempt，既不覆盖，也不续跑中途失败的 attempt。
- 只有完整校验后原子发布的 marker 是权威结果。`RUNNING`/`FAILED` attempt 中的临时 CSV 不可用于结论。
- 不提供 `--force`、覆盖或从 partial output 恢复的通道。重跑必须用新 Job ID / 新 attempt，从第 0 条题开始。

## 外部目录

`freeze-inputs` 成功并完成提交前的输出目录准备后，应有如下结构：

```text
$HOME/audattn_external_eval/same_bank_2026-08-29_v4/
├── input_freeze.json
├── logs/
├── state/
│   ├── evaluation.lock                 # canonical nonempty JSON
│   ├── SMOKE_PASS.json                  # smoke 成功后
│   └── SAME_BANK_AUDIT_PUBLISHED.json  # full audit 成功后
├── tools/
│   ├── locked_same_bank_eval.py
│   └── run_locked_same_bank_eval.sbatch
├── submitted_runners/
│   ├── <job-id>.sbatch
│   └── <job-id>.environment.json       # canonical JSON + one newline
└── attempts/
    ├── smoke/
    │   └── slurm-<job-id>/
    └── audit/
        └── slurm-<job-id>/
```

`input_freeze.json` 至少要以 SHA-256 绑定：工具本身、冻结 run snapshot manifest/config、`COMPLETE`、`COMPLETE_RECOVERY.json`、旧 bank 及 freeze record、三个 checkpoint/模型 profile、数据根身份以及评估协议。其中 epoch33 checkpoint 必须记录 `epoch=33, global_step=59024`；formal-final 必须记录 `epoch=40, global_step=69440`，并重新校验 completion-recovery sidecar 的全部绑定。

`state/evaluation.lock` 不再是空文件，而是 canonical JSON，且必须恰好包含 `schema_version=1`、上述 `protocol_id`、上述 `filesystem_identity_policy`、`purpose=cross_node_evaluation_flock_identity`、`external_root` 的精确 canonical 绝对路径和 `lock_nonce`。`lock_nonce` 必须由 `secrets.token_hex(32)` 生成，即 256-bit、恰好 64 个小写十六进制字符；空 nonce、重用 v2/v3 lock 或手写 lock 均必须拒绝。

## 1. 上传工具（不上传到项目中）

上传本身也是 one-shot 发布。不能用 `mkdir -p .../tools` 或直接 `scp` 到最终文件名：那会复用旧的日期目录，并可能覆盖已被 manifest 绑定的工具。

先在 Mac 上校验本地待上传文件：

```bash
LOCAL_DIR="/Users/gigi/发表/超算/same_bank_eval_2026_08_29_v4"
EXPECTED_EVALUATOR_SHA256="31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
EXPECTED_RUNNER_SHA256="b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495"

printf '%s  %s\n' "$EXPECTED_EVALUATOR_SHA256" \
  "$LOCAL_DIR/locked_same_bank_eval.py" \
  | /usr/bin/shasum -a 256 -c -
printf '%s  %s\n' "$EXPECTED_RUNNER_SHA256" \
  "$LOCAL_DIR/run_locked_same_bank_eval.sbatch" \
  | /usr/bin/shasum -a 256 -c -
```

然后独占创建全新的评估根、`tools/` 和临时上传目录。如果当天的根已存在（即使只是一次中断的上传），下面会 STOP；不要删除、覆盖或复用它，应换新的版本化根并同步更新 runner 的 `#SBATCH` 绝对路径后重新审阅：

```bash
ssh s2510040@hakusan1 '
  set -eu
  BASE="$HOME/audattn_external_eval"
  EVAL_ROOT="$BASE/same_bank_2026-08-29_v4"
  test ! -L "$BASE" || { echo "STOP: external base is a symlink" >&2; exit 2; }
  if [ ! -e "$BASE" ]; then mkdir "$BASE"; fi
  test -d "$BASE" || { echo "STOP: invalid external base" >&2; exit 2; }
  test ! -e "$EVAL_ROOT" && test ! -L "$EVAL_ROOT" \
    || { echo "STOP: dated evaluation root already exists; do not reuse it" >&2; exit 2; }
  mkdir "$EVAL_ROOT"
  mkdir "$EVAL_ROOT/tools"
  mkdir "$EVAL_ROOT/.upload-staging"
'
```

只把文件传到刚创建的 staging 目录，不直接写最终工具名：

```bash
scp "$LOCAL_DIR/locked_same_bank_eval.py" \
    "$LOCAL_DIR/run_locked_same_bank_eval.sbatch" \
    s2510040@hakusan1:audattn_external_eval/same_bank_2026-08-29_v4/.upload-staging/
```

最后在远端先按人工审定 SHA 校验 staging，再用 hard link 的 no-overwrite 语义发布到 `tools/`，重新校验最终名后才清理 staging：

```bash
ssh s2510040@hakusan1 '
  set -eu
  EVAL_ROOT="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"
  STAGING="$EVAL_ROOT/.upload-staging"
  EVALUATOR_SHA="31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
  RUNNER_SHA="b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495"
  test -d "$STAGING" && test ! -L "$STAGING" || exit 2
  printf "%s  %s\n" "$EVALUATOR_SHA" "$STAGING/locked_same_bank_eval.py" \
    | /usr/bin/sha256sum -c -
  printf "%s  %s\n" "$RUNNER_SHA" "$STAGING/run_locked_same_bank_eval.sbatch" \
    | /usr/bin/sha256sum -c -
  ln "$STAGING/locked_same_bank_eval.py" "$EVAL_ROOT/tools/locked_same_bank_eval.py"
  ln "$STAGING/run_locked_same_bank_eval.sbatch" "$EVAL_ROOT/tools/run_locked_same_bank_eval.sbatch"
  printf "%s  %s\n" "$EVALUATOR_SHA" "$EVAL_ROOT/tools/locked_same_bank_eval.py" \
    | /usr/bin/sha256sum -c -
  printf "%s  %s\n" "$RUNNER_SHA" "$EVAL_ROOT/tools/run_locked_same_bank_eval.sbatch" \
    | /usr/bin/sha256sum -c -
  /usr/bin/unlink "$STAGING/locked_same_bank_eval.py"
  /usr/bin/unlink "$STAGING/run_locked_same_bank_eval.sbatch"
  rmdir "$STAGING"
'
```

不要把这两个文件复制进 `selective_listening_repro`。任一 SHA 校验失败、最终名已存在或上传中断时都必须停止；不要对该根执行 `freeze-inputs`。

## 2. 定义本次唯一路径

登录 HAKUSAN 后：

```bash
PROJECT_ROOT="$HOME/selective_listening_repro/code/auditory_attention"
RUN_ID="fullpilot4_accum9_20260815_181000"
RUN_ROOT="$PROJECT_ROOT/selftrain/experiments/runs/$RUN_ID"
EVAL_ROOT="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"
TOOL="$EVAL_ROOT/tools/locked_same_bank_eval.py"
RUNNER="$EVAL_ROOT/tools/run_locked_same_bank_eval.sbatch"
PYTHON="$HOME/miniconda3/envs/attn/bin/python"
ANALYSIS_STATUS="REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
MODEL_ROLES="formal40-primary__valbest33-secondary__author-external"
RECOVERY_TOOL="$HOME/audattn_recovery/2026-08-28/recover_full_completion_2026_08_28.py"
EXPECTED_RECOVERY_TOOL_SHA256="f7b682f61920d21d181a4721a32e87d4dc216d07df3d476392ee2de41f967959"
VALBEST_CHECKPOINT="$RUN_ROOT/full/checkpoints/epoch=33-step=59024.ckpt"
EXPECTED_VALBEST_SHA256="853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14"
EXPECTED_EVAL_ROOT="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"

verify_reviewed_static_inputs () {
  test -f "$VALBEST_CHECKPOINT" && test ! -L "$VALBEST_CHECKPOINT" \
    || { echo "STOP: invalid epoch33 checkpoint"; return 2; }
  test -f "$RECOVERY_TOOL" && test ! -L "$RECOVERY_TOOL" \
    || { echo "STOP: reviewed recovery tool is missing"; return 2; }
  VALBEST_HASH_LINE=$(/usr/bin/sha256sum "$VALBEST_CHECKPOINT") || return 2
  RECOVERY_HASH_LINE=$(/usr/bin/sha256sum "$RECOVERY_TOOL") || return 2
  ACTUAL_VALBEST_SHA256=${VALBEST_HASH_LINE%% *}
  ACTUAL_RECOVERY_TOOL_SHA256=${RECOVERY_HASH_LINE%% *}
  test "$ACTUAL_VALBEST_SHA256" = "$EXPECTED_VALBEST_SHA256" \
    || { echo "STOP: epoch33 SHA-256 differs from the human-reviewed value"; return 2; }
  test "$ACTUAL_RECOVERY_TOOL_SHA256" = "$EXPECTED_RECOVERY_TOOL_SHA256" \
    || { echo "STOP: recovery-tool SHA-256 differs from the reviewed value"; return 2; }
}

verify_external_root_boundary () {
  test "$EVAL_ROOT" = "$EXPECTED_EVAL_ROOT" \
    || { echo "STOP: EVAL_ROOT is not the reviewed v4 root"; return 2; }
  case "$EVAL_ROOT/" in
    "$PROJECT_ROOT/"* ) echo "STOP: EVAL_ROOT is inside project"; return 2 ;;
  esac
  case "$PROJECT_ROOT/" in
    "$EVAL_ROOT/"* ) echo "STOP: PROJECT_ROOT is inside EVAL_ROOT"; return 2 ;;
  esac
}

STATIC_INPUT_GATE=2
if verify_reviewed_static_inputs && verify_external_root_boundary; then
  STATIC_INPUT_GATE=0
  echo "STATIC INPUT GATE: PASS"
else
  echo "STOP: static-input/root gate failed; do not continue" >&2
fi
test "$STATIC_INPUT_GATE" -eq 0
```

任何一个上述命令输出 `STOP` 或返回非 0 时，不要继续复制后续命令。后续每个关键命令也会在同一 `if` 成功分支内重算这两个检查，不依赖用户看到 `false` 后手动停止。

## 3. `audit-inputs`：只读发现

以下参数是本目录的 CLI 合同；正式运行前先用 `--help` 核对实现版本。

```bash
"$PYTHON" "$TOOL" audit-inputs --help
AUDIT_INPUTS_GATE=2
if verify_reviewed_static_inputs && verify_external_root_boundary; then
  if "$PYTHON" "$TOOL" audit-inputs \
    --project-root "$PROJECT_ROOT" \
    --run-root "$RUN_ROOT" \
    --external-root "$EVAL_ROOT" \
    --recovery-tool "$RECOVERY_TOOL" \
    --sbatch "$RUNNER" \
    --expected-valbest-sha256 "$EXPECTED_VALBEST_SHA256"; then
    AUDIT_INPUTS_GATE=0
  fi
fi
if [ "$AUDIT_INPUTS_GATE" -ne 0 ]; then
  echo "STOP: audit-inputs gate failed; do not freeze" >&2
fi
test "$AUDIT_INPUTS_GATE" -eq 0
```

`audit-inputs` 只在 stdout 打印 candidate 和 SHA；不应建目录或锁。人工检查下列项目后再 freeze：

- bank 是该 run 的 `evaluation/pilot4/frozen_bank.tsv`，而不是重新随机生成的样本；
- 顶层 `protocol_id` 和 `filesystem_identity_policy` 必须与本文已审定值完全一致；持久身份只用 path/basename/size/SHA-256 作权威判定，`device/inode` 只作诊断；
- v2 SNR identity diagnostic 必须同时为 `mixed_rows=9000`、`clean_rows=1000`、`exact_mismatch_count=56`、`max_abs=8.881784197001252e-16`、`rtol=0`、`atol=1e-12`，且 `max_abs <= atol`；任一值不同都必须 STOP，不得执行 `freeze-inputs`；
- SNR 分层为冻结 bank 内的五档，干扰者数为 1–4；
- epoch33 和 formal-final 是普通文件、不是 symlink，并且 epoch/global_step 正确；
- 作者 checkpoint 的 profile 明确标记 external，不声称同分布可比；
- `COMPLETE_RECOVERY.json` 的工具/日志/checkpoint/原始 loop counter 证据可重算；
- 用途字段精确为 `$ANALYSIS_STATUS`，模型角色字段精确为 `$MODEL_ROLES`。

`AUDIT_INPUTS_GATE` 只对当前 shell 会话有效。如果在人工审阅期间断线，重新执行第 2 节和本节的只读 `audit-inputs`；不得手工把 gate 变量设为 0。

## 4. `freeze-inputs`：唯一的输入发布

`freeze-inputs` 是显式写操作，它一次性初始化冻结 manifest、`logs/`、`state/evaluation.lock`、`attempts/{smoke,audit}/` 和 `submitted_runners/`，并对任何已有冻结目标拒绝覆盖。因此在 freeze 之前不要手工创建这些目录。

```bash
"$PYTHON" "$TOOL" freeze-inputs --help
FREEZE_INPUTS_GATE=2
if [ "${AUDIT_INPUTS_GATE:-2}" -eq 0 ] \
  && verify_reviewed_static_inputs \
  && verify_external_root_boundary; then
  if "$PYTHON" "$TOOL" freeze-inputs \
    --project-root "$PROJECT_ROOT" \
    --run-root "$RUN_ROOT" \
    --external-root "$EVAL_ROOT" \
    --recovery-tool "$RECOVERY_TOOL" \
    --sbatch "$RUNNER" \
    --expected-valbest-sha256 "$EXPECTED_VALBEST_SHA256" \
    --manifest "$EVAL_ROOT/input_freeze.json"; then
    FREEZE_INPUTS_GATE=0
  fi
fi
if [ "$FREEZE_INPUTS_GATE" -ne 0 ]; then
  echo "STOP: freeze prerequisites or freeze-inputs failed" >&2
fi
test "$FREEZE_INPUTS_GATE" -eq 0
```

此时暂停，审阅 freeze 输出的所有路径、哈希和语义字段。审阅通过后，把 freeze 打印的 manifest SHA 作为一个新的人工批准常量填入下面的占位符。不能现场从同一文件计算出“expected”再让文件自证：

这个 freeze 后的人工门禁还必须确认 `evaluation.lock` 是上述六字段 canonical JSON，`external_root` 必须精确等于 v4 根，`lock_nonce` 是新生成的 64 位 lowercase hex。`audit-inputs` 时 lock 尚不存在；不得在 freeze 前手工创建它。

```bash
MANIFEST="$EVAL_ROOT/input_freeze.json"
EXPECTED_MANIFEST_SHA256="<paste-human-reviewed-freeze-sha256-here>"

verify_reviewed_manifest () {
  case "$EXPECTED_MANIFEST_SHA256" in
    *[!0-9a-f]*|'') echo "STOP: fill the reviewed manifest SHA-256"; return 2 ;;
  esac
  test "${#EXPECTED_MANIFEST_SHA256}" -eq 64 \
    || { echo "STOP: reviewed manifest SHA-256 must have 64 characters"; return 2; }
  MANIFEST_HASH_LINE=$(/usr/bin/sha256sum "$MANIFEST") || return 2
  ACTUAL_MANIFEST_SHA256=${MANIFEST_HASH_LINE%% *}
  test "$ACTUAL_MANIFEST_SHA256" = "$EXPECTED_MANIFEST_SHA256" \
    || { echo "STOP: frozen manifest differs from the reviewed SHA-256"; return 2; }
}
MANIFEST_REVIEW_GATE=2
if verify_reviewed_static_inputs \
  && verify_external_root_boundary \
  && verify_reviewed_manifest; then
  MANIFEST_REVIEW_GATE=0
  echo "MANIFEST REVIEW GATE: PASS"
else
  echo "STOP: manifest review gate failed" >&2
fi
test "$MANIFEST_REVIEW_GATE" -eq 0
```

freeze 成功后如果断线，禁止重跑 `freeze-inputs`。重连后重新执行第 2 节，重新填入人工审定的 `MANIFEST` / `EXPECTED_MANIFEST_SHA256`，然后只读重跑上面的 `verify_reviewed_manifest` gate 即可恢复。

Slurm 在作业启动前就要打开日志路径。这些目录应已由 freeze 一次性创建；此处只检查，不用 `mkdir -p` 隐藏不完整的 freeze：

```bash
test -d "$EVAL_ROOT/logs" \
  && test -d "$EVAL_ROOT/submitted_runners" \
  && test -d "$EVAL_ROOT/attempts/smoke" \
  && test -d "$EVAL_ROOT/attempts/audit" \
  || { echo "STOP: freeze layout is incomplete"; false; }
```

## 5. `check-only`：零写入复核

先记录目录状态，运行 check-only，再比较。它不应创建 `state/evaluation.lock`、`__pycache__` 或 attempt。

```bash
"$PYTHON" "$TOOL" check-only --help
LOGIN_CHECK_ONLY_GATE=2
if [ "${MANIFEST_REVIEW_GATE:-2}" -eq 0 ] \
  && verify_reviewed_static_inputs \
  && verify_external_root_boundary \
  && verify_reviewed_manifest; then
  if "$PYTHON" "$TOOL" check-only \
    --external-root "$EVAL_ROOT" \
    --manifest "$MANIFEST" \
    --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"; then
    LOGIN_CHECK_ONLY_GATE=0
  fi
fi
if [ "$LOGIN_CHECK_ONLY_GATE" -ne 0 ]; then
  echo "STOP: login-node check-only gate failed" >&2
fi
test "$LOGIN_CHECK_ONLY_GATE" -eq 0
```

只有命令退出码为 0，且 JSON 输出为 `"status": "CHECK_PASS"` 才能继续。如果失败，不要手工改 manifest 或结果 marker；查明原因后创建新的版本化外部根。

### 5.1 计算节点零写入 `check-only`

v4 继续使用跨节点 NFS 身份语义，所以登录节点通过还不够。在 smoke 之前，必须先从 Slurm compute 节点直接运行一次不建 attempt、不归档 runner/environment 的 `check-only`。下面整块是一个门禁：不要开启 `set -e`，每一步的退出码都会被显式保存，以免断线或首个失败遮蔽后续取证。先在登录节点记录 v4 根的 path/type/mode/size/mtime/device/inode/symlink-target 元数据和全部普通文件内容哈希：

```bash
COMPUTE_PREREQUISITE_GATE=2
if [ "${LOGIN_CHECK_ONLY_GATE:-2}" -eq 0 ] \
  && verify_reviewed_static_inputs \
  && verify_external_root_boundary \
  && verify_reviewed_manifest; then
  COMPUTE_PREREQUISITE_GATE=0
else
  echo "STOP: compute check-only prerequisites failed" >&2
fi

v4_tree_identity_sha () {
  (
    set -o pipefail
    cd "$EVAL_ROOT" || return 2
    /usr/bin/find . -xdev \
      -printf '%P\t%y\t%m\t%s\t%T@\t%D\t%i\t%l\0' \
      | LC_ALL=C /usr/bin/sort -z \
      | /usr/bin/sha256sum \
      | /usr/bin/awk '{print $1}'
  )
}

v4_file_content_sha () {
  (
    set -o pipefail
    cd "$EVAL_ROOT" || return 2
    /usr/bin/find . -xdev -type f -print0 \
      | LC_ALL=C /usr/bin/sort -z \
      | /usr/bin/xargs -0 -r /usr/bin/sha256sum \
      | /usr/bin/sha256sum \
      | /usr/bin/awk '{print $1}'
  )
}

V4_TREE_IDENTITY_BEFORE=$(v4_tree_identity_sha)
V4_TREE_IDENTITY_BEFORE_RC=$?
V4_FILE_CONTENT_BEFORE=$(v4_file_content_sha)
V4_FILE_CONTENT_BEFORE_RC=$?
```

然后提交一个短 compute allocation；`env -i` 阻断登录 shell 的 Python/Conda/loader 注入，stdout 只保留在当前 shell 变量中，不写入 v4 根。`RUN_COMPUTE_GATE` 只在 prerequisites 和两个运行前指纹都成功后才变为 0；否则下面明确不调用 `srun`。`check-only` 的三次 strict model load 可能在最终 JSON 前保留初始化诊断行，因此 parser 只接受唯一一个占满 stdout 后缀的顶层 JSON object，并同时复核顶层与 `verification` 内的 identity policy：

```bash
RUN_COMPUTE_GATE=2
if [ "$COMPUTE_PREREQUISITE_GATE" -eq 0 ] \
  && [ "$V4_TREE_IDENTITY_BEFORE_RC" -eq 0 ] \
  && [ "$V4_FILE_CONTENT_BEFORE_RC" -eq 0 ] \
  && [ -n "$V4_TREE_IDENTITY_BEFORE" ] \
  && [ -n "$V4_FILE_CONTENT_BEFORE" ]; then
  RUN_COMPUTE_GATE=0
fi

COMPUTE_CHECK_JSON=""
COMPUTE_CHECK_RC=99
if [ "$RUN_COMPUTE_GATE" -eq 0 ]; then
  COMPUTE_CHECK_JSON=$(srun \
    -p GPU-1A -N 1 -G 1 --ntasks=1 --cpus-per-task=8 -t 01:00:00 \
    /usr/bin/env -i \
      HOME="$HOME" \
      PATH="$HOME/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin" \
      PYTHONNOUSERSITE=1 \
      PYTHONDONTWRITEBYTECODE=1 \
      PYTHONHASHSEED=0 \
      CV_CLIPS="$PROJECT_ROOT/cv_train/clips" \
      "$PYTHON" -I "$TOOL" check-only \
        --external-root "$EVAL_ROOT" \
        --manifest "$MANIFEST" \
        --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
  )
  COMPUTE_CHECK_RC=$?
else
  echo "STOP: compute preflight failed; srun was not invoked" >&2
fi

COMPUTE_JSON_PARSER_OUTPUT=""
COMPUTE_JSON_PARSER_RC=99
if [ "$COMPUTE_CHECK_RC" -eq 0 ]; then
  COMPUTE_JSON_PARSER_OUTPUT=$(printf '%s\n' "$COMPUTE_CHECK_JSON" | "$PYTHON" -I -c '
import json, re, sys
raw = sys.stdin.read()
decoder = json.JSONDecoder()
candidates = []
for match in re.finditer(r"(?m)^\{", raw):
    try:
        candidate, end = decoder.raw_decode(raw[match.start():])
    except json.JSONDecodeError:
        continue
    if not raw[match.start() + end:].strip() and isinstance(candidate, dict):
        candidates.append(candidate)
if len(candidates) != 1:
    raise SystemExit("STOP: expected exactly one trailing compute JSON object")
value = candidates[0]
if value.get("status") != "CHECK_PASS":
    raise SystemExit("STOP: compute check-only did not pass")
if value.get("protocol_id") != "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1":
    raise SystemExit("STOP: compute protocol mismatch")
policy = "cross_invocation_path_size_sha_exact__dev_inode_diagnostic"
if value.get("filesystem_identity_policy") != policy:
    raise SystemExit("STOP: compute filesystem policy mismatch")
verification = value.get("verification")
if not isinstance(verification, dict):
    raise SystemExit("STOP: compute verification object is missing")
if verification.get("filesystem_identity_policy") != policy:
    raise SystemExit("STOP: compute verification filesystem policy mismatch")
if verification.get("verified_files") != 24:
    raise SystemExit("STOP: compute check-only did not verify exactly 24 files")
print("COMPUTE JSON: CHECK_PASS; verified_files=24")
')
  COMPUTE_JSON_PARSER_RC=$?
fi

V4_TREE_IDENTITY_AFTER=$(v4_tree_identity_sha)
V4_TREE_IDENTITY_AFTER_RC=$?
V4_FILE_CONTENT_AFTER=$(v4_file_content_sha)
V4_FILE_CONTENT_AFTER_RC=$?

COMPUTE_ZERO_WRITE_GATE=2
if [ "$COMPUTE_PREREQUISITE_GATE" -eq 0 ] \
  && [ "$RUN_COMPUTE_GATE" -eq 0 ] \
  && [ "$V4_TREE_IDENTITY_BEFORE_RC" -eq 0 ] \
  && [ "$V4_FILE_CONTENT_BEFORE_RC" -eq 0 ] \
  && [ "$COMPUTE_CHECK_RC" -eq 0 ] \
  && [ "$COMPUTE_JSON_PARSER_RC" -eq 0 ] \
  && [ "$V4_TREE_IDENTITY_AFTER_RC" -eq 0 ] \
  && [ "$V4_FILE_CONTENT_AFTER_RC" -eq 0 ] \
  && [ -n "$V4_TREE_IDENTITY_BEFORE" ] \
  && [ -n "$V4_FILE_CONTENT_BEFORE" ] \
  && [ "$V4_TREE_IDENTITY_AFTER" = "$V4_TREE_IDENTITY_BEFORE" ] \
  && [ "$V4_FILE_CONTENT_AFTER" = "$V4_FILE_CONTENT_BEFORE" ]; then
  COMPUTE_ZERO_WRITE_GATE=0
fi

# 完整 JSON 先回显到当前终端，保留 24 条 frozen/current
# device+inode 跨节点 diagnostics；不将它写入 v4 根。
printf '%s\n' "$COMPUTE_CHECK_JSON"
printf '%s\n' "$COMPUTE_JSON_PARSER_OUTPUT"
printf 'fingerprint_rc: identity_before=%s content_before=%s identity_after=%s content_after=%s\n' \
  "$V4_TREE_IDENTITY_BEFORE_RC" "$V4_FILE_CONTENT_BEFORE_RC" \
  "$V4_TREE_IDENTITY_AFTER_RC" "$V4_FILE_CONTENT_AFTER_RC"
printf 'compute_rc=%s parser_rc=%s\n' "$COMPUTE_CHECK_RC" "$COMPUTE_JSON_PARSER_RC"

if [ "$COMPUTE_ZERO_WRITE_GATE" -eq 0 ]; then
  echo "COMPUTE CHECK-ONLY ZERO-WRITE GATE: PASS"
else
  echo "STOP: compute check-only failed or changed the v4 tree; do not submit smoke" >&2
fi
test "$COMPUTE_ZERO_WRITE_GATE" -eq 0
```

只有最后显示 `COMPUTE CHECK-ONLY ZERO-WRITE GATE: PASS` 且最后的 `test` 返回 0，才能提交 smoke。也就是：compute 命令与 JSON parser 均返回 0、JSON 为 `CHECK_PASS`、恰好验证 24 个文件、四个指纹命令都成功，而且登录节点的元数据指纹和内容指纹前后完全相同。compute 节点与登录节点的 `device/inode` 可在 diagnostics 中不同；这里纳入 device/inode 的是同一登录节点上运行前后的零写检查。任何一项返回码非 0、指纹为空或前后不同，都会显示 `STOP`；此时明确禁止继续执行第 6 节。

第 5.1 节到第 6 节必须保持同一 shell，因为 smoke 提交会检查本会话的 `COMPUTE_ZERO_WRITE_GATE`。如果断线，不得手工设它为 0；重连后重跑第 2 节、manifest 只读复核和第 5 至 5.1 节。

## 6. 提交 smoke

Slurm 在读取 `#SBATCH --output` 时日志目录必须已经存在；它和 `submitted_runners/` 都由已完成的 freeze 创建，不是 `check-only` 的副作用。runner 只会以真正的 exclusive/atomic 语义创建 `${SLURM_JOB_ID}.sbatch` 和 `${SLURM_JOB_ID}.environment.json`，绝不覆盖。后者是 canonical JSON 加一个换行；evaluator 必须按路径和实际文件 SHA 重新读取并绑定，不能只信任日志里打印的 digest。下面还会拒绝已存在的 active `audattn_samebank_v4` 作业，并用当前 shell 的 `SMOKE_SUBMISSION_ATTEMPTED` 防止同一区块被重复粘贴提交。一旦已经调用 `sbatch`，不要在当前 shell 中手工把该变量改回 0。

```bash
SMOKE_SUBMISSION_ATTEMPTED=${SMOKE_SUBMISSION_ATTEMPTED:-0}
ACTIVE_V4_JOB=$(squeue -h -u "$USER" -n audattn_samebank_v4 -o '%A|%T|%j')
SMOKE_SQUEUE_RC=$?
SMOKE_SUBMISSION_GATE=2
if [ "${COMPUTE_ZERO_WRITE_GATE:-2}" -eq 0 ] \
  && [ "$SMOKE_SQUEUE_RC" -eq 0 ] \
  && [ -z "$ACTIVE_V4_JOB" ] \
  && [ "$SMOKE_SUBMISSION_ATTEMPTED" = 0 ] \
  && verify_reviewed_static_inputs \
  && verify_external_root_boundary \
  && verify_reviewed_manifest \
  && test -d "$EVAL_ROOT/logs" \
  && test -d "$EVAL_ROOT/submitted_runners" \
  && test ! -e "$EVAL_ROOT/state/SMOKE_PASS.json" \
  && test ! -L "$EVAL_ROOT/state/SMOKE_PASS.json"; then
  SMOKE_SUBMISSION_ATTEMPTED=1
  if SMOKE_JOB_RAW=$(sbatch --parsable \
    --export=EVAL_ACTION=smoke,EXTERNAL_ROOT="$EVAL_ROOT",INPUT_MANIFEST="$MANIFEST",EXPECTED_MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" \
    "$RUNNER"); then
    SMOKE_JOB=${SMOKE_JOB_RAW%%;*}
    case "$SMOKE_JOB" in
      *[!0-9]*|'') echo "STOP: sbatch returned an invalid smoke Job ID" >&2 ;;
      *) SMOKE_SUBMISSION_GATE=0; printf 'SMOKE_JOB=%s\n' "$SMOKE_JOB" ;;
    esac
  fi
fi
if [ "$SMOKE_SUBMISSION_GATE" -ne 0 ]; then
  printf 'ACTIVE_V4_JOB=%s\n' "$ACTIVE_V4_JOB" >&2
  echo "STOP: same-session compute gate or smoke submission prerequisites failed" >&2
fi
test "$SMOKE_SUBMISSION_GATE" -eq 0
```

smoke 只做小样本工程验证（包括可重现性/绑定），不产生科学结论。查询：

```bash
squeue -j "$SMOKE_JOB"
sacct -j "$SMOKE_JOB" -X --format=JobID,State,ExitCode,Elapsed,Start,End,NodeList
tail -n 120 "$EVAL_ROOT/logs/audattn_samebank_v4_${SMOKE_JOB}.log"
"$PYTHON" "$TOOL" check-only \
  --external-root "$EVAL_ROOT" \
  --manifest "$MANIFEST" \
  --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

需要同时满足 Slurm `COMPLETED 0:0`、日志无 traceback，且 `$EVAL_ROOT/state/SMOKE_PASS.json` 可被 `check-only` 重算验证。

## 7. 提交完整 10k audit

完整 audit 与 smoke 使用同样的双重防重复门禁：先拒绝任何 active `audattn_samebank_v4` 作业，再用当前 shell 的 `AUDIT_SUBMISSION_ATTEMPTED` 保证该提交区块只能调用一次 `sbatch`。已有正式发布 marker 时也会拒绝第二次提交。

```bash
AUDIT_SUBMISSION_ATTEMPTED=${AUDIT_SUBMISSION_ATTEMPTED:-0}
ACTIVE_V4_JOB=$(squeue -h -u "$USER" -n audattn_samebank_v4 -o '%A|%T|%j')
AUDIT_SQUEUE_RC=$?
AUDIT_SUBMISSION_GATE=2
if [ "$AUDIT_SQUEUE_RC" -eq 0 ] \
  && [ -z "$ACTIVE_V4_JOB" ] \
  && [ "$AUDIT_SUBMISSION_ATTEMPTED" = 0 ] \
  && verify_reviewed_static_inputs \
  && verify_external_root_boundary \
  && verify_reviewed_manifest \
  && test -f "$EVAL_ROOT/state/SMOKE_PASS.json" \
  && test ! -L "$EVAL_ROOT/state/SMOKE_PASS.json" \
  && test ! -e "$EVAL_ROOT/state/SAME_BANK_AUDIT_PUBLISHED.json" \
  && test ! -L "$EVAL_ROOT/state/SAME_BANK_AUDIT_PUBLISHED.json" \
  && "$PYTHON" "$TOOL" check-only \
    --external-root "$EVAL_ROOT" \
    --manifest "$MANIFEST" \
    --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"; then
  AUDIT_SUBMISSION_ATTEMPTED=1
  if AUDIT_JOB_RAW=$(sbatch --parsable \
    --export=EVAL_ACTION=run-audit,EXTERNAL_ROOT="$EVAL_ROOT",INPUT_MANIFEST="$MANIFEST",EXPECTED_MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" \
    "$RUNNER"); then
    AUDIT_JOB=${AUDIT_JOB_RAW%%;*}
    case "$AUDIT_JOB" in
      *[!0-9]*|'') echo "STOP: sbatch returned an invalid audit Job ID" >&2 ;;
      *) AUDIT_SUBMISSION_GATE=0; printf 'AUDIT_JOB=%s\n' "$AUDIT_JOB" ;;
    esac
  fi
fi
if [ "$AUDIT_SUBMISSION_GATE" -ne 0 ]; then
  printf 'ACTIVE_V4_JOB=%s\n' "$ACTIVE_V4_JOB" >&2
  echo "STOP: verified smoke or full-audit submission prerequisites failed" >&2
fi
test "$AUDIT_SUBMISSION_GATE" -eq 0
```

`run-audit` 必须重新验证 `SMOKE_PASS.json`、manifest 及所有输入，并全程持有 NFS 锁。查询方式：

```bash
squeue -j "$AUDIT_JOB"
sacct -j "$AUDIT_JOB" -X --format=JobID,State,ExitCode,Elapsed,Start,End,NodeList
tail -n 160 "$EVAL_ROOT/logs/audattn_samebank_v4_${AUDIT_JOB}.log"
"$PYTHON" "$TOOL" check-only \
  --external-root "$EVAL_ROOT" \
  --manifest "$MANIFEST" \
  --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

只有当 Slurm 为 `COMPLETED 0:0`，且完整 audit 发布 marker 经 `check-only` 验证通过，才读取结果。不要根据进度日志或 partial CSV 提前报告数值。

## 失败与重跑规则

| 情况 | 处理 |
|---|---|
| `audit-inputs` / `check-only` 失败 | 保持全部输入不变，先定位哪个 hash/语义绑定失配 |
| `freeze-inputs` 发现目标已存在 | 不删除、不覆盖；先用 `check-only` 判断它是否是已冻结的同一版本 |
| smoke 作业失败 | 保留 `attempts/smoke/slurm-<job>/` 为证据；只有不改变已冻结 evaluator/runner/协议的瞬时故障才可用新 Job ID 从头跑，如需修改已冻结工具则保留 v4 并新建 v5 |
| full audit 作业失败 | 保留 `attempts/audit/slurm-<job>/` 中的 partial/`FAILED.json`，不拼接/续跑；新 Job ID 从头跑 |
| 已有完整发布 marker | 仅允许重新校验和读取，拒绝第二次发布 |
| 锁已被占用 | 不删锁文件。先用 `squeue`/`sacct` 确认持有者，等待或调查 |

## 结果解释顺序

1. 主要：每个模型内部的 SNR 趋势和干扰者数趋势，并报告冻结样本数/不确定性。
2. 次要：formal-final 与 epoch33 在同 bank 上的配对差值。epoch33 已用 validation 选择，所以这不是无偏的最终泛化估计。
3. 描述性：作者 checkpoint 在我们难度坐标上的 profile。只说曲线/退化形态，不说总 accuracy 高低代表模型优劣。
4. 真正的最终泛化结论留给从未参与训练、checkpoint 选择、pilot 或调参的独立 test bank。

## CLI 对齐清单

`locked_same_bank_eval.py` 合入后，在上传前核对以下合同。如果 CLI 参数名不同，应该修改本 runner 和 README，不能在超算上临时猜参数。

- 子命令：`audit-inputs`、`freeze-inputs`、`check-only`、`smoke`、`run-audit`。
- `audit-inputs` / `freeze-inputs` 公共参数：`--project-root`、`--run-root`、`--external-root`、`--recovery-tool`、`--sbatch`、`--expected-valbest-sha256`；`freeze-inputs` 另有 `--manifest`。
- `check-only` 参数：`--external-root`、`--manifest`、`--expected-manifest-sha256`。
- GPU 命令参数：`--external-root`、`--manifest`、`--expected-manifest-sha256`、`--attempt-id`、`--job-id`、`--submitted-runner`、`--submitted-runner-sha256`、`--environment-fingerprint`、`--environment-fingerprint-sha256`、`--confirm-role formal40-primary__valbest33-secondary__author-external`；只在必要的本地调试中可加 `--allow-cpu`。
- 工具自己负责 NFS 锁、attempt 状态、原子发布和拒绝覆盖；runner 不另取第二把同名锁。
- `check-only` 使用延迟 `torch` 导入，并且在任何路径不存在时只报错、不创建它。
- `sbatch --export` 只列出四个必需变量，不使用 `ALL`，也不使用 Slurm 不允许的 `NONE,显式变量` 组合。runner 在首个外部命令前清理 Python/Conda/loader 注入变量，使用绝对解释器和 SHA 命令，并将环境 fingerprint 的原始 canonical JSON 与 SHA 一起绑入 attempt/published marker。
- runner 在执行 evaluator 前独立读取人工审定 SHA 对应的 manifest，校验冻结 sbatch/evaluator 的 canonical path、size 和 SHA；一旦 freeze，不得再编辑这两个文件。
- runner 的独立 trust bootstrap 还必须硬校验顶层 `protocol_id=fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1` 和 `filesystem_identity_policy=cross_invocation_path_size_sha_exact__dev_inode_diagnostic`；不可只相信 evaluator 自我声明。
