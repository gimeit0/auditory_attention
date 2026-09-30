"""Fake scheduler/SSH and private local filesystem only; no remote side effects."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import control  # noqa: E402
import remote_ops as ops  # noqa: E402


def ok(stdout=""):
    return {"returncode": 0, "stdout": stdout, "stderr": "", "timed_out": False, "truncated": False}


def fixture_release():
    raw = ops.read(control.WORKSPACE / ops.MANIFEST)
    names = list(json.loads(raw)["files"]) + [ops.MANIFEST, ops.OPS, str(HERE.relative_to(control.WORKSPACE) / "control.py")]
    data = {name: ops.read(control.WORKSPACE / name) for name in names}
    release = {"schema_version": 1, "root": str(ops.REMOTE), "limits": ops.LIMITS,
               "package_sha256": ops.PACKAGE_SHA, "scope": ops.SCOPE, "files": {n: ops.sha(b) for n, b in data.items()}}
    raw = ops.wire(release)
    return raw, release, data


def held(root, job, nonce):
    return (f"JobId={job} JobName=audattn_b2_coldpair UserId=s2510040(1001) Partition=GPU-1A "
            "JobState=PENDING Reason=JobHeldUser Priority=0 NumCPUs=8 NumNodes=1 NumTasks=1 CPUs/Task=8 "
            "TimeLimit=02:00:00 Requeue=0 MinMemoryNode=64G ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu=1 "
            f"Comment=audattn-b2-{nonce} WorkDir={root} Command={root / 'package' / ops.RUNNER}")


class RemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.release, cls.files = fixture_release()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gpu-control-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "new-root"
        self.calls = []
        self.nonce = "a" * 32
        self.clock = 100000.0
        self.operations = ops.Operations(self.root, self.invoke, lambda: self.clock)
        self.operations.preflight = mock.Mock(return_value={"status": "SYNTHETIC_PREFLIGHT_ONLY"})
        self.operations.protected_inputs = mock.Mock()
        self.spec = {"action": "deploy", "request_id": "1" * 32, "release_sha256": ops.sha(self.raw),
                     "release_base64": base64.b64encode(self.raw).decode(),
                     "files": {n: base64.b64encode(b).decode() for n, b in self.files.items()}}

    def invoke(self, argv):
        self.calls.append(argv)
        if argv[0] == "/usr/bin/sbatch":
            if "--test-only" in argv:
                return ok("synthetic scheduling estimate\n")
            self.assertTrue((self.root / "SUBMIT_INTENT.json").exists())
            self.assertIn("--hold", argv)
            return ok("12345\n")
        if argv[:3] == ["/usr/bin/scontrol", "show", "job"]:
            return ok(held(self.root, "12345", self.nonce))
        if argv[:2] == ["/usr/bin/scontrol", "release"]:
            self.assertTrue((self.root / "RELEASE_INTENT.json").exists())
            return ok()
        return ok()

    def prepared(self):
        self.operations.deploy(self.spec)
        test = self.operations.test_only({"request_id": "2" * 32, "release_sha256": self.spec["release_sha256"]}, self.release)
        return {"action": "submit", "request_id": "3" * 32, "release_sha256": self.spec["release_sha256"],
                "confirm": ops.CONFIRM, "test_id": test["test_id"], "test_sha256": test["test_sha256"],
                "authorization": {"approved": True, "package_sha256": ops.PACKAGE_SHA, "pair_nonce": self.nonce,
                                  "limits": dict(ops.LIMITS), "scope": ops.SCOPE}}

    def submit_calls(self):
        return [a for a in self.calls if a[0] == "/usr/bin/sbatch" and "--test-only" not in a]

    def release_calls(self):
        return [a for a in self.calls if a[:2] == ["/usr/bin/scontrol", "release"]]

    def test_real_pinned_package_roundtrip_local_fixture(self):
        result = self.operations.deploy(self.spec)
        self.assertEqual(result["status"], "GPU_PACKAGE_DEPLOYED")
        self.operations.sources(self.release)
        self.assertTrue((self.root / "logs").is_dir())
        self.assertFalse((self.root / "AUTHORIZATION.json").exists())
        self.assertEqual(self.calls, [])

    def test_no_overwrite_after_deploy(self):
        self.operations.deploy(self.spec)
        before = ops.read(self.root / "DEPLOYMENT.json")
        with self.assertRaisesRegex(RuntimeError, "root already"):
            self.operations.deploy(self.spec)
        self.assertEqual(before, ops.read(self.root / "DEPLOYMENT.json"))

    def test_corrupt_upload_rejected_before_root_creation(self):
        self.spec["files"][ops.RUNNER] = base64.b64encode(b"bad").decode()
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            self.operations.deploy(self.spec)
        self.assertFalse(self.root.exists())

    def test_extra_upload_member_rejected(self):
        self.spec["files"]["docs/extra.py"] = ""
        with self.assertRaisesRegex(RuntimeError, "member set"):
            self.operations.deploy(self.spec)
        self.assertFalse(self.root.exists())

    def test_preflight_failure_writes_nothing(self):
        self.operations.preflight.side_effect = RuntimeError("related job")
        with self.assertRaises(RuntimeError):
            self.operations.deploy(self.spec)
        self.assertFalse(self.root.exists())

    def test_partial_deployment_blocks_retry(self):
        original = ops.write_new
        def fail(path, raw):
            if path.name == "numeric_trace.py":
                raise OSError("synthetic disk failure")
            original(path, raw)
        with mock.patch.object(ops, "write_new", side_effect=fail), self.assertRaises(OSError):
            self.operations.deploy(self.spec)
        self.assertTrue(self.root.exists())
        with self.assertRaisesRegex(RuntimeError, "root already"):
            self.operations.deploy(self.spec)

    def test_no_authorization_or_job_from_test_only(self):
        self.prepared()
        self.assertEqual(len([a for a in self.calls if "--test-only" in a]), 1)
        self.assertEqual(self.submit_calls(), [])
        self.assertFalse((self.root / "AUTHORIZATION.json").exists())

    def test_missing_confirmation_never_submits(self):
        spec = self.prepared()
        spec.pop("confirm")
        with self.assertRaisesRegex(RuntimeError, "authorization"):
            self.operations.submit(spec, self.release)
        self.assertEqual(self.submit_calls(), [])

    def test_wrong_resource_authorization_never_submits(self):
        spec = self.prepared()
        spec["authorization"]["limits"]["gpus"] = 2
        with self.assertRaisesRegex(RuntimeError, "authorization differs"):
            self.operations.submit(spec, self.release)
        self.assertEqual(self.submit_calls(), [])

    def test_stale_test_receipt_rejected(self):
        spec = self.prepared()
        self.clock += 86401
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.operations.submit(spec, self.release)
        self.assertEqual(self.submit_calls(), [])

    def test_changed_test_receipt_rejected(self):
        spec = self.prepared()
        spec["test_sha256"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.operations.submit(spec, self.release)
        self.assertEqual(self.submit_calls(), [])

    def test_submit_hold_verify_release_exactly_once(self):
        spec = self.prepared()
        result = self.operations.submit(spec, self.release)
        self.assertEqual(result["status"], "SUBMITTED_AND_RELEASED")
        self.assertEqual(len(self.submit_calls()), 1)
        self.assertEqual(self.release_calls(), [["/usr/bin/scontrol", "release", "12345"]])
        self.assertEqual(json.loads(ops.read(self.root / "AUTHORIZATION.json")), spec["authorization"])
        self.assertEqual(ops.read(self.root / "AUTHORIZATION.json"), ops.read(self.root / "SUBMIT_INTENT.json"))
        with self.assertRaises(RuntimeError):
            self.operations.submit(spec, self.release)
        self.assertEqual(len(self.submit_calls()), 1)

    def test_sbatch_timeout_preserves_intent_no_release_retry(self):
        spec = self.prepared()
        original = self.operations.invoke
        def lost(argv):
            if argv[0] == "/usr/bin/sbatch":
                self.calls.append(argv)
                return {**ok(), "returncode": None, "timed_out": True}
            return original(argv)
        self.operations.invoke = lost
        with self.assertRaises(RuntimeError):
            self.operations.submit(spec, self.release)
        self.assertTrue((self.root / "SUBMIT_ERROR.json").exists())
        self.assertEqual(len(self.submit_calls()), 1)
        self.assertEqual(self.release_calls(), [])
        with self.assertRaises(RuntimeError):
            self.operations.submit(spec, self.release)
        self.assertEqual(len(self.submit_calls()), 1)

    def test_bad_scheduler_resources_leave_same_job_held(self):
        spec = self.prepared()
        original = self.operations.invoke
        def wrong(argv):
            result = original(argv)
            if argv[:3] == ["/usr/bin/scontrol", "show", "job"]:
                result["stdout"] = result["stdout"].replace("NumCPUs=8", "NumCPUs=16")
            return result
        self.operations.invoke = wrong
        with self.assertRaisesRegex(RuntimeError, "held scheduler"):
            self.operations.submit(spec, self.release)
        self.assertEqual(self.release_calls(), [])
        self.assertEqual(json.loads(ops.read(self.root / "SUBMISSION_RECEIPT.json"))["job_id"], "12345")

    def test_source_change_before_release_keeps_held(self):
        spec = self.prepared()
        original = self.operations.invoke
        def changed(argv):
            result = original(argv)
            if argv[:3] == ["/usr/bin/scontrol", "show", "job"]:
                path = self.root / "package" / ops.RUNNER
                path.write_bytes(path.read_bytes() + b"\n# synthetic corruption\n")
            return result
        self.operations.invoke = changed
        with self.assertRaisesRegex(RuntimeError, "source SHA"):
            self.operations.submit(spec, self.release)
        self.assertEqual(self.release_calls(), [])

    def test_release_timeout_never_resubmits(self):
        spec = self.prepared()
        original = self.operations.invoke
        def lost(argv):
            result = original(argv)
            if argv[:2] == ["/usr/bin/scontrol", "release"]:
                raise TimeoutError("release reply lost")
            return result
        self.operations.invoke = lost
        with self.assertRaises(TimeoutError):
            self.operations.submit(spec, self.release)
        with self.assertRaises(RuntimeError):
            self.operations.submit(spec, self.release)
        self.assertEqual(len(self.release_calls()), 1)
        self.assertEqual(len(self.submit_calls()), 1)

    def test_status_only_queries_no_state_change(self):
        spec = self.prepared()
        self.operations.submit(spec, self.release)
        before = {str(p.relative_to(self.root)): ops.sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        calls = len(self.calls)
        result = self.operations.status()
        after = {str(p.relative_to(self.root)): ops.sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["jobs_submitted"], 0)
        self.assertTrue(all(a[0] in ("/usr/bin/squeue", "/usr/bin/sacct") for a in self.calls[calls:]))

    def test_partial_root_status_is_read_only(self):
        self.root.mkdir(mode=0o700)
        (self.root / ".upload-staging").mkdir(mode=0o700)
        result = self.operations.status()
        self.assertEqual(result["top_level"], [".upload-staging"])
        self.assertEqual(self.calls, [])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [".upload-staging"])

    def test_failed_test_only_recorded_without_job_or_authorization(self):
        self.operations.deploy(self.spec)
        self.operations.invoke = mock.Mock(return_value={**ok("synthetic rejection"), "returncode": 1})
        with self.assertRaisesRegex(RuntimeError, "test-only failed"):
            self.operations.test_only({"request_id": "2" * 32, "release_sha256": self.spec["release_sha256"]}, self.release)
        self.assertTrue((self.root / "test_only" / ("2" * 32 + ".json")).exists())
        self.assertFalse((self.root / "AUTHORIZATION.json").exists())
        self.assertIn("--test-only", self.operations.invoke.call_args[0][0])

    def test_unsafe_member_paths_rejected(self):
        for name in ("/tmp/a.py", "docs/../bad.py", "docs//bad.py", "docs/./bad.py", "docs/a.sh", "other/a.py"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                ops.member(name)

    def test_scheduler_variants_and_bad_fields(self):
        valid = held(self.root, "12345", self.nonce)
        self.assertTrue(ops.held_request_matches(valid.replace("NumNodes=1", "NumNodes=1-1").replace("64G", "65536M"),
                                               "12345", self.nonce, self.root))
        for old, new in (("gres/gpu=1", "gres/gpu=0"), ("gres/gpu=1", "gres/gpu=2"), ("mem=64G", "mem=128G"),
                         ("JobHeldUser", "Resources"), ("JobId=12345", "JobId=12346"), ("Requeue=0", "Requeue=1"),
                         ("TimeLimit=02:00:00", "TimeLimit=04:00:00"), ("UserId=s2510040", "UserId=someone_else")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                ops.held_request_matches(valid.replace(old, new), "12345", self.nonce, self.root)

    def test_ambiguous_job_id_rejected(self):
        for text in ("123\n124\n", "Submitted batch job 123", "0\n", "١٢٣\n"):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                ops.job_id(ok(text))
        self.assertEqual(ops.job_id(ok("123;cluster\n")), "123")


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gpu-control-local-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.raw, self.release, self.files = fixture_release()

    def test_submit_requires_confirmation_and_test(self):
        with self.assertRaises(RuntimeError):
            control.make_request("submit", self.raw, self.files)

    def test_non_submit_requests_contain_no_authorization(self):
        for action in ("preflight", "deploy", "test-only", "status"):
            spec = control.make_request(action, self.raw, self.files)
            self.assertNotIn("authorization", spec)
            self.assertNotIn("confirm", spec)

    def test_ssh_fallback_and_password_auth_disabled(self):
        argv = control.ssh_command(self.root / "socket")
        self.assertIn("ProxyCommand=/usr/bin/false", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ControlMaster=no", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)

    def test_local_uncertain_submit_blocks_second_transport(self):
        spec = control.make_request("submit", self.raw, self.files, confirmation=ops.CONFIRM,
                                    reviewed={"test_id": "2" * 32, "test_sha256": "b" * 64})
        calls = []
        def lost(command, request, folder):
            calls.append(command)
            self.assertTrue((self.root / "LOCAL_SUBMIT_INTENT.json").exists())
            ops.write_new(folder / "output.log", b"synthetic SSH disconnect\n")
            return {"returncode": 255, "error": None}
        with redirect_stdout(io.StringIO()):
            result = control.operate(spec, self.files, self.root, lost)
            with self.assertRaises(FileExistsError):
                control.operate(spec, self.files, self.root, lost)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(result["returncode"], 0)

    def test_wrong_remote_response_binding_rejected(self):
        spec = control.make_request("status", self.raw, self.files)
        def wrong(command, request, folder):
            value = {"request_id": "f" * 32, "action": spec["action"], "release_sha256": spec["release_sha256"], "ok": True}
            ops.write_new(folder / "output.log", b"GPU_CONTROL=" + ops.wire(value))
            return {"returncode": 0, "error": None}
        with redirect_stdout(io.StringIO()):
            result = control.operate(spec, self.files, self.root, wrong)
        self.assertNotEqual(result["returncode"], 0)

    def test_test_receipt_binding(self):
        path = self.root / "receipt.json"
        value = {"action": "test-only", "returncode": 0, "release_sha256": ops.sha(self.raw),
                 "remote": {"ok": True, "result": {"status": "SCHEDULER_TEST_ONLY_PASS", "test_id": "a" * 32, "test_sha256": "b" * 64}}}
        ops.write_new(path, ops.wire(value))
        self.assertEqual(control.test_receipt(path, ops.sha(self.raw))["test_id"], "a" * 32)
        with self.assertRaises(RuntimeError):
            control.test_receipt(path, "f" * 64)

    def test_duplicate_response_not_accepted(self):
        spec = control.make_request("status", self.raw, self.files)
        def duplicate(command, request, folder):
            value = {k: spec[k] for k in ("request_id", "action", "release_sha256")}
            value.update(ok=True, result={"status": "SYNTHETIC"})
            ops.write_new(folder / "output.log", (b"GPU_CONTROL=" + ops.wire(value)) * 2)
            return {"returncode": 0, "error": None}
        with redirect_stdout(io.StringIO()):
            result = control.operate(spec, self.files, self.root, duplicate)
        self.assertEqual(result["returncode"], 2)

    def test_matching_response_receipt_is_rehashable(self):
        spec = control.make_request("status", self.raw, self.files)
        def response(command, request, folder):
            value = {k: spec[k] for k in ("request_id", "action", "release_sha256")}
            value.update(ok=True, result={"status": "SYNTHETIC_NO_REMOTE"})
            ops.write_new(folder / "output.log", b"GPU_CONTROL=" + ops.wire(value))
            return {"returncode": 0, "error": None}
        with redirect_stdout(io.StringIO()):
            result = control.operate(spec, self.files, self.root, response)
        self.assertEqual(result["returncode"], 0)
        path = next(self.root.glob("*/output.log"))
        self.assertEqual(ops.sha(path.read_bytes()), result["output"]["sha256"])

    def test_local_transport_actual_echo_no_ssh(self):
        command = [sys.executable, "-I", "-B", "-c", "import sys; print(sys.stdin.read())"]
        result = control.transport(command, b"synthetic payload", self.root, timeout=2)
        self.assertEqual(result["returncode"], 0)
        self.assertIsNone(result["error"])
        self.assertEqual((self.root / "output.log").read_bytes(), b"synthetic payload\n")

    def test_local_transport_timeout_preserved(self):
        command = [sys.executable, "-I", "-B", "-c", "import time; time.sleep(5)"]
        result = control.transport(command, b"synthetic", self.root, timeout=0.2)
        self.assertEqual(result["error"]["type"], "TimeoutError")
        self.assertTrue((self.root / "request.py").exists())

    def test_local_transport_exception_produces_receipt(self):
        spec = control.make_request("status", self.raw, self.files)
        with redirect_stdout(io.StringIO()):
            result = control.operate(spec, self.files, self.root, mock.Mock(side_effect=OSError("synthetic start error")))
        self.assertEqual(result["returncode"], 2)
        self.assertTrue(list(self.root.glob("*/receipt.json")))

    def test_payload_contains_exact_source_not_modified_by_spec(self):
        spec = control.make_request("preflight", self.raw, self.files)
        source = b"RETURNED_REQUEST=SPEC['request_id']\n"
        code = control.payload(spec, source)
        namespace = {"__name__": "synthetic-test"}
        exec(compile(code, "<transport-payload-test>", "exec"), namespace)
        self.assertEqual(namespace["SOURCE_SHA"], ops.sha(source))
        self.assertEqual(namespace["SPEC"], spec)
        self.assertEqual(namespace["RETURNED_REQUEST"], spec["request_id"])


if __name__ == "__main__":
    os.umask(0o077)
    unittest.main()
