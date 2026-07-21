# Silence / effective-SNR audit

This analysis checks the distinction between the nominal SNR set from each
complete 2.5 s waveform and the effective SNR in the central 2.0 s retained by
the model front end.

Run from the repository root:

```bash
conda run -n audattn python reproduction/analysis/silence_snr_audit.py
```

Use `--limit 5` for a quick smoke test. Set `CV_CLIPS` or pass `--audio-dir`
when the Common Voice clips are stored elsewhere.

Outputs are written to `reproduction/analysis/silence_snr/`:

- `stimulus_snr_audit.csv`: trial-level effective-SNR diagnostics;
- `distractor_pool_silence_audit.csv`: exact energy diagnostics for Experiment
  2's saved anchored distractor pool;
- `silence_snr_summary.csv`: condition-level statistics;
- `silence_snr_audit.png`: presentation-ready distributions;
- `PPT_SNR説明_日本語.md`: Japanese interpretation and a short oral answer.

Experiment 1 can be reconstructed exactly from its manifest. Experiment 2's
final result file does not save masker IDs. Its multi-talker audit therefore
reconstructs the documented gender-balanced, nested design with seed 0 and
labels every such row accordingly. It excludes ISSN because the saved files do
not contain enough information to reproduce those exact noises.
