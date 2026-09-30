"""Fresh synthetic CPU process. No Dynamo reset, checkpoint, audio or GPU."""

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_archive as archive  # noqa: E402
import torch  # noqa: E402

FIXTURE_SHA = '25c427438faedd30fde6770ff1f7f26598f809d6a949d3f6050200b0f0450b16'
FIXTURE_PATH = archive.PROTOTYPES / 'targeted_trace_20260911/test_trace_observer.py'
archive.require(not FIXTURE_PATH.is_symlink()
                and archive.digest(FIXTURE_PATH.read_bytes()) == FIXTURE_SHA, 'toy fixture changed')
import test_trace_observer as fixtures  # noqa: E402


def plan():
    candidate = fixtures.plan()
    return replace(candidate, trials=tuple(range(32)), targets=(0, 28), batch_sizes=(16, 1),
                   stages=tuple(archive.base.Stage('model._orig_mod.' + s.module, s.branch)
                                for s in candidate.stages))


class Outer(torch.nn.Module):
    def __init__(self, dependent):
        super().__init__()
        self.model = torch.compile(fixtures.Toy(dependent), backend='eager')
        self.eval().requires_grad_(False)

    def forward(self, cue, mixture):
        return self.model(cue, mixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('reference', 'observed'), required=True)
    parser.add_argument('--case', choices=('invariant', 'dependent', 'interference'), required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binding', required=True)
    args = parser.parse_args()
    archive.require(sys.flags.isolated and sys.dont_write_bytecode and sys.byteorder == 'little',
                    'isolated bytecode-free process required')
    archive.require(not torch.cuda.is_initialized() and not torch.cuda.is_available(), 'CPU-only child required')
    torch.set_num_threads(1)
    torch.manual_seed(20260911)
    trace_plan = plan()
    binding = json.loads(args.binding)
    archive.require(binding['scope'] == 'SYNTHETIC_COLD_PAIR' and binding['case'] == args.case
                    and binding['torch'] == torch.__version__ and binding['backend'] == 'eager',
                    'supervised synthetic binding differs')
    args.root.mkdir(mode=0o700, exist_ok=False)
    model = Outer(dependent=args.case != 'invariant')
    store = None
    try:
        if args.role == 'reference':
            batches = fixtures.baseline(model, trace_plan)
        else:
            store = archive.stream.CaptureStore(args.root / 'captures')
            with archive.stream.StreamObserver(model, trace_plan, store) as observer:
                for p, i, ids in trace_plan.schedule():
                    call = (lambda c, m: model(c, m) + .125) if args.case == 'interference' else model
                    observer.record(call, p, i, ids, *fixtures.inputs(ids))
                batches = observer.finish()
        receipt = archive.seal_archive(args.root, role=args.role, binding=binding,
                                       plan=trace_plan, batches=batches, store=store)
    finally:
        if store is not None:
            store.close()
    archive.require(not torch.cuda.is_initialized(), 'CUDA initialized during child')
    print(json.dumps({'child_kind': 'COLD_SYNTHETIC_ARCHIVE_COMPLETE', **receipt,
        'pid': os.getpid(), 'python': sys.version.split()[0], 'torch': torch.__version__,
        'backend': 'eager', 'batches': len(batches), 'cuda_initialized': False,
        'checkpoint_loaded': False, 'jobs_submitted': 0,
        'worker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}), flush=True)


if __name__ == '__main__':
    main()
