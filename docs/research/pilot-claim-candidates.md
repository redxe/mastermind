# Pilot-Claim Candidate Selection Memo

**Status: RECOMMENDATIONS ONLY.** No corpus-manifest changes have been made.
Vi must approve selections before any placeholder in
[claim-corpus-manifest.yaml](claim-corpus-manifest.yaml) is replaced. Sealing
remains blocked until all seven external slots are resolved. Nothing here has
been recomputed; all budget/feasibility entries are estimates.

Citation caution: sources are quoted from memory of the literature and MUST be
re-verified against the primary documents (DOI/arXiv) before corpus entry.

---

## Slot: quantum simulation (2 slots, 4 candidates)

### QS-1. IBM "utility" kicked-Ising claim
- Claim (paraphrase): error-mitigated estimates of ⟨Z⟩-type observables on a
  127-qubit kicked transverse-field Ising circuit are accurate in regimes where
  "brute-force" classical methods fail, evidencing utility before fault tolerance.
- Source: Kim, Eddins et al., *Evidence for the utility of quantum computing
  before fault tolerance*, Nature 618, 500–505 (2023). doi:10.1038/s41586-023-06096-3.
- Estimand: magnetization/weight-k observable values vs classical reference at
  declared Trotter depths.
- Strongest known baseline: post-publication tensor-network and Pauli-path
  simulations (Begušić & Chan; Tindall et al. 2023–24) that reproduced the
  observables cheaply — a *documented, already-executed escalation*, ideal for
  the taxonomy.
- Escalation trigger: existence of sparse-Pauli/BP-MPS methods for this circuit family.
- Artifacts: circuits and mitigation described in paper/SI; raw data partially
  public. Public enough: likely yes.
- Budget: classical only, hours on a workstation with published methods. No QPU.
- Exclusion risk: low. Reproduction feasible: high.

### QS-2. D-Wave quantum-annealer glassy-dynamics simulation claim
- Claim (paraphrase): quantum annealers simulate quench dynamics of spin
  glasses in regimes beyond the reach of classical tensor-network methods.
- Source: King et al., *Beyond-classical computation in quantum simulation*,
  Science (2025). doi:10.1126/science.ado6285 (verify).
- Estimand: correlation functions / residual energy vs matched MPS/PEPS baselines.
- Strongest known baseline: post-publication rebuttal simulations (e.g.
  Mauron & Carleo; Tindall et al. 2025 claims of classical reproduction).
- Escalation trigger: any published classical method reproducing the reported
  observables at matched accuracy.
- Artifacts: partial; device access proprietary. Public enough: marginal —
  audit would be of the *comparison*, not a rerun of the annealer.
- Budget: classical only, potentially large (days of GPU). No QPU.
- Exclusion risk: medium (artifact access). Reproduction: partial only.

### QS-3 (reserve). Google random-circuit-sampling beyond-classical claim
  (Arute et al., Nature 574, 505 (2019)) — well-trodden; classical spoofing
  literature is mature; mainly useful as a calibration claim for the taxonomy.
### QS-4 (reserve). Trapped-ion/analog Schwinger-model dynamics claims — closer
  to Mastermind's HEP section but artifacts are usually not public; higher
  exclusion risk.

**Recommendation:** QS-1 and QS-2 (one sustained-vs-reversed pair with strong
public classical baselines).

---

## Slot: optimization (2 slots, 4 candidates)

### OPT-1. Rydberg maximum-independent-set speedup claim
- Claim (paraphrase): Rydberg atom arrays show superlinear speedup over
  simulated annealing on hard MIS instances on unit-disk graphs.
- Source: Ebadi et al., *Quantum optimization of maximum independent set using
  Rydberg atom arrays*, Science 376, 1209 (2022). doi:10.1126/science.abo6587.
- Estimand: time-to-solution / approximation-ratio scaling vs instance hardness
  parameter, against declared classical solvers.
- Strongest known baseline: post-publication classical analyses (e.g. Andrist
  et al. 2023, PRR) showing improved classical heuristics narrow or remove the gap.
- Escalation trigger: any classical heuristic with better scaling on the same
  instance ensemble.
- Artifacts: instance graphs partially published; device data not rerunnable.
- Budget: classical only, moderate. No QPU. Exclusion risk: medium.

### OPT-2. QAOA LABS scaling-advantage claim
- Claim (paraphrase): QAOA exhibits a scaling advantage over the best known
  classical heuristic for the Low Autocorrelation Binary Sequences problem
  (evidence from simulation + trapped-ion execution).
- Source: Shaydulin et al., *Evidence of scaling advantage for the quantum
  approximate optimization algorithm on a classically intractable problem*,
  Science Advances 10, eadm6761 (2024). doi:10.1126/sciadv.adm6761 (verify).
- Estimand: fitted time-to-solution scaling exponent vs branch-and-bound /
  Memetic tabu baselines.
- Strongest known baseline: best published classical LABS solvers; escalation if
  a better exponent is published post-2024.
