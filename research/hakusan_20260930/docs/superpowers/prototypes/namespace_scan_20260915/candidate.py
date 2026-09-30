"""Local test-only single-function overlay; never a deployable v19 identity."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v19/diagnose_batch_invariance.py'
PARENT_SHA = 'c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d'
NAME = '_safe_instance_dict'


def assemble():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PARENT_SHA:
        raise RuntimeError('frozen v19 core differs')
    original = raw.decode()
    tree = ast.parse(original)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == NAME]
    if len(nodes) != 1 or nodes[0].decorator_list:
        raise RuntimeError('overlay scope differs')
    # Lower precisely the two existing short-circuit generator checks into
    # loops. Same iterator, exact type identity predicate, and raise statement;
    # no dependency additions, successful-result cache, or skipped live keys.
    class Lower(ast.NodeTransformer):
        count = 0

        def visit_If(self, node):
            expected = ast.parse('any(type(key) is not str for key in dict.keys(namespace))', mode='eval').body
            if ast.dump(node.test) != ast.dump(expected):
                return self.generic_visit(node)
            if node.orelse or len(node.body) != 1 or not isinstance(node.body[0], ast.Raise):
                raise RuntimeError('rejection branch changed')
            self.count += 1
            return ast.For(target=ast.Name(id='key', ctx=ast.Store()),
                iter=ast.parse('dict.keys(namespace)', mode='eval').body,
                body=[ast.If(test=ast.parse('type(key) is not str', mode='eval').body,
                             body=node.body, orelse=[])], orelse=[], type_comment=None)

    lowered = Lower()
    replacement = ast.unparse(ast.fix_missing_locations(lowered.visit(nodes[0])))
    if lowered.count != 2:
        raise RuntimeError('expected exactly two namespace checks')
    lines = original.splitlines(keepends=True)
    node = nodes[0]
    source = ''.join(lines[:node.lineno - 1]) + replacement + '\n' + ''.join(lines[node.end_lineno:])
    strip = lambda t: [ast.dump(n) for n in t.body
                      if not (isinstance(n, ast.FunctionDef) and n.name == NAME)]
    if strip(ast.parse(original)) != strip(ast.parse(source)):
        raise RuntimeError('overlay changed code outside target')
    return source


def load(variant):
    if variant not in ('original', 'candidate'):
        raise ValueError('unknown local variant')
    name = 'namespace_scan_test_only_evaluator'
    if name in sys.modules:
        raise RuntimeError('independent cold process required')
    assembled = assemble()
    source = SOURCE.read_text() if variant == 'original' else assembled
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(source, '<namespace-scan-local-' + variant + '>', 'exec', dont_inherit=True), vars(module))
    module.LOCAL_TEST_VARIANT = variant
    return module, hashlib.sha256(source.encode()).hexdigest()
