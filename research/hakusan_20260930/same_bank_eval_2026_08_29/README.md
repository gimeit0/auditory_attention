# 同一冻结 bank 的项目外评估（2026-08-29）

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

- 工具、manifest、日志和结果都放在项目外的 `$HOME/audattn_external_eval/same_bank_2026-08-29`。不向 live project 或训练 run snapshot 写入文件。
- 旧 `PILOT4_BANK_FROZEN.json` 和 `frozen_bank.tsv` 只读引用；本工具不冒充它们原先的 freeze 绑定。
- `freeze-inputs` 是唯一创建冻结输入和锁文件的步骤，而且拒绝覆盖。
- `check-only` 绝对不得创建目录、`state/evaluation.lock` 或任何状态。
- `smoke` 和 `run-audit` 由 Python 工具全程持有同一把 NFS 可见锁。每次 Slurm 作业创建唯一 attempt，既不覆盖，也不续跑中途失败的 attempt。
- 只有完整校验后原子发布的 marker 是权威结果。`RUNNING`/`FAILED` attempt 中的临时 CSV 不可用于结论。
- 不提供 `--force`、覆盖或从 partial output 恢复的通道。重跑必须用新 Job ID / 新 attempt，从第 0 条题开始。

## 外部目录

`freeze-inputs` 成功并完成提交前的输出目录准备后，应有如下结构：

```text
$HOME/audattn_external_eval/same_bank_2026-08-29/
├── input_freeze.json
├── logs/
├── state/
│   ├── evaluation.lock
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

## 1. 上传工具（不上传到项目中）

上传本身也是 one-shot 发布。不能用 `mkdir -p .../tools` 或直接 `scp` 到最终文件名：那会复用旧的日期目录，并可能覆盖已被 manifest 绑定的工具。

先在 Mac 上校验本地待上传文件：

```bash
LOCAL_DIR="/Users/gigi/发表/超算/same_bank_eval_2026_08_29"
EXPECTED_EVALUATOR_SHA256="221096ef601e63ddc5e0a14833b687c810d36095b2c6bc2d66f380ab90bf0040"
EXPECTED_RUNNER_SHA256="3d35b416b4ece19459742d74e83cb3268d732cf25006c3f539878b5407affa21"

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
  EVAL_ROOT="$BASE/same_bank_2026-08-29"
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
    s2510040@hakusan1:audattn_external_eval/same_bank_2026-08-29/.upload-staging/
```

最后在远端先按人工审定 SHA 校验 staging，再用 hard link 的 no-overwrite 语义发布到 `tools/`，重新校验最终名后才清理 staging：

```bash
ssh s2510040@hakusan1 '
  set -eu
  EVAL_ROOT="$HOME/audattn_external_eval/same_bank_2026-08-29"
  STAGING="$EVAL_ROOT/.upload-staging"
  EVALUATOR_SHA="221096ef601e63ddc5e0a14833b687c810d36095b2c6bc2d66f380ab90bf0040"
  RUNNER_SHA="3d35b416b4ece19459742d74e83cb3268d732cf25006c3f539878b5407affa21"
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
EVAL_ROOT="$HOME/audattn_external_eval/same_bank_2026-08-29"
TOOL="$EVAL_ROOT/tools/locked_same_bank_eval.py"
RUNNER="$EVAL_ROOT/tools/run_locked_same_bank_eval.sbatch"
PYTHON="$HOME/miniconda3/envs/attn/bin/python"
ANALYSIS_STATUS="REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
MODEL_ROLES="formal40-primary__valbest33-secondary__author-external"
RECOVERY_TOOL="$HOME/audattn_recovery/2026-08-28/recover_full_completion_2026_08_28.py"
EXPECTED_RECOVERY_TOOL_SHA256="f7b682f61920d21d181a4721a32e87d4dc216d07df3d476392ee2de41f967959"
VALBEST_CHECKPOINT="$RUN_ROOT/full/checkpoints/epoch=33-step=59024.ckpt"
EXPECTED_VALBEST_SHA256="853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14"

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
verify_reviewed_static_inputs || false
```

先检查它与项目路径无包含关系：

```bash
case "$EVAL_ROOT/" in
  "$PROJECT_ROOT/"* ) echo "STOP: EVAL_ROOT is inside project"; false ;;
esac
```

任何一个上述命令输出 `STOP` 或返回非 0 时，不要继续复制后续命令。

## 3. `audit-inputs`：只读发现

以下参数是本目录的 CLI 合同；正式运行前先用 `--help` 核对实现版本。

```bash
"$PYTHON" "$TOOL" audit-inputs --help
"$PYTHON" "$TOOL" audit-inputs \
  --project-root "$PROJECT_ROOT" \
  --run-root "$RUN_ROOT" \
  --external-root "$EVAL_ROOT" \
  --recovery-tool "$RECOVERY_TOOL" \
  --sbatch "$RUNNER" \
  --expected-valbest-sha256 "$EXPECTED_VALBEST_SHA256"
