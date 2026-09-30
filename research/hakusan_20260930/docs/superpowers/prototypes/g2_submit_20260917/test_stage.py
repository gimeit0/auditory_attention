"""Local real candidate deployment tests in temporary directories; no SSH."""
import ast
import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import control as c
import ship


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/c.REMOTE.name
        control, source, raw, files = ship.sources()
        spec = importlib.util.spec_from_file_location('g2_test_stage', HERE/'stage.py')
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        self.s.c, self.s.CONTROL_BYTES, self.s.SOURCE_BYTES = c, control, source
        self.s.SPEC = dict(action='deploy', control_sha256=c.sha(control), stage_sha256=c.sha(source),
            release=base64.b64encode(raw).decode(), files={n:base64.b64encode(b).decode() for n,b in files.items()})
        self.addCleanup(lambda: sys.modules.pop('g2_stage_entry', None))
        self.root_patch = patch.object(c, 'REMOTE', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.calls = []
        def command(argv, **kwargs):
            self.calls.append(argv)
            self.assertEqual(argv[0], '/usr/bin/squeue')
            return dict(returncode=0, error=None, stdout='', stderr='')
        self.command_patch = patch.object(c, 'command', command)
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def test_real_write_once_candidate_layout_and_hashes(self):
        result = self.s.deploy()
        self.assertEqual(result['files'], 32)
        self.assertEqual(result['jobs_submitted'], 0)
        manifest = c.decode(c.read(self.root/'RELEASE.json'), c.RELEASE_SHA)
        for name, digest in manifest['files'].items():
            self.assertEqual(c.sha(c.read(self.root/name)), digest)
            self.assertEqual((self.root/name).stat().st_mode & 0o777, 0o600)
        for p in ('R','C','D','E'):
            self.assertEqual({n.name for n in (self.root/p).iterdir()},
                             {'tools','logs','state','attempts','submitted_runners'})
            self.assertFalse((self.root/p/'input_freeze.json').exists())
        self.assertFalse((self.root/'EXECUTION_PLAN.json').exists())
        self.assertFalse((self.root/'RUN_REQUEST.json').exists())
        with self.assertRaises(RuntimeError): self.s.deploy()
        self.assertEqual(len(self.calls), 1)

    def test_corrupt_payload_refused_before_root_creation(self):
        name = next(iter(self.s.SPEC['files']))
        self.s.SPEC['files'][name] = base64.b64encode(b'bad').decode()
        with self.assertRaises(RuntimeError): self.s.deploy()
        self.assertFalse(self.root.exists())

    def test_extra_path_refused_before_root_creation(self):
        self.s.SPEC['files']['../escape'] = base64.b64encode(b'bad').decode()
        with self.assertRaises(RuntimeError): self.s.deploy()
        self.assertFalse(self.root.exists())

    def test_nonempty_queue_refused_before_root_creation(self):
        with patch.object(c, 'command', return_value=dict(returncode=0, error=None, stdout='123|RUNNING|other')):
            with self.assertRaises(RuntimeError): self.s.deploy()
        self.assertFalse(self.root.exists())

    def test_dangling_root_symlink_refused(self):
        self.root.symlink_to(self.root.parent/'missing')
        with self.assertRaises(RuntimeError): self.s.deploy()
        self.assertFalse(self.calls)

    def test_payload_is_code_and_bounded_data_not_shell(self):
        blob = ship.payload(self.s.SPEC, self.s.CONTROL_BYTES, self.s.SOURCE_BYTES)
        compile(blob, '<local-payload-check>', 'exec')
        tree = ast.parse(blob)
        spec_node = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                         and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'SPEC')
        self.assertEqual(c.sha(c.wire(ast.literal_eval(spec_node))), c.sha(c.wire(self.s.SPEC)))
        self.assertLess(len(blob), 16*1024**2)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StageTests))
    print('G2_STAGE_TEST_REPORT='+json.dumps(dict(tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), jobs_submitted=0, production_model_loaded=False)), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)
