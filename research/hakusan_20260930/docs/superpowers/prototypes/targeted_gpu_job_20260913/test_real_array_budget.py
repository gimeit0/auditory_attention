"""Actual frozen feature SHAPE/bytes, synthetic zeros; never original model data."""
import hashlib
import mmap
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bounded_archive as bounded  # noqa: E402


class RealSizeTests(unittest.TestCase):
    def test_exact_parent_file_and_total_budget(self):
        self.assertEqual(bounded.archive.MAX_ARRAY, 204800000)
        self.assertEqual(bounded.archive.CHUNK, 1048576)
        self.assertLessEqual(bounded.BUDGET["expected_array_bytes_per_child"], bounded.archive.MAX_TOTAL)
        self.assertEqual(hashlib.sha256(bounded.SOURCE.read_bytes()).hexdigest(), bounded.SOURCE_SHA)

    def test_above_exact_real_file_cap_rejected_without_copy(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            bounded.archive.metadata({"dtype": "<f4", "shape": [32, 2, 40, 20001],
                                      "nbytes": 32 * 2 * 40 * 20001 * 4, "sha256": "0" * 64})

    def test_full_204800000_byte_stream_and_rehash(self):
        # Anonymous zero pages are a synthetic source. Transfer and verification
        # use the real 195.3125 MiB shape without allocating a full bytes copy.
        with tempfile.TemporaryDirectory(prefix="real-size-array-test-") as temporary:
            root = Path(temporary).resolve()
            mapping = mmap.mmap(-1, 204800000)
            array = np.ndarray((32, 2, 40, 20000), dtype="<f4", buffer=mapping)
            digest, count, peak = hashlib.sha256(), 0, 0
            try:
                path = root / "000.bin"
                with path.open("xb") as stream:
                    for chunk in bounded.archive.array_chunks(array):
                        stream.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                        peak = max(peak, len(chunk))
                    stream.flush()
                    os.fsync(stream.fileno())
                path.chmod(0o600)
                self.assertEqual(count, 204800000)
                self.assertLessEqual(peak, 1048576)
                fd = bounded.archive.directory(root)
                try:
                    read = sum(len(c) for c in bounded.archive.chunks(fd, "000.bin", count, digest.hexdigest()))
                finally:
                    os.close(fd)
                self.assertEqual(read, count)
            finally:
                del array
                mapping.close()


if __name__ == "__main__":
    unittest.main()
