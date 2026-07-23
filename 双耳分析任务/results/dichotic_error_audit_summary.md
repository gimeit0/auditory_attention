# Dichotic error and central-two-second acoustic audit

## Scope and method

- Valid trials audited: 440
- Error trials queued for manual review: 93
- RMS was measured after the same full-2.5-second normalization used by the evaluation, followed by the model's central-2-second crop.
- The low-energy value is the fraction of 20-ms frames below -40 dB of that crop's peak frame RMS. It is an energy proxy, not VAD.
- These diagnostics do not alter the primary exact-word score.

## Error decomposition

- Baseline and dichotic errors: 40
- Dichotic-specific errors: 53
- Opposite-ear confusions: 0
- Error strings with target/prediction similarity >= 0.8: 13/93
- Baseline errors repeating the same wrong diotic prediction: 25/40

## Effective central-two-second level

- Median cued-minus-opposite level: +0.00 dB
- Central 95% range: -1.79 to +1.79 dB
- Absolute imbalance > 1 dB: 112/440
- Absolute imbalance > 2 dB: 12/440
- Signed effective level vs hit: Spearman rho=0.042, p=0.385
- Absolute effective gap vs hit: Spearman rho=0.122, p=0.010

Interpretation: the AB/BA and left/right swaps make the signed level distribution symmetric. There is no evidence that a louder cued central crop explains the overall result. Absolute-gap associations are descriptive and confounded with recording/word difficulty.

## Cue low-energy proxy and speaker clustering

- Cue low-energy fraction vs errors per speaker: Spearman rho=0.074, p=0.444
- Speakers by number of dichotic errors out of four: 0 errors: 63 speakers, 1 errors: 14 speakers, 2 errors: 25 speakers, 3 errors: 3 speakers, 4 errors: 5 speakers

Interpretation: the energy proxy does not show that cue silence is the main error source. Manual listening is still required for alignment, audibility, transcription and recording-quality judgements.

## Manual-review rule

Review the CSV in `review_order`. Keep the original 440-trial primary result unchanged. Any exclusion must use an objective audio/alignment criterion defined independently of the model prediction; normalized-label results, if reported, must be a separate sensitivity analysis.
