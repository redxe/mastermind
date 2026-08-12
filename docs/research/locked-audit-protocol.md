# Locked Audit Protocol — Evidence Contracts for Quantum-Work Claims

Status: **DRAFT — pilot phase.** This document becomes immutable when sealed with
`scripts/evidence_contract.py seal-protocol`. After sealing, any change requires a new
protocol version and invalidates no existing sealed contracts (they reference the hash
they were sealed under).

## 1. Purpose

Audit whether a quantum-vs-classical or quantum-work claim remains supported when the
experimental choices that *should not matter* are varied, using a contract frozen and
hash-sealed **before** any outcome-bearing evaluation. This is prospective auditing: the
differentiator from retrospective rubrics (e.g. CLAIMSTAB-QC) is that the contract is an
executable artifact with full-stack provenance, sealed before results exist.

## 2. What is frozen, and when

Everything below is frozen at seal time. The seal covers the SHA-256 of this document,
the schema, the corpus manifest, and every contract file.

1. **Claim corpus and selection/exclusion rules** — `docs/research/claim-corpus-manifest.yaml`.
   No claim may be added, dropped, or reworded after sealing except through the amendment
   log (§7), and dropped claims are still reported as Not Auditable with the drop reason.
2. **Exact claim / estimand** — one sentence + one computable estimand per contract.
3. **Baseline-escalation policy** — per contract: initial baseline, triggers, escalation
   targets, and whether the strongest known classical baseline is mandatory. A claim
   evaluated only against a knowably-weak baseline is at best Conditionally Stable.
4. **Workload and resource budget** — instance definition, generator script, quantum shot /
   device budget, classical wall-clock budget.
5. **Metrics and equivalence tolerances** — computable definitions with absolute, relative,
   or standard-error tolerances.
6. **Allowed variations** — an explicit, enumerated list of compiler, seed, mapping, noise,
   mitigation, backend, and calibration-window values. Nothing open-ended.
7. **Statistical decision rules** — alpha, multiple-comparison correction, mandatory
   uncertainty sources, per-variation verdict rule, aggregation rule (`standard-v1`).
8. **Missing-evidence handling** — required artifact classes and whether absence voids the
   audit or only the variation.
9. **Outcome taxonomy** — Stable, Conditionally Stable, Unresolved, Reversed, Not Auditable
   (definitions in §5). Fixed; embedded in every contract.
10. **Software/environment identities** — git commit, Python version, pinned package
    versions for everything that can influence results.

## 3. Procedure

1. Author contracts (`*.yaml`) validating against
   [evidence-contract.schema.json](../../specs/evidence-contract.schema.json).
2. Run `evidence_contract.py validate` on every contract.
3. Run `evidence_contract.py seal-protocol` to produce
   `specs/protocol-seal.json` containing hashes and a timestamp. Commit it.
4. Only after the seal is committed and pushed may outcome-bearing computations be
   evaluated against contracts.
5. Record results per variation in a results file; run `evidence_contract.py evaluate`.
6. Publish contract + seal + results + evaluation together as the evidence bundle.

## 4. Per-variation verdicts

For each enumerated variation combination:

- **supported** — every metric with `required_for_support: true` is within tolerance,
  all mandatory uncertainty sources are quantified, and the estimand agrees with the
  claim's direction at the declared confidence level.
- **reversed** — the estimand contradicts the claim's direction at the declared
  confidence level with all mandatory uncertainty sources included.
- **indeterminate** — anything else: tolerance failures without a confident reversal,
  missing non-fatal evidence, or unquantified mandatory uncertainty.

## 5. Aggregation (`standard-v1`)

| Condition | Outcome |
|---|---|
| Any required artifact missing (policy `not-auditable`) | Not Auditable |
| All variations supported | Stable |
| Some supported, none reversed | Conditionally Stable |
| Some supported, some reversed | Unresolved |
| None supported, at least one reversed | Reversed |
| None supported, none reversed | Not Auditable |

**Baseline-escalation consequences** (two intentionally distinct conditions):

- If the contract declares `strongest_known_required: true`, the strongest known
  classical baseline is **mandatory for auditability**: an escalation trigger that
  fires and is not honored makes the claim **Not Auditable**, regardless of the
  per-variation verdicts.
- If `strongest_known_required: false`, the stronger baseline is recommended but
  not mandatory: an unhonored trigger **caps the outcome at Conditionally
  Stable** and must be reported.

Both cases must appear in the published evaluation report.

## 6. Pilot then expansion

- **Phase A (pilot):** 8–12 claims to validate the schema, CLI, and taxonomy. Claim 0 is
  the Mastermind TFIM/free-fermion correction — chosen because it demonstrates why
  baseline escalation belongs *inside* the contract (dense diagonalization vs the exact
  Pfeuty free-fermion solution reverses the scaling narrative).
- **Phase B:** freeze the final protocol version, then expand to 20–40 claims across
  quantum simulation, optimization, and error mitigation. No Phase A claim may be
  re-scored under Phase B rules.

## 7. Amendment log

Amendments after sealing are append-only entries here, each with date, reason, and the
new protocol hash. Results obtained under an earlier hash are never re-evaluated under a
later one.

*(no amendments)*
