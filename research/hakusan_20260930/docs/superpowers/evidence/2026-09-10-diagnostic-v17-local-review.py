"""Check exact predecessor preservation and narrow engineering AST changes."""

import ast
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v16'
NEW = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v17'
MANIFEST = ROOT / '.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v16-candidate-manifest.sha256'


def normalize(text):
    return text.replace('_v16', '_v17').replace('V16', 'V17')


def main():
    raw = MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'b8dd965e688ea8d2452a14cf831985e342969927e66363377eaaff1c6582bf15'
    count = 0
    for line in raw.decode().splitlines():
        sha, name = line.split()
        old = (OLD / name).read_bytes()
        assert hashlib.sha256(old).hexdigest() == sha, name
        if name not in ('README.md', 'diagnose_batch_invariance.py'):
            assert normalize(old.decode()) == (NEW / name).read_text(), name
        count += name.startswith('test_')
    a = ast.parse(normalize((OLD / 'diagnose_batch_invariance.py').read_text()))
    b = ast.parse((NEW / 'diagnose_batch_invariance.py').read_text())
    allowed = {
        '_callable_anchor_matches', '_SealBudget.__init__',
        '_SnapshotLoader.verify_runtime_bindings', '_AttemptArtifactStore._publish',
    }

    def erase(tree):
        found = set()
        for item in tree.body:
            if isinstance(item, ast.FunctionDef) and item.name in allowed:
                item.body = [ast.Pass()]
                found.add(item.name)
            if isinstance(item, ast.ClassDef):
                for method in item.body:
                    if isinstance(method, ast.FunctionDef):
                        name = item.name + '.' + method.name
                        if name in allowed:
                            method.body = [ast.Pass()]
                            found.add(name)
        assert found == allowed, found
    added = [n for n in b.body if isinstance(n, ast.FunctionDef) and n.name == '_live_protected_module_bindings']
    assert len(added) == 1
    b.body.remove(added[0])
    erase(a)
    erase(b)
    assert ast.dump(a) == ast.dump(b), 'change outside reviewed engineering methods'
    # The work/depth/node enforcement and all scientific execution code are
    # included in the unchanged AST, not omitted merely by a loose class diff.
    print('OLD_RELEASE_FILES_VERIFIED=23')
    print('ORIGINAL_TEST_ENTRIES_UNCHANGED=' + str(count))
    print('AST_SCOPE_FOUR_ENGINEERING_METHODS_ONE_NAME_CLASSIFIER=PASS')
    print('SCIENTIFIC_EXECUTION_MODEL_GRAPH_BODIES_BUDGET_ENFORCEMENT_UNCHANGED=PASS')
    tests_path = NEW / 'test_live_anchor_match.py'
    spec = importlib.util.spec_from_file_location('v17_anchor_mutation_review', tests_path)
    tests = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tests
    spec.loader.exec_module(tests)
    source = (NEW / 'diagnose_batch_invariance.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_callable_anchor_matches')
    body = ast.get_source_segment(source, node)
    cases = [
        ('and previous[2] is code', 'and True', 'test_code_change_within_check_rejected'),
        ('and previous[3] is defaults', 'and True', 'test_defaults_rebinding_and_kwdefaults_are_live'),
        ('and value.__kwdefaults__ is None', 'and True', 'test_defaults_rebinding_and_kwdefaults_are_live'),
        ('id(defaults) in budget.literal_defaults', 'True', 'test_mutable_default_contents_never_reused'),
    ]
    for old_text, new_text, name in cases:
        result = unittest.TestResult()
        tests.MatchTests(name).run(result)
        assert result.wasSuccessful(), (name, result.errors, result.failures)
        assert body.count(old_text) == 1
        namespace = dict(vars(tests.diag))
        exec(compile(body.replace(old_text, new_text), '<v17-rejected-mutation>', 'exec'), namespace)
        with mock.patch.object(tests.diag, '_callable_anchor_matches', namespace['_callable_anchor_matches']):
            result = unittest.TestResult()
            tests.MatchTests(name).run(result)
        assert not result.wasSuccessful(), 'mutation escaped: ' + name
        print('REJECTED_MUTATION=' + old_text)
    print('Self-review, not an independent agent review or GPU acceptance.')


if __name__ == '__main__':
    main()
