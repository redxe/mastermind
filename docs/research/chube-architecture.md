# CHUBE — Convolutional Hamiltonian Updates with Basis Encoding

**Status: PROPOSED / NOT EXECUTED.** This document specifies a prospective research
architecture. Nothing here is an established quantum-advantage result, none of the
experiments in [specs/chube-experiment.md](../../specs/chube-experiment.md) have been
run, and no CHUBE claim may be cited as evidence for any Mastermind conclusion.

Prospective paper title: *"CHUBE: Convolutional Hamiltonian Updates with Basis
Encoding for Quantum-Assisted Symbolic Reasoning."*

Rejected naming alternatives (recorded so the acronym stays unique): none yet; any
future alternative expansion of "CHUBE" must be logged here as rejected.

---

## 1. Formal architecture

### 1.1 Input and windows

The input is a fourteen-bit string

```
x = x_0 x_1 ... x_13,    x_i ∈ {0, 1}
```

from which seven overlapping eight-position windows are taken with stride 1:

```
w_t = (x_t, x_{t+1}, ..., x_{t+7}),    t = 0, ..., 6
```

Fourteen bits with window length eight and stride one yield exactly
`14 − 8 + 1 = 7` windows.

### 1.2 Basis encoding

Each window is encoded in the Hadamard/phase basis:

```
|φ_t⟩ = H^{⊗8} |w_t⟩ = ⊗_{j=0}^{7} Z_j^{x_{t+j}} |+⟩
```

so `0 ↦ |+⟩` and `1 ↦ |−⟩`. The encoded states are computational-basis states
rotated by a global Hadamard layer; distinct windows map to mutually orthogonal
states, and each `|φ_t⟩` is normalized by construction.

### 1.3 Shared Hamiltonian update and features

A single trainable Hermitian generator `H_θ` defines the shared update

```
U_θ = exp(−i H_θ τ)
```

and the observable features are Pauli expectations after evolution:

```
f_{t,k} = ⟨φ_t| U_θ† P_k U_θ |φ_t⟩
```

for a fixed, declared set of Pauli observables `{P_k}` (e.g. single-site `Z_j`,
`X_j`, and selected two-site correlators).

### 1.4 What "convolutional" means here

"Convolutional" refers to **weight sharing across translated, overlapping
windows**: the same parameterized update `U_θ` (or the same translated local
generator, §2.C) is reused at every window position, exactly as a classical
convolution reuses one kernel across positions. It does **not** mean that an
entire nonlinear CNN — activations, pooling, and all — has been converted into a
single matrix; that conversion is not generally possible (§3).

---

## 2. Three CHUBE variants

These are distinct computational models with different qubit costs and different
coherence properties. Conflating them is the main failure mode this document
exists to prevent.

### 2.A Stateless CHUBE filter (8 qubits)

- Prepare `|φ_t⟩` on the same eight physical qubits, apply `U_θ`, measure the
  feature observables, reset, and load window `t+1`.
- Aggregate the seven measured feature vectors `f_t ∈ R^K` with a classical head
  (linear probe, small MLP, or voting).
- Implementable with eight qubits and mid-circuit reset (or seven independent
  circuit executions).
- **The seven quantum states never coexist coherently.** All cross-window
  interaction happens classically in the aggregation head.
- This variant is a form of patch-wise quantum feature extraction and is closely
  related to data re-uploading classifiers [Pérez-Salinas et al. 2020] and
  quantum-convolutional patch processing [Cong, Choi & Lukin 2019; Henderson et
  al. 2020-style "quanvolution"]. Novelty, if any, lies in the specific
  combination of phase-basis window encoding with a shared Hamiltonian-generated
  filter — not in patch-wise processing itself.

### 2.B Recurrent CHUBE (8 qubits, split register)

- Partition the eight qubits into a persistent memory register `M` (m qubits)
  and an input/workspace register `D` (8 − m qubits).
- Stream tokens or feature chunks through `D` while `M` persists. One step is
  the quantum channel

```
ρ_{t+1}^M = Tr_D[ V_θ ( ρ_t^M ⊗ ρ(x_t)^D ) V_θ† ]
```

  where `ρ(x_t)^D` is the fresh encoding of chunk `x_t` and `V_θ` is the shared
  step unitary.
- **Memory/data tradeoff, stated explicitly:** if m qubits retain context, only
  8 − m qubits are available for input, so all eight qubits cannot
  simultaneously encode an eight-bit window. An eight-bit window must then be
  streamed in smaller chunks.
- **Coherence bookkeeping:** tracing out or resetting `D` implements a
  non-unitary channel on `M`. If `D` is entangled with `M` at the moment of
  reset, that entanglement is converted to decoherence on `M` — context is
  partially destroyed. Coherence on `M` survives a workspace reuse only when
  the step ends with `D` *disentangled* from `M`, which is achievable when the
  computation on `D` is reversibly uncomputed (compute–use–uncompute, §4)
  before the reset. Designs that skip uncomputation must model the step as a
  genuinely dissipative channel, not as unitary recurrence.

