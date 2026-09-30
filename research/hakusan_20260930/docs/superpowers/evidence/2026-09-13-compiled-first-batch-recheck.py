"""Offline recheck of the one specific completed synthetic CPU probe."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = Path(__file__).parent / "compiled-remote-cpu-20260913T030436Z-lr38eivo"
DRIVER = ROOT / "docs/superpowers/prototypes/targeted_compiled_20260912/probe_driver.py"
EXPECTED = "66b6b75d130add467b515d94b1cc0a02e52ad94dab6344f346ffe920fa16e09c"


def main():
    assert hashlib.sha256(DRIVER.read_bytes()).hexdigest() == EXPECTED
    spec = importlib.util.spec_from_file_location("reviewed_compiled_driver", DRIVER)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    receipt = json.loads((FOLDER / "receipt.json").read_bytes())
    raw = (FOLDER / "output.log").read_bytes()
    records, sources = driver.package_sources()
    payload = driver.make_bootstrap(records, sources, True)
    assert receipt["driver_sha256"] == EXPECTED
    assert receipt["manifest_sha256"] == driver.sha(driver.MANIFEST.read_bytes())
    assert receipt["payload_sha256"] == driver.sha(payload)
    assert receipt["output_sha256"] == driver.sha(raw)
    assert receipt["output_size"] == len(raw) == 12063
    parsed = [json.loads(line.removeprefix("BOOTSTRAP_RECORD="))
              for line in raw.decode().splitlines() if line.startswith("BOOTSTRAP_RECORD=")]
    assert len(parsed) == 1 and parsed[0] == receipt["bootstrap_record"]
    assert driver.accepted(parsed[0], True)
    assert parsed[0]["source_sha256"] == records
    assert receipt["returncode"] == 0
    assert receipt["status"] == "REMOTE_COMPILED_FIRST_BATCH_VERIFIED"
    child = parsed[0]["child"]
    assert child["pid"] == 3076537
    # The preparation receipt is a pre-forward snapshot, not the final result.
    assert child["preparation"]["compiled_guard_probe_completed"] is False
    assert child["preparation"]["compiler_backend_entered"] is False
    assert child["compiler_backend_entered"] is True
    assert child["preparation"]["original_attestation"]["trust_domain"] == "hermetic-test"
    print(json.dumps({"status": "FIRST_BATCH_EVIDENCE_RECHECK_PASS",
                      "files_verified": len(records), "worker_pid": child["pid"],
                      "output_sha256": driver.sha(raw),
                      "receipt_sha256": driver.sha((FOLDER / "receipt.json").read_bytes()),
                      "scope": "one synthetic CPU compiled eager forward; not production",
                      "jobs_submitted": 0, "ready_for_gpu": False}, sort_keys=True))


if __name__ == "__main__":
    main()
