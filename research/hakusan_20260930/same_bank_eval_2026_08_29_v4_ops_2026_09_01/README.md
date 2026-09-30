# v4 smoke 恢复工具（2026-09-01）

本目录是冻结 v4 评估包之外的操作工具，不是科学 evaluator 的一部分。它解决交互式 tmux/bash 大段粘贴造成的变量丢失和 parser gate 假失败：在单个 Python 进程中重新执行登录节点 `check-only`、计算节点 `check-only`、前后零写指纹，并且只在所有门禁通过时提交一个 smoke。

冻结根保持为：

```text
/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4
```

本工具只允许安装到：

```text
/home/s2510040/audattn_external_eval_ops/same_bank_v4_2026-09-01
```

操作状态（锁、提交 intent、提交 receipt）写在上述 ops 目录的 `resume_state/`，绝不写入冻结 v4 根。正常路径恰好调用一次 `sbatch`；任何 `sbatch` 超时、断线、异常或非法返回都会留下 unresolved intent，此后自动拒绝重投。

**防重复提交硬约束：从开始本恢复流程到 smoke 状态核实完成，`resume_v4_smoke.py` 是唯一允许的提交入口。禁止再执行 v4 原 README 中的手工 `sbatch`，禁止在其他 SSH/tmux 窗口并发提交，也禁止与其他脚本同时提交 `audattn_samebank_v4`。**

## 审定文件

```text
resume_v4_smoke.py  245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4
test_resume_v4_smoke.py  ae4639191a2c355946c8af584470bf0ead0089fabd2bc7fd92bddce26e6fe042
```

测试状态：28/28 `unittest` 通过，Ruff check 与 Ruff format check 通过。测试覆盖真实前导诊断行、空/截断/重复/非有限 JSON、嵌套对象、语义突变、非零命令退出、登录/计算零写指纹、active job、既有 evidence、持久 intent/receipt、异常提交、receipt 写失败以及跨进程并发锁。

## 1. Mac 本地复核并上传

以下整块只在 Mac 终端执行：

```bash
(
  set -eu
  LOCAL_DIR="$HOME/发表/超算/same_bank_eval_2026_08_29_v4_ops_2026_09_01"
  HELPER_SHA="245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4"
  TEST_SHA="ae4639191a2c355946c8af584470bf0ead0089fabd2bc7fd92bddce26e6fe042"

  cd "$LOCAL_DIR"
  printf '%s  %s\n' "$HELPER_SHA" resume_v4_smoke.py |
    /usr/bin/shasum -a 256 -c -
  printf '%s  %s\n' "$TEST_SHA" test_resume_v4_smoke.py |
    /usr/bin/shasum -a 256 -c -
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_resume_v4_smoke.py

  ssh s2510040@hakusan1 '
    set -eu
    BASE="$HOME/audattn_external_eval_ops"
    ROOT="$BASE/same_bank_v4_2026-09-01"
    test ! -L "$BASE" || exit 2
    if [ ! -e "$BASE" ]; then mkdir "$BASE"; fi
    test -d "$BASE" || exit 2
    test ! -e "$ROOT" && test ! -L "$ROOT" || {
      echo "STOP: reviewed v4 ops root already exists" >&2
      exit 2
    }
    mkdir "$ROOT"
    mkdir "$ROOT/.upload-staging"
  '

  scp resume_v4_smoke.py \
    s2510040@hakusan1:audattn_external_eval_ops/same_bank_v4_2026-09-01/.upload-staging/

  ssh s2510040@hakusan1 '
    set -eu
    ROOT="$HOME/audattn_external_eval_ops/same_bank_v4_2026-09-01"
    STAGE="$ROOT/.upload-staging"
    SHA="245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4"
    test -d "$STAGE" && test ! -L "$STAGE"
    test ! -e "$ROOT/resume_v4_smoke.py"
    printf "%s  %s\n" "$SHA" "$STAGE/resume_v4_smoke.py" |
      /usr/bin/sha256sum -c -
    ln "$STAGE/resume_v4_smoke.py" "$ROOT/resume_v4_smoke.py"
    printf "%s  %s\n" "$SHA" "$ROOT/resume_v4_smoke.py" |
      /usr/bin/sha256sum -c -
    /usr/bin/unlink "$STAGE/resume_v4_smoke.py"
    rmdir "$STAGE"
    echo "V4_OPS_HELPER_PUBLISHED=PASS"
  '
)
```

如果 ops root 已经存在，整块会停止。不要删除或覆盖；先检查该目录是否来自这次审定发布。

## 2. HAKUSAN 上一次运行

登录 HAKUSAN 后先进入已有 tmux：

```bash
tmux new-session -A -s samebank_v4
```

然后把下面整块一次粘贴进去。它可能在 `srun` 处排队；此时可按 `Ctrl-b`，再按 `d` 安全脱离 tmux，SSH 可以断开。

