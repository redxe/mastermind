# CHUBE Prospective Experiment Specification

**Status: PROPOSED / NOT EXECUTED.** No runs have been performed; this document
contains no performance results and must not acquire any until a CHUBE evidence
contract has been authored, validated, and sealed under
[docs/research/locked-audit-protocol.md](../docs/research/locked-audit-protocol.md).
Architecture definitions: [docs/research/chube-architecture.md](../docs/research/chube-architecture.md).

## Primary research question (conservative by construction)

> Does a phase-encoded overlapping-window quantum filter with shared Hamiltonian
> updates and optional coherent memory provide a useful inductive bias for
> structured symbolic sequence tasks relative to matched classical and
> tensor-network models?

Improved accuracy alone is **not** "quantum advantage." Decision language is
fixed now:

- CHUBE beats matched CNN/GRU/transformer but not matched MPS → report as an
  **architectural/inductive-bias result**.
- CHUBE beats all matched baselines including MPS at matched effective memory →
  report as an inductive-bias result **plus** an open simulability question;
  still not an advantage claim.
- Any advantage-flavored claim requires a separate, sealed evidence contract
  with a strongest-known-baseline escalation policy.

## Models compared

| Model | Register | Execution |
|---|---|---|
| Stateless CHUBE filter (variant A) | 8 qubits | exact simulation |
| Recurrent CHUBE (variant B) | 8 qubits (m memory + 8−m data) | exact density-matrix simulation |
| Fully coherent sweep (variant C) | 14 qubits | exact statevector simulation |
| Classical 1D CNN | — | matched parameter count |
| GRU | — | matched parameter count |
| Restricted transformer | — | matched parameter count |
| MPS/tensor-network sequence model | — | bond dimension matched to 2^m (variant B) and to declared compression (variant C) |

"Matched" means: parameter count within ±10%, identical training data, identical
optimizer budget (steps × batch), and, for the MPS baseline, effective memory
matched to the quantum model's memory register (bond dimension χ = 2^m).

## Tasks

Synthetic symbolic sequence tasks over 14-bit inputs (extended lengths for
length-generalization), each with exact ground truth:

1. Valid-vs-corrupted algebraic rewrite classification (tokenized to bits).
2. Next-rewrite selection from a finite candidate set.
3. Boolean-expression equivalence.
4. Modular/parity/periodic relations crossing window boundaries.
5. Tactic ranking on short formally verified proof states (stretch goal; only
   if the token encoding is settled per architecture §5).

## Required ablations

1. Computational-basis vs |+⟩/|−⟩ phase encoding.
2. Shared vs position-dependent parameters (weight sharing on/off).
3. Stateless (A) vs persistent memory (B).
4. Fixed vs translated Hamiltonian (sweep vs single-position update).
5. With vs without reversible workspace uncomputation before reset (B).
6. Memory/data register splits m ∈ {1, 2, 3, 4}.
7. Noiseless vs declared noise models (depolarizing + readout at declared
   rates; no hardware execution in this phase).

## Required metrics

- Held-out accuracy.
- Shift generalization (train on window positions/offsets, test on shifted
  inputs).
- Length generalization where the task defines it (train at 14 bits, test at
  18/22 with the same shared filter).
- Sample efficiency (accuracy vs training-set size curves).
- Gradient variance / trainability (variance of parameter-shift gradients vs
  depth and width; barren-plateau diagnostics).
- Shot cost to reach declared accuracy under sampled (non-exact) readout.
- Circuit depth and two-qubit-gate count after compilation to a declared basis.
- Noise robustness (accuracy degradation under the declared noise models).
- Classical simulation cost of each quantum variant (wall-clock and asymptotic).
- All comparisons at matched parameter and compute budgets.

## Statistical discipline

- Train/validation/test splits, seeds, and hyperparameter grids frozen in the
  evidence contract before any outcome-bearing run.
- ≥ 10 seeds per configuration; report medians with bootstrap intervals.
- Multiple-comparison correction across tasks and ablations (per the
  evidence-contract decision rules).
- Negative and null results are reported with the same prominence as positive
  ones.

## Execution preconditions (all must hold before any outcome-bearing run)

1. CHUBE evidence contract authored, validated against
   [evidence-contract.schema.json](evidence-contract.schema.json), and sealed.
2. Reference implementation tests green in CI.
3. Task generators committed with fixed seeds and hashed artifacts.
4. Baseline implementations committed and matched-budget verification script in
   place.

None of these preconditions are currently claimed as satisfied except where CI
says so.
