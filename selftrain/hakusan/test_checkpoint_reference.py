"""Regression tests for exact resume-checkpoint handoff."""

from __future__ import annotations

import pathlib
import tempfile
import unittest

import torch

from selftrain.hakusan.checkpoint_reference import (
    lock_reference,
    verify_reference,
)


class CheckpointReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = pathlib.Path(self.temporary_directory.name)
        self.old = self.directory / "last.ckpt"
        self.new = self.directory / "last-v1.ckpt"
        torch.save({"global_step": 7813}, self.old)
        torch.save({"global_step": 31252}, self.new)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_explicit_versioned_checkpoint_is_not_reselected(self) -> None:
        reference = lock_reference(self.directory, "epoch", "last-v1.ckpt")
        self.old.touch()
        verified = verify_reference(
            self.directory,
            "epoch",
            reference["basename"],
            reference["sha256"],
            reference["global_step"],
        )
        self.assertEqual(verified["basename"], "last-v1.ckpt")
        self.assertEqual(verified["global_step"], 31252)

    def test_content_mutation_is_rejected(self) -> None:
        reference = lock_reference(self.directory, "epoch", "last-v1.ckpt")
        torch.save({"global_step": 31253}, self.new)
        with self.assertRaises(RuntimeError):
            verify_reference(
                self.directory,
                "epoch",
                reference["basename"],
                reference["sha256"],
                reference["global_step"],
            )

    def test_unsafe_basenames_are_rejected(self) -> None:
        for basename in (
            "../last.ckpt",
            "last-v0.ckpt",
            "last-v1.ckpt,MODE=new",
            "epoch=3.ckpt",
        ):
            with self.subTest(basename=basename), self.assertRaises(
                (ValueError, FileNotFoundError)
            ):
                lock_reference(self.directory, "epoch", basename)

    def test_symbolic_link_is_rejected(self) -> None:
        link = self.directory / "last-v2.ckpt"
        link.symlink_to(self.new.name)
        with self.assertRaises(ValueError):
            lock_reference(self.directory, "epoch", link.name)

    def test_resume_kind_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            lock_reference(
                self.directory, "best-effort-rolling", "last-v1.ckpt"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
