# PILOT4 Scientific Review

  - review_schema: audattn-pilot4-human-review-v1
  - reviewer: s2510040
  - reviewed_date_jst: 2026-09-30
  - run_id: formal40_newseed20260928_20260929
  - training_job_id: 757211
  - evaluation_job_id: 759658
  - evaluator_engineering_status: PASS
  - evaluator_decision: GO
  - all_seven_gates_true: yes
  - per_trial_rows: 10000
  - partial_artifacts_present: no
  - reviewer_decision: APPROVE_FULL_CONTINUATION

  ## Evidence reviewed

  - PILOT4_COMPLETE: completed_epochs=4, global_step=6944
  - PILOT4_EVAL SHA256: 126e2e818b043ea34dfdb96dd81464bb34d5e8edf7dded563b44cc23bba967b2
  - per_trial_results SHA256: d37e846ee43f63010ba5add079005c6359e7bc03860a6ea3e3d9920c1b4dd6ba
  - frozen_bank SHA256: d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091
  - pilot4-final checkpoint SHA256: c0cf676757afb4d337a161631e7626e3148e12d5e478d9da6faad35515737764
  - Slurm evaluation: COMPLETED, ExitCode=0:0 (job 759658; the earlier attempt 759391 failed before producing any result because ldconfig was missing from the submission PATH)

  ## Scientific findings

  - Overall accuracy improved from 0.09% to 33.69%.
  - Mixed-only accuracy improved from 0.100% to 30.544%.
  - Clean accuracy reached 62.00%.
  - Correct cue accuracy was 30.40%.
  - Shuffled cue accuracy was 14.15%.
  - Silent cue accuracy was 21.00%.
  - Correct cue exceeded the strongest control by 9.40 percentage points.
  - All seven preregistered gates passed.

  ## Limitations acknowledged

  - The lowest SNR bin reached only 12.00%.
  - Performance decreased under multiple distractors.
  - Female and male target accuracy differed by 6.06 percentage points and requires further investigation.
  - This is a single-seed validation-bank pilot decision, not final test performance.
  - This run is the new-seed replicate (seed 20260928) of formal40; before seeing this evaluation the user had already decided to continue to 40 epochs even if a gate failed.

  ## Decision

  I reviewed the frozen 10,000-trial evaluation and approve continuation from pilot4-final.ckpt to the full phase.
