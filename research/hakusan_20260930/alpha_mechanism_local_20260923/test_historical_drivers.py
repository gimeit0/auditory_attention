"""Executed historical drivers: preserved byte-exact copies and the exact edits that lead to the current files."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).absolute().parent
ROOT = HERE/'historical_drivers_20260929'
ident = lambda raw: dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class LineageTests(unittest.TestCase):
    def test_preserved_copies_match_executed_identity_and_edits_reproduce_current(self):
        lineage = json.loads((ROOT/'DRIVER_LINEAGE.json').read_text())
        self.assertEqual(len(lineage['drivers']), 4)
        for name, row in lineage['drivers'].items():
            recorded = json.loads((HERE/row['local_intent']).read_text())['driver']
            preserved = (ROOT/name).read_bytes()
            self.assertEqual(ident(preserved), recorded, name)
            text = preserved.decode()
            for step in row['edits_preserved_to_current']:
                if step['kind'] == 'replace_once':
                    self.assertEqual(text.count(step['old']), 1, name); text = text.replace(step['old'], step['new'], 1)
                else:
                    lines = text.split('\n'); i = lines.index(step['line']); lines.insert(i+1, step['text']); text = '\n'.join(lines)
            self.assertEqual(text, (HERE/name).read_text(), name + ': current file drifted beyond the documented edits')


if __name__ == '__main__': unittest.main()
