"""Dry-run default; --run reuses R1's existing-only SSH transport, no retry."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE.parent / 'docs/superpowers/evidence/r1-development-inventory-20260922/run_readonly.py'
spec = importlib.util.spec_from_file_location('r1_existing_transport', DRIVER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if __name__ == '__main__':
    raise SystemExit(module.main(payload=(HERE/'e2_checkpoint_inventory.py').read_bytes(),
        accepted=('E2_BYTES_HASHED_STAGE_UNVERIFIED', 'E2_CHECKPOINT_GAP_RECORDED'),
        scope='8 named checkpoints; <=1 GiB each; <=90 seconds; SHA only; no deserialization or jobs'))
