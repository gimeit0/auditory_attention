(
  set -euo pipefail
  test "$(uname -s)" = Linux
  test "$(id -un)" = s2510040

  B="$HOME/audattn_external_eval_diag"
  O="$B/same_bank_v4_job646900_2026-09-03_v6"
  R="$B/same_bank_v4_job646900_2026-09-03_v7"
  V="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"
  P="$HOME/miniconda3/envs/attn/bin/python"

  for D in "$B" "$O" "$O/state" "$V" "$V/state"
  do
    test -d "$D"
    test ! -L "$D"
  done

  if [ -e "$R" ] || [ -L "$R" ]; then
    echo "STOP: diagnostic v7 root already exists"
    ls -ld "$R"
    exit 2
  fi

  M="$V/input_freeze.json"
  K="$V/state/evaluation.lock"
  T="$O/state/DIAGNOSTIC_FAILED.json"
  for F in "$M" "$K" "$T"
  do
    test -f "$F"
    test ! -L "$F"
  done

  MH=1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5
  KH=63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710
  TH=5425b5f69dc41c782b816a608437321598793f8759aaa4c592fda0c3b7f2f999
  printf '%s  %s\n' "$MH" "$M" "$KH" "$K" "$TH" "$T" |
    /usr/bin/sha256sum -c -

  Q1=$(squeue -h -u "$USER" -n audattn_samebank_v4)
  Q2=$(squeue -h -u "$USER" -n audattn_v4_numdiag)
  printf 'V4_QUEUE=%s\nDIAG_QUEUE=%s\n' "$Q1" "$Q2"
  if [ -n "$Q1" ] || [ -n "$Q2" ]; then
    echo "STOP: related job exists"
    exit 2
  fi

  C='import torch,json;'
  C+='print("TORCH_VERSION="+torch.__version__);'
  C+='assert torch.__version__=="2.1.1+cu118";'
  C+='t=torch.backends;'
  C+='torch.use_deterministic_algorithms(True);'
  C+='t.cudnn.deterministic=True;t.cudnn.benchmark=False;'
  C+='torch.set_float32_matmul_precision("medium");'
  C+='t.cuda.matmul.allow_tf32=True;t.cudnn.allow_tf32=True;'
  C+='a=torch.are_deterministic_algorithms_enabled();'
  C+='p=torch.get_float32_matmul_precision();'
  C+='x=(a,t.cudnn.deterministic,t.cudnn.benchmark,p,'
  C+='t.cuda.matmul.allow_tf32,t.cudnn.allow_tf32);'
  C+='print("RUNTIME_VALUES="+json.dumps(x));'
  C+='assert x==(True,True,False,"high",True,True);'
  C+='print("RUNTIME_SIX_FLAGS=PASS")'
  "$P" -I -B -c "$C"

  echo "REMOTE_DIAG_V7_PREFLIGHT=PASS"
)
RC=$?
printf 'PREFLIGHT_RC=%s\n' "$RC"
