"""Shared indexing rules for valid target/cue anchor pairs."""

from __future__ import annotations

import numpy as np
import pandas as pd


def cue_eligible_target_mask(anchors: pd.DataFrame) -> np.ndarray:
    """Return rows that have a same-speaker, different-file/word cue.

    A speaker having two paths and two words is not sufficient by itself.  For
    example, rows ``(path_a, word_x)``, ``(path_a, word_y)`` and
    ``(path_b, word_x)`` leave the first row without a cue that differs in both
    path and word.  Inclusion/exclusion counts compute the exact row-level rule
    in linear time.
    """

    speaker_size = anchors.groupby("speaker", sort=False)[
        "speaker"
    ].transform("size")
    same_path = anchors.groupby(
        ["speaker", "path"], sort=False
    )["speaker"].transform("size")
    same_word = anchors.groupby(
        ["speaker", "norm"], sort=False
    )["speaker"].transform("size")
    same_path_word = anchors.groupby(
        ["speaker", "path", "norm"], sort=False
    )["speaker"].transform("size")

    eligible_cue_count = (
        speaker_size - same_path - same_word + same_path_word
    )
    return eligible_cue_count.to_numpy() > 0
