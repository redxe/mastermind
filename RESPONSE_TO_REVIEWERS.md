# Response to reviewers — simulated memorandum (Version 0.2 → 0.3)

> Historical record. References to "Appendix C" below denote the reproducible demonstration appendix, which is lettered Appendix B in the current manuscript (the former notation appendix was removed from the compiled composition in a later pass).

Dear Editor and Reviewers,

Thank you for the detailed critique. Below, point by point, is what changed, what evidence backs each change, and what remains open. All line references are to the rebuilt PDF; all numbers are reproducible from `scripts/` in the artifact.

## Mathematics (P0)

1. **"The shot calculation does not control the total energy error."** Agreed. Section 4 now builds the estimator $\hat H=\sum_g\hat\mu_g$ over commuting groups, derives the grouped variance, and gives two correct allocations: a finite-sample union-bound Hoeffding budget (eq. worstcase-shots, ≈5.9×10⁶ shots for the toy instance) and an asymptotic Neyman allocation (eq. neyman-shots, ≈3.8×10⁴). During the second internal audit we additionally found and fixed a factor-of-4 error in the single-observable Hoeffding bound (range 2, not 1). The two allocations' differing guarantee semantics, pilot-variance cost, and rounding are now stated, and their empirical coverage (1.000 and 0.938 vs. a 0.95 target) was measured in the reproducible demonstration (Appendix C).
2. **"The complete-time equation multiplies the wrong things."** Replaced by a one-time / per-iteration / per-circuit / per-shot ledger (eq. complete-ledger) with every symbol defined and amortizable terms identified; state preparation now sits explicitly inside the innermost multiplier.
3. **"The error budget imposes no budget."** Now two inequalities (triangle bound and budget constraint) plus an explicit union bound for failure probabilities, with correlated-error and quadrature caveats.
4. **"$P_0$ is not a fidelity."** Relabeled a toy triage model; independent-stochastic-Pauli assumption, RB-substitution and coherence double-counting failure modes stated; channel-level simulation recommended for serious work.
5. **"881,000 qubits is not a resource estimate."** Now labeled an idealized memory-only floor; $c_d$, $\tau_L$, $D_{\mathrm{dep}}$ defined; sensitivity discussion added; a full estimate is deferred to an established estimator run (explicit TODO — we will not quote tool output we have not produced).

## Validation

6. **"The framework is never applied."** Appendix C now reports a complete, seed-fixed, NumPy-only execution of Algorithm 1 on a 4-qubit transverse-field Ising instance (correctly returning `classical-only`) and a quantitative rejection of the DNA phase-encoding proposal at its most favorable operating point. This validates the procedure and the shot mathematics; it is explicitly *not* hardware evidence, and the hardware-scale protocol remains a TODO in §8.

## Framing and scope

7. Contributions and scope subsection added; genre stated (perspective/framework; no new speedup theorem); gate-model scope declared; annealing/analog/sensing excluded pending their own resource contracts.
8. Related-work section and comparison table added (selective, and labeled as such). Claim–evidence matrix added to §13 distinguishing theorems, engineering approximations, empirical evidence, synthesis, and provisional hypotheses.
9. "Genuine quantum opportunity," "strongest matches," and the astronomy ranking are now either conditioned on the audit gates or labeled the author's provisional assessment under stated criteria.

## Domains

10. DNA: relative vs. global phase distinguished; QFT output distribution derived; loading vs. FFT cost made quantitative (Appendix C). Scheduling: retained as a warning vignette with the full formulation marked TODO. HEP: rhetoric removed; bounded-model instantiation marked TODO. Gravitational waves: inner product replaced by the noise-weighted form with $S_n(f)$ defined.

## Bibliography

11. Load-bearing entries verified against arXiv/DOI on 2026-08-11 (SOURCE_VERIFICATION.md). Four corrections: Beverland et al. author name; van Dam et al. title and venue (unverified journal claim removed); Brunet et al. upgraded to the published Astronomy and Computing version; the NQI workshop report's real author list and title restored. No citation was added without verification.

## What we did not do

We did not run a hardware experiment, an established resource estimator, or a systematic literature review; the manuscript says so where it matters and the revision record lists every remaining gap. We prefer a visible TODO to a confident sentence we cannot back.

> **Postscript (2026-08-11, after this memorandum was written):** the first two items above have since been executed and archived — an independent Qiskit cross-validation, a calibrated-noise simulation, a single uncorrected physical run on IBM `ibm_kingston` (one four-qubit, classically solvable instance; shot-noise-only uncertainty), a local Azure Quantum Resource Estimator sweep (labeled a synthetic sensitivity scenario, not an application estimate), and a bounded Schwinger-model instantiation. See REVISION_RECORD.md third and fourth passes. What remains open is listed there: validation on a genuinely uncertain instance, a controlled model-versus-device comparison, systematic-uncertainty characterization, and error-mitigated/corrected performance.

Sincerely,
Vi Connelly
