# Kingston Two-Day Prediction Protocol — SPECIFIED, NOT EXECUTED

Status: **frozen design, awaiting QPU allocation.** This document specifies the
combined calibration-conditioned-prediction (rank 1) and drift-statistics (rank 4)
hardware experiment so the next `ibm_kingston` allocation produces reusable research
data. Do not execute before this file and the prediction artifact format are committed.

## Design principle

Temporal separation is what turns calibration fitting into prediction: all model
fitting uses day-1 data only; a locked, committed prediction artifact is produced
before day 2; day-2 execution is held-out validation. A model that explains day 1
is post hoc fitting; a model that predicts day 2 with calibrated coverage is research.

## Day 1 — training and pilot

1. **Calibration snapshot** at session start and end: full backend properties
   (T1, T2, gate errors, readout errors, frequencies), timestamps, provenance.
2. **Randomized execution blocks** (order randomized within each block):
   - Control circuits: the 4-qubit TFIM audit circuits from
     `scripts/hw_tfim_audit.py` (seeded transpile, `--backend-name ibm_kingston`),
     matched to the existing `artifacts/hardware/hardware_ibm_kingston` run.
   - Application circuits: the same TFIM observables under **3 qubit mappings ×
     3 transpiler seeds** (all enumerated in the sealed contract, not chosen ad hoc).
   - Noise probes: idle-decay, readout, and paired RB-style probes interleaved
     between application circuits within each block.
3. **Blocking:** ≥ 8 blocks spread across the session; identical block structure;
   per-block timestamps retained for drift estimation.
4. **Provenance:** compilation trace, physical layout, schedule, shot partitions,
   and job ids archived under `artifacts/hardware/kingston_day1/` with SHA256SUMS.

## Between days — the locked prediction artifact

Before any day-2 job is submitted, commit `artifacts/hardware/kingston_prediction.json`:

- For each day-2 circuit (including **held-out mappings/seeds not run on day 1**):
  predicted observable bias, predicted total-variation distance, and a **95%
  prediction interval** for each observable.
- An **abstention list**: circuits the model declines to predict, with the
  out-of-distribution rule that triggered abstention.
- The model definition, its day-1 training inputs (by hash), and the git commit.
- Sealed with `scripts/evidence_contract.py`-style hashing; the commit must be
  pushed before day 2.

## Day 2 — held-out validation (target: ≥ 48 h after day 1)

1. Same block structure; includes the held-out mappings/seeds and, if available,
   a later calibration window than any training data.
2. No model refits. No prediction edits. Any deviation is logged and the affected
   circuits are excluded from coverage scoring (not silently re-predicted).

## Scoring (declared now)

- **Coverage:** fraction of day-2 observables inside their 95% prediction
  intervals; success band declared in advance: [0.90, 0.99]. Below → model
  miscalibrated; above → intervals uninformatively wide (also reported).
- **Sharpness:** mean interval width, reported alongside coverage.
- **Abstention quality:** error rate on abstained circuits vs predicted circuits
  (abstention should concentrate the worst errors).
- **Drift:** hierarchical model on block-level control/probe results; report
  run-to-run and within-session variance components separately from shot noise.
- All uncertainties reported per the rank-4 statistics contract: shot noise,
  run-to-run, calibration, and drift — never shot noise alone.

## Budget

- 2 device-days (sessions), ~30k shots/day within existing allocation limits.
- Fallback if only one session is granted: split one session into two halves
  separated by a recalibration boundary; report as a weakened within-day variant
  and do not present it as the two-day protocol.

## Relation to existing artifacts

Day-1 control circuits reproduce the published `hardware_ibm_kingston` audit,
giving a direct replication datum for the Mastermind Appendix C deferred
experiment (matched snapshot + interleaved blocks) at zero extra cost.
