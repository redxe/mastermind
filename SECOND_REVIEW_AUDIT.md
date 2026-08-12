# Second review audit — independent adversarial pass (2026-08-11)

> Historical record. References to "Appendix C" below denote the reproducible demonstration appendix, which is lettered Appendix B in the current manuscript.

Five-perspective audit of Version 0.2 (post first revision). Severity: **B** blocking, **M** major, **Mo** moderate, **E** editorial.

Epistemic categories used below: [T] established theorem · [EA] engineering approximation · [EE] empirical evidence · [AS] author synthesis · [PH] provisional hypothesis · [AN] analogy.

## Blocking

| # | Criticism | Section/Eq | Why a reviewer objects | Evidence/calculation needed | Correction | Status |
|---|---|---|---|---|---|---|
| B1 | **eq:hoeffding is wrong by a factor of 4.** For an observable bounded in $[-1,1]$ the range is 2, so Hoeffding gives $N \ge 2\ln(2/\delta)/\epsilon^2$, not $\ln(2/\delta)/(2\epsilon^2)$ (which is correct only for range 1). | §4, eq:hoeffding | A theorist checks this in one line; a wrong concentration bound in a paper about calculational discipline is disqualifying. | Independent derivation + numeric check (scripts/verify_calculations.py) | Corrected to $2\ln(2/\delta)/\epsilon^2$; grouped formula eq:worstcase-shots re-verified (it was already correct for range $2a_g$) | ✅ |
| B2 | No numerical claim in §4 was machine-verified. | §4 worked examples | "Every number reproducible" is the paper's own standard. | Executable script reproducing $P_0$, $d$, 881, $5.9\times10^6$, $3.8\times10^4$, times | scripts/verify_calculations.py added; all printed values match manuscript | ✅ |
| B3 | The paper demands an end-to-end audit but contains none. | §8 | The framework's value claim is untested by its own gate 5. | Executed demonstration on a solvable instance | scripts/demo_tfim_audit.py: 4-qubit transverse-field Ising model audit (exact diagonalization, grouping, simulated sampling, shot-formula empirical check, toy noise screen); reported in new Appendix C with actual outputs. This validates the *procedure*, claims no advantage. | ✅ |

## Major

| # | Criticism | Section/Eq | Why | Needed | Correction | Status |
|---|---|---|---|---|---|---|
| M1 | Hoeffding vs. Neyman comparison mixes guarantee types: Hoeffding is finite-sample and distribution-free [T]; the Neyman/normal figure is asymptotic and requires variance estimates [EA]. Presenting the $155\times$ gap without saying so overstates the "savings." | §4, eq:worstcase-shots vs eq:neyman-shots | Statistician's objection: unequal confidence semantics. | Text distinguishing guarantee strength; pilot-shot cost accounting | Paragraph added: guarantee semantics differ; pilot estimation cost $G N_{\text{pilot}}$ must be added; empirical coverage checked in demo script | ✅ |
| M2 | 2 ms/shot is asserted without source; shot time is platform-dependent (superconducting ~µs–ms with reset; trapped-ion much slower). | §4 | Experimentalist objection. | Label as assumption with plausible range | Labeled an assumption; sensitivity to shot time noted (linear) | ✅ |
| M3 | Abstract says the framework "is applied to" seven domains; §8–10 are audits of framings, not applications. | Abstract | Overclaim vs. §8's own disclaimer. | none | Abstract reworded to "used to audit proposed framings in..." + demonstration sentence added | ✅ |
| M4 | Computational model scope never stated: gate-model only? Annealing appears in §3's table; sensing in §10. | §1 | Editor objection: scope ambiguity. | none | Scope paragraph added to Contributions: gate-model primary; annealing/analog/sensing require separate resource contracts | ✅ |
| M5 | "This is a genuine quantum opportunity" (§9) and "strongest conceptual matches" are [AS]/[PH] presented as fact. | §9 | Domain-scientist objection. | none | Rephrased as conditional, mechanism-based statements | ✅ |
| M6 | The §2 procedure is prose; the paper promises a usable decision procedure with stop conditions and outputs. | §2 | Practitioner cannot execute it. | none | Recast as "Algorithm 1: Quantum Opportunity Audit" (tcolorbox float) with inputs, ordered gates, calculations, stop conditions, and four outputs: `proceed` / `reframe` / `classical-only` / `insufficient-evidence` | ✅ |
| M7 | No claim–evidence mapping; reviewer cannot tell which conclusions rest on theorems vs. synthesis. | global | Editor objection. | none | Claim–evidence matrix added to §13 with category labels [T]/[EA]/[EE]/[AS]/[PH] | ✅ |
| M8 | Citation metadata never verified against sources. | bib | Fabrication risk. | Web verification | Load-bearing entries verified (see SOURCE_VERIFICATION.md); unverifiable-from-here entries flagged there, none found contradicted; no new citations invented | ✅ |

## Moderate

| # | Criticism | Section | Correction | Status |
|---|---|---|---|---|
| Mo1 | Neyman formula assumes measured $\sigma_g$; rounding $\lceil N_g\rceil$ and the constraint $N_g\ge$ pilot floor not mentioned. | §4 | One sentence added; script uses ceil | ✅ |
| Mo2 | DNA audit lacks a quantitative rejection: the framework should be *shown* rejecting it. | §8 | Rejection case added to demo script (QFT-sampling vs. FFT cost at $N=4096$) and one sentence citing Appendix C | ✅ |
| Mo3 | Repeated caveat: "screening model, not a warranty" appears in §4 (twice), §13, §15. | §4/§13/§15 | Deduplicated; §4 warningbox is the canonical statement, §15 references it | ✅ |
| Mo4 | eq:tts assumes independent Bernoulli trials with stationary $p_s$; drift (§5) contradicts stationarity. | §4 | Assumption stated inline | ✅ |
| Mo5 | Related-work table calls MQT Bench "benchmarking"; it is benchmark *circuit provision*, not crossover analysis. | §2 (related work) | Wording tightened | ✅ |
| Mo6 | "The demonstration must not be conflated with hardware evidence" — demo uses classical simulation of an ideal + toy-noise device. | App. C | Stated explicitly in Appendix C | ✅ |

## Editorial

| # | Item | Status |
|---|---|---|
| E1 | "we need"/"we do not need" in §1 — acceptable (addresses community); retained deliberately | ✅ |
| E2 | PSD, RB, FFT, MIP acronym first-use check | ✅ (MIP expanded in §2 baseline protocol) |
| E3 | Title: current title signals perspective adequately; subtitle already does framework work. Proposal (optional, author's call): "Where the Quantum Work Actually Is: A Resource-Bounded Audit Framework for Proposed Quantum Applications." Left as TODO for Vi. | 🔶 |
| E4 | Historical section interrupts Part IV flow — acceptable as-is since Part IV is synthesis; Pauli folklore already compressed. No further move. | ✅ |
| E5 | Submission placeholder check: title-page footer TODO (ORCID/URL) retained as visible author TODO | ✅ |

## Category discipline check (Phase 1 requirement)

- Hoeffding, Grover quadratic bound, HHL readout limits: [T] — cited.
- $P_0$ screen, $p_L(d)$ scaling, eq:distance: [EA] — labeled toy/screening in text.
- Below-threshold surface-code scaling: [EE] — cited (acharya2025).
- The audit framework itself, hybrid partition objective, five gates: [AS] — now stated in Contributions.
- Astronomy ranking, DNA relational abstraction: [PH] — labeled provisional/hypothesis.
- Feynman drawer: [AN] — labeled "the analogy is almost too convenient," retained.