```bash
(
  set -eu
  OPS="$HOME/audattn_external_eval_ops/same_bank_v4_2026-09-01"
  HELPER="$OPS/resume_v4_smoke.py"
  HELPER_SHA="245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4"
  MANIFEST_SHA="1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
  PYTHON="$HOME/miniconda3/envs/attn/bin/python"

  printf '%s  %s\n' "$HELPER_SHA" "$HELPER" |
    /usr/bin/sha256sum -c -

  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
    "$PYTHON" -I "$HELPER" \
      --confirm-action RESUME_V4_SMOKE \
      --confirm-manifest-sha256 "$MANIFEST_SHA"
)
```

成功终态应包含：

```text
"status": "SMOKE_SUBMITTED"
"job_id": "<纯数字 Job ID>"
```

若显示 `ALREADY_SUBMITTED`，代表本 ops 目录已有与 intent 匹配的可信 receipt，程序没有再次调用 `sbatch`。若显示 `STOP_AMBIGUOUS`，绝对不要重跑，应保留 `resume_state/intent.json` 并按下面的 nonce 流程人工核对。

### `STOP_AMBIGUOUS` 的唯一处置流程

helper 会在调用 `sbatch` 之前持久化一个 64 位 `intent_nonce`，并把前 12 位写入 Slurm comment。用以下整块定位潜在 Job：

```bash
(
  set -eu
  OPS="$HOME/audattn_external_eval_ops/same_bank_v4_2026-09-01"
  INTENT="$OPS/resume_state/intent.json"
  NONCE=$(jq -er '.intent_nonce | select(type == "string" and length == 64)' "$INTENT")
  TAG="audattn-v4-smoke-resume-${NONCE:0:12}"

  printf 'INTENT_NONCE=%s\nSLURM_COMMENT=%s\n' "$NONCE" "$TAG"
  squeue -h -u "$USER" -o '%A|%j|%T|%k' |
    /usr/bin/awk -F '|' -v tag="$TAG" '$4 == tag'
  sacct -S 2026-08-29 -u "$USER" -X -P \
    --format=JobIDRaw,JobName,State,ExitCode,Submit,Start,End,Comment |
    /usr/bin/awk -F '|' -v tag="$TAG" 'NR == 1 || $8 == tag'
)
```

判定规则：

- 若去重后恰好找到一个带此 comment 的纯数字 Job ID，则把它视为已提交 Job，直接用第 3 节的核验流程跟踪；不得重跑 helper。
- 若没找到或找到多个 Job，状态仍是 `STOP_AMBIGUOUS`；保留 intent 和所有 Slurm 记录，不得重试、删除 intent 或人工伪造 `receipt.json`。
- 任何歧义状态的自动恢复都必须由新的、独立审查的 reconciliation 工具处理；本 helper 故意永久拒绝该 ops 目录的第二次提交。

## 3. 查询 smoke

helper 正常返回后可从 receipt 读取 Job ID；若是上节的唯一匹配歧义 Job，则把人工核对到的纯数字 Job ID 填入下面的 `MANUAL_JOB_ID`。以下整块在 HAKUSAN 执行：