### 2.C Fully coherent Hamiltonian sweep (14 qubits)

For a 14-qubit register holding the whole input, define the translated shared
operator sweep

```
U_sweep = ∏_{t=0}^{6} exp[ −i τ  T^t h_θ T^{−t} ]
```

where `h_θ` is an 8-local generator acting on sites 0..7 and `T` is the
translation by one site, so the factor at step `t` acts on sites `t..t+7` —
the literal version of one operator scrolling across sites 0:8, 1:9, ..., 6:14.
The product is ordered (factors at different offsets need not commute); the
ordering convention is part of the model definition.

**Capacity statements (non-negotiable):**

- An arbitrary coherent 14-position basis input requires 14 data qubits: the
  2^14 inputs must map to mutually orthogonal states, and an 8-qubit Hilbert
  space (dimension 2^8 = 256) cannot contain 2^14 = 16384 mutually orthogonal
  states.
- An eight-qubit implementation of the sweep semantics is therefore possible
  only as (i) a classical-data re-uploading model (variant A), (ii) a
  bounded-memory streaming computation (variant B), or (iii) under an
  explicitly stated and justified compression or low-entanglement assumption
  (e.g. the relevant state family has bounded bond dimension and the
  compression map is part of the declared model).
- Continuous amplitudes do **not** rescue this: fourteen classical bits cannot
  be losslessly retrieved from eight qubits (Holevo bound — at most eight
  classical bits of retrievable information per eight qubits). Any CHUBE text
  implying otherwise is wrong and must be corrected.

---

## 3. Matrix-to-unitary guardrails

Claims about "turning the network into a matrix" must respect the following
distinctions:

1. A **linear** convolution is a structured (banded, Toeplitz-like) matrix.
   Representing it as a matrix is legitimate.
2. A complete CNN with nonlinear activations or pooling **cannot** in general
   be collapsed into one matrix; nonlinearities are not linear maps.
3. A Hermitian matrix `H` generates the unitary `exp(−iHt)`. Implementing this
   evolution is **not** the same as applying `H` itself to a state vector.
4. A nonunitary matrix `W` can be embedded via unitary dilation / block
   encoding:

   ```
   (⟨0^a| ⊗ I) U_W (|0^a⟩ ⊗ I) ≈ W / α
   ```

   This costs: a normalization factor `α ≥ ||W||`, ancilla qubits `a`,
   postselection or amplitude amplification on the ancilla outcome, and —
   critically — an *efficient structured-access* assumption on `W`
   [Gilyén et al. 2019]. None of these are free.
5. A generic dense 256×256 matrix is **not** "efficient" merely because it fits
   in an eight-qubit circuit: compiling an arbitrary 8-qubit unitary takes
   Θ(4^8) two-qubit gates in general.
6. CHUBE therefore prefers a **structured shallow ansatz**: `H_θ` is a sum of
   local one- and two-qubit Pauli terms (e.g. nearest-neighbor `ZZ` + on-site
   `X`/`Z` with trainable coefficients), Trotterized to shallow depth. This
   keeps gate counts polynomial in window size, keeps the model hardware-
   plausible, and makes the classical-simulability question honest (§7).

---

## 4. Uncomputation and readout

The standard compute–copy/phase-kickback–uncompute pattern:

```
|x⟩ |0⟩ |0⟩
  → |x⟩ |junk(x)⟩ |a(x)⟩      (compute predicate, garbage in workspace)
  → |x⟩ |0⟩ |a(x)⟩            (uncompute workspace; answer survives)
```

Rules:

- **Copying a classical basis-valued predicate** `a(x) ∈ {0,1}` into an output
  qubit (CNOT from a basis-encoded register) is allowed. **Copying an arbitrary
  unknown quantum state is not** (no-cloning).
- A **global phase is not measurable.** A phase-oracle answer must survive as a
  *relative* phase (interference against a reference branch), an explicit
  output qubit, or a measured observable — never as an overall phase on the
  whole state.
- If all eight qubits hold the window (variant A), **no separate coherent
  output register exists**; readout must go through measured observables
  `f_{t,k}` and classical aggregation.
- A strict eight-qubit recurrent design (variant B) should reserve at least one
  accumulator/memory qubit, or accept classical measurement aggregation as its
  cross-window mechanism.

---

## 5. Application framing: quantum-assisted symbolic reasoning

CHUBE is framed as one **scoring component inside a verified classical
pipeline**, not as an autonomous "quantum mathematician":

1. A classical parser or language model converts a problem into formal tokens,
   an AST, constraints, or a proof state.
2. CHUBE scores candidate rewrites, lemmas, tactics, or constraint assignments.
3. A classical symbolic engine executes the selected candidates.
4. A proof checker (Lean, Isabelle, or equivalent) verifies **every** accepted
   result. Nothing CHUBE emits is trusted unverified.

Initial controlled tasks (all with exactly computable ground truth):

