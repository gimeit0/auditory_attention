"""Synthetic event-matcher tests; never stand in for production compiler evidence."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backend_evidence as b


def compiler(self):
    return None


def codegen():
    return None


class Graph:
    pass


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'artifact.py'
        self.path.write_text('def call(inputs):\n    return inputs\n')
        scope = {}
        exec(compile(self.path.read_bytes(), str(self.path), 'exec'), scope)
        self.fn = scope['call']
        self.owner = object()
        self.graph = Graph()
        self.graph.compiled_artifact = self.fn
        self.graph.artifact_path = str(self.path)
        self.graph.cache_key = 'synthetic-only'
        self.cframe = types.SimpleNamespace(f_code=compiler.__code__, f_locals={'self': self.owner}, f_back=None)
        self.gframe = types.SimpleNamespace(f_code=codegen.__code__, f_locals={}, f_back=self.cframe)
        self.aframe = types.SimpleNamespace(f_code=self.fn.__code__, f_locals={}, f_globals=scope)
        self.ledger = b.CallLedger(self.owner, compiler.__code__, codegen.__code__, Graph, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def compile(self):
        self.ledger.observe(self.cframe, 'call', None)
        self.ledger.observe(self.gframe, 'return', self.graph)
        self.ledger.observe(self.cframe, 'return', self.fn)

    def execute(self):
        self.ledger.observe(self.aframe, 'call', None)
        self.ledger.observe(self.aframe, 'return', (1,))

    def test_bound_compilation_and_artifact_execution(self):
        self.compile(); self.execute()
        r = self.ledger.finish()
        self.assertTrue(r['target_generated_artifacts_executed'])
        self.assertFalse(r['production_ready'])
        self.assertFalse(r['interference_validated'])

    def test_context_only_rejected(self):
        with self.assertRaises(RuntimeError):
            self.ledger.finish()

    def test_compile_without_execution_rejected(self):
        self.compile()
        with self.assertRaises(RuntimeError):
            self.ledger.finish()

    def test_other_compiler_rejected(self):
        self.cframe.f_locals['self'] = object()
        with self.assertRaises(RuntimeError):
            self.ledger.observe(self.cframe, 'call', None)

    def test_unbound_codegen_rejected(self):
        with self.assertRaises(RuntimeError):
            self.ledger.observe(self.gframe, 'return', self.graph)

    def test_compilation_time_execution_not_inference(self):
        self.ledger.observe(self.cframe, 'call', None)
        self.ledger.observe(self.gframe, 'return', self.graph)
        with self.assertRaises(RuntimeError):
            self.execute()

    def test_partial_or_failed_execution_rejected(self):
        self.compile()
        self.ledger.observe(self.aframe, 'call', None)
        with self.assertRaises(RuntimeError):
            self.ledger.finish()
        with self.assertRaises(RuntimeError):
            self.ledger.observe(self.aframe, 'return', None)

    def test_changed_artifact_file_rejected(self):
        self.compile(); self.execute()
        self.path.write_text('changed')
        with self.assertRaises(RuntimeError):
            self.ledger.finish()

    def test_changed_artifact_binding_rejected(self):
        self.compile(); self.execute()
        self.graph.compiled_artifact = lambda x: x
        with self.assertRaises(RuntimeError):
            self.ledger.finish()

    def test_other_globals_rejected(self):
        self.compile()
        self.aframe.f_globals = dict(self.aframe.f_globals)
        with self.assertRaises(RuntimeError):
            self.execute()


if __name__ == '__main__':
    unittest.main(verbosity=2)