```

`audit-inputs` 只在 stdout 打印 candidate 和 SHA；不应建目录或锁。人工检查下列项目后再 freeze：

- bank 是该 run 的 `evaluation/pilot4/frozen_bank.tsv`，而不是重新随机生成的样本；
- SNR 分层为冻结 bank 内的五档，干扰者数为 1–4；
- epoch33 和 formal-final 是普通文件、不是 symlink，并且 epoch/global_step 正确；
- 作者 checkpoint 的 profile 明确标记 external，不声称同分布可比；
- `COMPLETE_RECOVERY.json` 的工具/日志/checkpoint/原始 loop counter 证据可重算；
- 用途字段精确为 `$ANALYSIS_STATUS`，模型角色字段精确为 `$MODEL_ROLES`。

## 4. `freeze-inputs`：唯一的输入发布

`freeze-inputs` 是显式写操作，它一次性初始化冻结 manifest、`logs/`、`state/evaluation.lock`、`attempts/{smoke,audit}/` 和 `submitted_runners/`，并对任何已有冻结目标拒绝覆盖。因此在 freeze 之前不要手工创建这些目录。

```bash
"$PYTHON" "$TOOL" freeze-inputs --help
"$PYTHON" "$TOOL" freeze-inputs \
  --project-root "$PROJECT_ROOT" \
  --run-root "$RUN_ROOT" \
  --external-root "$EVAL_ROOT" \
  --recovery-tool "$RECOVERY_TOOL" \
  --sbatch "$RUNNER" \
  --expected-valbest-sha256 "$EXPECTED_VALBEST_SHA256" \
  --manifest "$EVAL_ROOT/input_freeze.json"
```

此时暂停，审阅 freeze 输出的所有路径、哈希和语义字段。审阅通过后，把 freeze 打印的 manifest SHA 作为一个新的人工批准常量填入下面的占位符。不能现场从同一文件计算出“expected”再让文件自证：

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
verify_reviewed_manifest || false
```

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
"$PYTHON" "$TOOL" check-only \
  --external-root "$EVAL_ROOT" \
  --manifest "$MANIFEST" \
  --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

只有命令退出码为 0，且 JSON 输出为 `"status": "CHECK_PASS"` 才能继续。如果失败，不要手工改 manifest 或结果 marker；查明原因后创建新的版本化外部根。

## 6. 提交 smoke

Slurm 在读取 `#SBATCH --output` 时日志目录必须已经存在；它和 `submitted_runners/` 都由已完成的 freeze 创建，不是 `check-only` 的副作用。runner 只会以真正的 exclusive/atomic 语义创建 `${SLURM_JOB_ID}.sbatch` 和 `${SLURM_JOB_ID}.environment.json`，绝不覆盖。后者是 canonical JSON 加一个换行；evaluator 必须按路径和实际文件 SHA 重新读取并绑定，不能只信任日志里打印的 digest。

```bash
test -d "$EVAL_ROOT/logs" || { echo "STOP: submission preparation is incomplete"; false; }

SMOKE_JOB=$(sbatch --parsable \
  --export=EVAL_ACTION=smoke,EXTERNAL_ROOT="$EVAL_ROOT",INPUT_MANIFEST="$MANIFEST",EXPECTED_MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" \
  "$RUNNER")
printf 'SMOKE_JOB=%s\n' "$SMOKE_JOB"
```

smoke 只做小样本工程验证（包括可重现性/绑定），不产生科学结论。查询：

```bash
squeue -j "$SMOKE_JOB"
sacct -j "$SMOKE_JOB" -X --format=JobID,State,ExitCode,Elapsed,Start,End,NodeList
tail -n 120 "$EVAL_ROOT/logs/audattn_samebank_${SMOKE_JOB}.log"
"$PYTHON" "$TOOL" check-only \
  --external-root "$EVAL_ROOT" \
  --manifest "$MANIFEST" \
  --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
```

需要同时满足 Slurm `COMPLETED 0:0`、日志无 traceback，且 `$EVAL_ROOT/state/SMOKE_PASS.json` 可被 `check-only` 重算验证。

## 7. 提交完整 10k audit

```bash
AUDIT_JOB=$(sbatch --parsable \
  --export=EVAL_ACTION=run-audit,EXTERNAL_ROOT="$EVAL_ROOT",INPUT_MANIFEST="$MANIFEST",EXPECTED_MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" \
  "$RUNNER")
printf 'AUDIT_JOB=%s\n' "$AUDIT_JOB"
```

`run-audit` 必须重新验证 `SMOKE_PASS.json`、manifest 及所有输入，并全程持有 NFS 锁。查询方式：

```bash
squeue -j "$AUDIT_JOB"
sacct -j "$AUDIT_JOB" -X --format=JobID,State,ExitCode,Elapsed,Start,End,NodeList
tail -n 160 "$EVAL_ROOT/logs/audattn_samebank_${AUDIT_JOB}.log"
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
| smoke 作业失败 | 保留 `attempts/smoke/slurm-<job>/` 为证据，修正原因后用新 Job ID 从头跑 |
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