- classifying valid versus corrupted algebraic rewrites
- selecting the next rewrite from a finite candidate set
- Boolean-expression equivalence
- modular, parity, or periodic relations that cross window boundaries (the case
  where overlapping windows should matter)
- ranking tactics for short, formally verified proof states

**Token encoding.** If tokens are not binary, the encoding must be declared. One
qubit cannot losslessly encode an arbitrary character alphabet (two orthogonal
states per qubit). Options: (i) fixed-width binary codes over multiple qubits
(orthogonal, faithful, costs qubits); (ii) angle/feature encoding of token
embeddings into single-qubit rotations — permitted, but the resulting states are
**nonorthogonal**, so distinct tokens are not perfectly distinguishable and the
model must be described as operating on a nonorthogonal feature map, not on a
faithful symbolic representation.

---

## 6. Related work (ingredients are established; the combination is unverified)

The present specification is a proposal ("we propose"); no novelty claim is made
until the exact combination has been checked against this literature:

- **Quantum convolutional neural networks:** Cong, Choi & Lukin, *Quantum
  Convolutional Neural Networks*, Nature Physics 15, 1273–1278 (2019),
  arXiv:1810.03787. Establishes translationally shared quantum filters and
  pooling; CHUBE's variant C sweep is close in spirit to a single QCNN layer
  without pooling.
- **Data re-uploading:** Pérez-Salinas, Cervera-Lierta, Gil-Fuster & Latorre,
  *Data re-uploading for a universal quantum classifier*, Quantum 4, 226
  (2020), arXiv:1907.02085. Variant A is a windowed data re-uploading model;
  this is the primary prior-art anchor for the 8-qubit stateless filter.
- **Block encoding / QSVT:** Gilyén, Su, Low & Wiebe, *Quantum singular value
  transformation and beyond*, STOC 2019, arXiv:1806.01838. Governs when a
  nonunitary matrix may legitimately be embedded (§3.4).
- **Quantum cellular automata:** Farrelly, *A review of Quantum Cellular
  Automata*, Quantum 4, 368 (2020), arXiv:1904.13318. Local unitary QCA are the
  rigorous framework for "the same local unitary applied translationally";
  variant C should be positioned relative to partitioned/Margolus QCA.
- **Quantum recurrent/sequential models:** Bausch, *Recurrent Quantum Neural
  Networks*, NeurIPS 2020, arXiv:2006.14619; and the tensor-network view of
  sequential quantum models (bounded-memory quantum sequence models correspond
  to matrix-product operators with bond dimension 2^m for m memory qubits —
  which is exactly why the MPS baseline in the experiment spec is mandatory).
- **Quantum language models / contextuality:** e.g. quantum-inspired and
  explicitly quantum sequence models for language tasks; to be surveyed
  properly before any novelty statement (deliberately left as an open
  verification item).
- **Trainability and simulability:** McClean, Boixo, Smelyanskiy, Babbush &
  Neven, *Barren plateaus in quantum neural network training landscapes*,
  Nature Communications 9, 4812 (2018), arXiv:1803.11173; Cerezo et al., *Does
  provable absence of barren plateaus imply classical simulability?*,
  arXiv:2312.09121. The uncomfortable possibility that any trainable CHUBE
  instance is classically simulable must be treated as a live hypothesis, not
  an inconvenience.

Citation hygiene: the arXiv identifiers above are believed correct but must be
re-verified against the primary sources before any manuscript submission; this
document is a research note, not a bibliography of record.

---

## 7. Honest failure modes

Recorded now so the eventual paper cannot quietly drop them:

1. Variant A may be exactly reproducible by a classical kernel method on the
   7×K feature matrix (the feature map is efficiently classically computable
   for shallow structured `H_θ`). If so, CHUBE-A is a classical model with
   quantum-flavored features and must be reported as such.
2. Variant B with m memory qubits is an MPO of bond dimension ≤ 2^m; a matched
   MPS/MPO baseline may match or beat it at equal effective memory.
3. Variant C at 14 qubits is trivially exactly simulable; it is a *simulation
   study* of an inductive bias, never a hardware-advantage claim.
4. Better-than-CNN accuracy is an architectural/inductive-bias result, not
   quantum advantage (see the experiment spec's decision rules).

---

## 8. Relation to Mastermind and the evidence-contract program

CHUBE is a **companion research direction**. It is not part of the Mastermind
manuscript's claims, it does not occupy any external pilot-claim slot in
[claim-corpus-manifest.yaml](claim-corpus-manifest.yaml), and it is not evidence
for anything. When (and only when) the prospective experiment in
[specs/chube-experiment.md](../../specs/chube-experiment.md) is about to be
executed, a CHUBE evidence contract must be authored and sealed under the locked
audit protocol *before* results exist, exactly like any other claim.

A deterministic, simulator-only, non-performance-claiming reference
implementation lives at [scripts/chube_reference.py](../../scripts/chube_reference.py)
with tests in [scripts/test_chube_reference.py](../../scripts/test_chube_reference.py).