- Artifacts: simulation data/code substantially public. Public enough: yes.
- Budget: classical replication of small-n scaling fits: workstation-scale.
- Exclusion risk: low-medium (extrapolation dispute is the point).

### OPT-3 (reserve). D-Wave vs SA/parallel-tempering optimization speedup claims
  (various) — messy baseline landscape, good stress test but high effort.
### OPT-4 (reserve). QAOA MaxCut hardware demonstrations claiming
  depth-limited advantage — typically Not Auditable (missing baselines); useful
  as a deliberate Not Auditable exemplar if a slot needs one.

**Recommendation:** OPT-1 and OPT-2.

---

## Slot: error mitigation (2 slots, 4 candidates)

### EM-1. Sparse Pauli–Lindblad PEC claim
- Claim (paraphrase): probabilistic error cancellation with a sparse
  Pauli–Lindblad noise model yields unbiased expectation values on
  superconducting processors at characterized sampling overhead.
- Source: van den Berg, Minev, Kandala & Temme, *Probabilistic error
  cancellation with sparse Pauli–Lindblad models on noisy quantum processors*,
  Nature Physics 19, 1116–1121 (2023). doi:10.1038/s41567-023-02042-2.
- Estimand: bias of mitigated observables vs exact values on verifiable
  circuits; empirical vs predicted sampling overhead (gamma factor).
- Strongest known baseline: exact simulation of the verification circuits;
  escalation to stronger noise models (non-Markovian/context-dependent) if the
  Lindblad model is contradicted by the device data.
- Artifacts: model parameters and circuits described; raw data partially public.
- Budget: classical verification cheap; faithful rerun needs QPU (defer rerun).
- Exclusion risk: low-medium.

### EM-2. ZNE "computational reach" claim
- Claim (paraphrase): zero-noise extrapolation extends the computational reach
  of a noisy processor, giving accurate observables for circuits whose
  unmitigated outputs are useless.
- Source: Kandala et al., *Error mitigation extends the computational reach of
  a noisy quantum processor*, Nature 567, 491–495 (2019). doi:10.1038/s41586-019-1040-7.
- Estimand: mitigated vs exact observable error for small verifiable systems
  (H2/LiH VQE observables).
- Strongest known baseline: exact diagonalization (trivially available) — the
  audit focus is uncertainty honesty and extrapolation-model dependence.
- Escalation trigger: extrapolation-model class shown to bias results on
  matched synthetic noise.
- Artifacts: published curves; raw shot data mostly not public → likely
  Conditionally Stable or Not Auditable on artifact grounds. That is an
  acceptable, informative outcome.
- Budget: classical only. Exclusion risk: medium by design.

### EM-3 (reserve). Kim et al. 2023 ZNE component audited separately from QS-1
  (avoid double-counting one paper across two slots unless Vi approves).
### EM-4 (reserve). Fundamental-limits contrast claim (Takagi et al. 2022,
  exponential sampling cost) as a theory-anchored consistency audit.

**Recommendation:** EM-1 and EM-2.

---

## Slot: cross-compiler comparison (1 slot, 2 candidates)

### CC-1. t|ket⟩ compilation-quality claim
- Claim (paraphrase): t|ket⟩ produces lower two-qubit-gate counts and depth than
  contemporary compilers (Qiskit, others) across benchmark circuit suites.
- Source: Sivarajah et al., *t|ket⟩: a retargetable compiler for NISQ devices*,
  Quantum Sci. Technol. 6, 014003 (2020). doi:10.1088/2058-9565/ab8e92.
- Estimand: two-qubit-gate count / depth distributions over a declared benchmark
  suite at pinned compiler versions.
- Strongest known baseline: current Qiskit transpiler at its best optimization
  level — the audit's built-in drift test (2020 claim vs 2026 compilers) makes
  the sustained/reversed question sharp.
- Artifacts: benchmark circuits public; compiler versions pip-installable. Fully
  reproducible classically. Budget: hours. Exclusion risk: low.

### CC-2 (reserve). MQT Bench / Quetschlich et al. compiler comparisons —
  broader but claim statements are more diffuse; harder to pin one estimand.

**Recommendation:** CC-1.

---

## Summary table

| Slot | Recommended | Sustained-vs-reversed interest | QPU needed |
|---|---|---|---|
| simulation-1 | QS-1 Kim 2023 utility | documented classical reversal exists | no |
| simulation-2 | QS-2 King 2025 annealing | active dispute | no |
| optimization-1 | OPT-1 Ebadi 2022 MIS | classical narrowing published | no |
| optimization-2 | OPT-2 Shaydulin 2024 LABS | extrapolation dispute | no |
| mitigation-1 | EM-1 PEC Nat. Phys. 2023 | model-adequacy question | rerun only |
| mitigation-2 | EM-2 ZNE Nature 2019 | artifact-poor by design | no |
| cross-compiler | CC-1 t|ket⟩ 2020 | version-drift reversal test | no |

Next step: Vi reviews; approved entries replace placeholders in the corpus
manifest with authored contracts; then — and only then — `seal-protocol`.