```bash
(
  set +e
  OPS="$HOME/audattn_external_eval_ops/same_bank_v4_2026-09-01"
  EVAL_ROOT="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"
  MANIFEST="$EVAL_ROOT/input_freeze.json"
  TOOL="$EVAL_ROOT/tools/locked_same_bank_eval.py"
  HELPER="$OPS/resume_v4_smoke.py"
  PYTHON="$HOME/miniconda3/envs/attn/bin/python"
  EXPECTED_HELPER_SHA256="245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4"
  EXPECTED_MANIFEST_SHA256="1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
  MANUAL_JOB_ID=""  # STOP_AMBIGUOUS 且只找到唯一 Job 时，在引号内填纯数字 ID

  HELPER_RC=0
  printf '%s  %s\n' "$EXPECTED_HELPER_SHA256" "$HELPER" |
    /usr/bin/sha256sum -c - || HELPER_RC=$?

  RECEIPT="$OPS/resume_state/receipt.json"
  RECEIPT_JOB_ID=""
  RECEIPT_RC=2
  if [ -f "$RECEIPT" ] && [ ! -L "$RECEIPT" ]; then
    RECEIPT_JOB_ID=$(jq -er \
      '.job_id | select(type == "string" and test("^[0-9]+$"))' "$RECEIPT")
    RECEIPT_RC=$?
  fi

  JOB_ID_SOURCE_RC=2
  JOB_ID=""
  if [ "$RECEIPT_RC" -eq 0 ] && [ -z "$MANUAL_JOB_ID" ]; then
    JOB_ID="$RECEIPT_JOB_ID"
    JOB_ID_SOURCE_RC=0
  elif printf '%s\n' "$MANUAL_JOB_ID" | /usr/bin/grep -Eq '^[0-9]+$' &&
       { [ ! -e "$RECEIPT" ] && [ ! -L "$RECEIPT" ]; }; then
    JOB_ID="$MANUAL_JOB_ID"
    JOB_ID_SOURCE_RC=0
  elif [ "$RECEIPT_RC" -eq 0 ] && [ "$MANUAL_JOB_ID" = "$RECEIPT_JOB_ID" ]; then
    JOB_ID="$MANUAL_JOB_ID"
    JOB_ID_SOURCE_RC=0
  fi

  if [ "$JOB_ID_SOURCE_RC" -ne 0 ]; then
    echo "STOP: no unique trusted Job ID" >&2
    exit 2
  fi

  LOG="$EVAL_ROOT/logs/audattn_samebank_v4_${JOB_ID}.log"
  MARKER="$EVAL_ROOT/state/SMOKE_PASS.json"

  squeue -j "$JOB_ID" -o "%.18i %.32j %.10T %.12M %.24R" || true
  sacct -j "$JOB_ID" -X \
    --format=JobID,JobName%32,State,ExitCode,Elapsed,Start,End,NodeList

  STATE_EXIT=$(sacct -j "$JOB_ID" -X -n -P --format=State,ExitCode |
    /usr/bin/awk -F '|' 'NF >= 2 { print $1 "|" $2; exit }')

  LOG_RC=2
  if [ -f "$LOG" ] && [ ! -L "$LOG" ]; then
    tail -n 160 "$LOG"
    if ! /usr/bin/grep -Eq 'Traceback|ERROR:' "$LOG"; then LOG_RC=0; fi
  fi

  MARKER_RC=2
  if [ -f "$MARKER" ] && [ ! -L "$MARKER" ]; then
    /usr/bin/sha256sum "$MARKER"
    MARKER_RC=0
  fi

  CHECK_OUTPUT=$(
    PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
      "$PYTHON" -I "$TOOL" check-only \
        --external-root "$EVAL_ROOT" \
        --manifest "$MANIFEST" \
        --expected-manifest-sha256 "$EXPECTED_MANIFEST_SHA256"
  )
  CHECK_RC=$?

  PARSER_RC=2
  if [ "$HELPER_RC" -eq 0 ]; then
    CHECK_OUTPUT="$CHECK_OUTPUT" \
    HELPER="$HELPER" \
    EXPECTED_MANIFEST_SHA256="$EXPECTED_MANIFEST_SHA256" \
      "$PYTHON" -I -c '
import os
import runpy

module = runpy.run_path(os.environ["HELPER"])
module["parse_check_output"](
    os.environ["CHECK_OUTPUT"].encode("utf-8"),
    os.environ["EXPECTED_MANIFEST_SHA256"],
)
' >/dev/null
    PARSER_RC=$?
  fi

  SMOKE_VERIFY_GATE=2
  if [ "$JOB_ID_SOURCE_RC" -eq 0 ] &&
     [ "$STATE_EXIT" = "COMPLETED|0:0" ] &&
     [ "$HELPER_RC" -eq 0 ] &&
     [ "$LOG_RC" -eq 0 ] &&
     [ "$MARKER_RC" -eq 0 ] &&
     [ "$CHECK_RC" -eq 0 ] &&
     [ "$PARSER_RC" -eq 0 ]; then
    SMOKE_VERIFY_GATE=0
  fi

  printf 'JOB_ID=%s STATE_EXIT=%s\n' "$JOB_ID" "$STATE_EXIT"
  printf 'RECEIPT_RC=%s JOB_ID_SOURCE_RC=%s HELPER_RC=%s LOG_RC=%s MARKER_RC=%s CHECK_RC=%s PARSER_RC=%s\n' \
    "$RECEIPT_RC" "$JOB_ID_SOURCE_RC" "$HELPER_RC" "$LOG_RC" \
    "$MARKER_RC" "$CHECK_RC" "$PARSER_RC"
  printf 'SMOKE_VERIFY_GATE=%s\n' "$SMOKE_VERIFY_GATE"

  if [ "$SMOKE_VERIFY_GATE" -ne 0 ]; then exit 2; fi
)
```

只有最后明确显示 `SMOKE_VERIFY_GATE=0` 时，smoke 才算通过。smoke 只是工程 canary，不产生科学结论；通过后才能准备完整 10k audit。

若 Job 是 `FAILED`、marker 缺失、日志有 `Traceback`/`ERROR:`、`check-only` 失败，或 `JOB_ID_SOURCE_RC`/`HELPER_RC`/`LOG_RC`/`MARKER_RC`/`CHECK_RC`/`PARSER_RC` 任一非 0，必须保留该 Job 的 log、`submitted_runners/`、`attempts/smoke/`、`FAILED/RUNNING` 记录及 ops `resume_state/`；禁止删除证据、禁止重跑 helper，也禁止手工再提一个 v4 smoke。对于经 nonce 唯一匹配的人工恢复路径，`RECEIPT_RC=2` 是预期的诊断值，不参与最终 gate。
