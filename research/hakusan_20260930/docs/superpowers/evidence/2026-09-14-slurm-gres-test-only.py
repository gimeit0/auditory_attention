"""Three distinct scheduler-only diagnostics, no job creation or source writes.

No deploy/submit entry is called. Every sbatch argv is required to contain
--test-only. Failed cases are recorded once, never repeated automatically.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

W = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914'))
import control
import remote_ops as ops

REMOTE_SOURCE = '''import json,os,subprocess,sys
assert sys.platform == "linux" and sys.version.split()[0] == "3.11.5"
import pwd
assert pwd.getpwuid(os.getuid()).pw_name == "s2510040"
env={k:os.environ[k] for k in ("HOME","PATH","USER","LOGNAME","LANG") if k in os.environ}
base=["/usr/bin/sbatch","--test-only","--parsable","--export=NONE","--partition=GPU-1A", "--nodes=1", "--ntasks=1", "--cpus-per-task=8", "--mem=64G", "--time=02:00:00", "--no-requeue", "--job-name=audattn_gres_probe", "--wrap=/bin/true"]
cases=[("both_typed",["--gpus=nvidia_a100:1","--gpus-per-node=nvidia_a100:1"]), ("node_typed_only",["--gres=gpu:nvidia_a100:1"]), ("total_typed_only",["--gpus=nvidia_a100:1"])]
records=[]
for label,flags in cases:
 argv=base+flags
 assert argv[0] == "/usr/bin/sbatch" and "--test-only" in argv
 try:
  p=subprocess.run(argv,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=25)
  result={"case":label,"argv":argv,"returncode":p.returncode,"stdout":p.stdout.decode(errors="replace")[:32768],"stderr":p.stderr.decode(errors="replace")[:32768],"truncated":len(p.stdout)>32768 or len(p.stderr)>32768,"timed_out":False}
 except subprocess.TimeoutExpired as e:
  result={"case":label,"argv":argv,"returncode":None,"timed_out":True,"stdout":(e.stdout or b"").decode(errors="replace")[:32768],"stderr":(e.stderr or b"").decode(errors="replace")[:32768]}
 records.append(result)
 print("GRES_CASE="+json.dumps(result,sort_keys=True),flush=True)
print("GRES_RESULT="+json.dumps({"scope":"SCHEDULER_TEST_ONLY_NO_JOB","jobs_submitted":0,"automatic_retry":False,"cases":records},sort_keys=True),flush=True)
'''

def main():
    assert len(sys.argv) == 2 and sys.argv[1] == '--run-remote-test-only'
    os.umask(0o077)
    before = control.package()
    control.master_check(control.SOCKET)
    folder = Path(tempfile.mkdtemp(prefix='slurm-gres-test-only-', dir=W / 'docs/superpowers/evidence'))
    source = REMOTE_SOURCE.encode()
    print('EVIDENCE_DIRECTORY=' + str(folder), flush=True)
    process = control.transport(control.ssh_command(control.SOCKET), source, folder, timeout=100, log_cap=256*1024)
    log = ops.read(folder / 'output.log')
    values = [json.loads(line[len('GRES_RESULT='):]) for line in log.decode(errors='replace').splitlines()
              if line.startswith('GRES_RESULT=')]
    value = values[0] if len(values) == 1 else None
    good = (value is not None and process['returncode'] == 0 and process['error'] is None
            and value['scope'] == 'SCHEDULER_TEST_ONLY_NO_JOB' and value['jobs_submitted'] == 0
            and len(value['cases']) == 3 and before == control.package())
    if good:
        assert {c['case'] for c in value['cases']} == {'both_typed', 'node_typed_only', 'total_typed_only'}
        assert all(c['argv'][0] == '/usr/bin/sbatch' and '--test-only' in c['argv'] for c in value['cases'])
    receipt = {'status':'SCHEDULER_DIAGNOSTICS_COLLECTED' if good else 'SCHEDULER_DIAGNOSTICS_INCOMPLETE',
               'process':process, 'result':value, 'source_sha256':ops.sha(ops.read(Path(__file__))),
               'remote_payload_sha256':ops.sha(source), 'control_release_sha256':ops.sha(before[0]),
               'output':{'sha256':ops.sha(log),'size':len(log)}, 'jobs_submitted':0,
               'automatic_retry':False, 'model_loaded':False, 'resource_authorization_created':False}
    ops.write_new(folder / 'receipt.json', ops.wire(receipt))
    print(json.dumps(receipt,sort_keys=True),flush=True)
    return 0 if good else 2

if __name__ == '__main__':
    raise SystemExit(main())
