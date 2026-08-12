"""End-to-end TFIM audit demonstration with an Ariadion-backed execution path.

Structure
---------
SECTION A  Classical oracle (pure NumPy; imports NO Ariadion code).
           Exact Hamiltonian diagonalization, an independent state-vector
           simulation of the fixed preparation circuit, exact measurement-
           setting distributions, and the audit arithmetic (shot bounds,
           coverage experiment, screening, decision).
SECTION B  Ariadion execution path (author-developed, version-pinned SDK,
           commit e4c56fb16b35382c95ba54d4b2b9f1fd2c684683, 0.1.0rc2).
           Explicit preparation + measurement programs, exact state-vector
           runs, seeded sampled runs, density-matrix runs under a declared
           toy noise model, Theonoe inspection, and noise-impact reports.
SECTION C  Paper-artifact energy reduction. Ariadion has no public
           expectation-value helper; THIS SCRIPT reduces Ariadion's joint
           returned classical distributions to grouped energy estimates.
           That reduction is performed by the paper artifact, not by
           Ariadion.
SECTION D  Numerical tests (assertions) + DNA-motif rejection example.
SECTION E  Artifact + manifest + hash emission (artifacts/ directory).

Honesty notes (repeated in the manifest and manuscript):
* Ariadion's density path binds noise channels to ONE-QUBIT gates only.
  It has no modeled two-qubit CX noise, no leakage, no correlated errors,
  and no device-calibration ingestion. Its noise results are a toy model,
  not a hardware model.
* Ariadion's protection-requirement reporting is NOT used here; TFIM energy
  estimation has no natural success/failure acceptance event, and we do not
  coerce one merely to obtain a reliability verdict.
* The independent NumPy oracle prevents the author-developed SDK from
  serving as its own sole validation.

Deterministic. Master seed 20260811.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np

MASTER_SEED = 20260811
ARIADION_COMMIT = "e4c56fb16b35382c95ba54d4b2b9f1fd2c684683"
ARIADION_VERSION = "0.1.0rc2"

# Fixed ansatz angles (chosen once, offline, by scripts/_choose_angles.py;
# hard-coded literals because Ariadion's @quantum frontend requires literal
# rotation angles).
THETA1 = 1.1148874287564283
THETA2 = 0.20641951023931937

N_QUBITS = 4
J = 1.0
HFIELD = 1.0
EPS = 0.05
DELTA = 0.05

ART = Path(__file__).resolve().parent.parent / "artifacts"

LINE = "-" * 72


def section(title: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")


# =========================================================================
# SECTION A - CLASSICAL ORACLE (pure NumPy; no Ariadion imports anywhere
# in this section; this is the independently implemented reference).
# Bit convention: outcome index m encodes qubit i as bit i (LSB-first),
# matching Ariadion's TARGETS_LSB_FIRST return convention so distributions
# are directly comparable at the boundary.
# =========================================================================

I2 = np.eye(2)
PX = np.array([[0.0, 1.0], [1.0, 0.0]])
PZ = np.array([[1.0, 0.0], [0.0, -1.0]])
H1 = np.array([[1.0, 1.0], [1.0, -1.0]]) / math.sqrt(2.0)


def kron_at(op: np.ndarray, i: int) -> np.ndarray:
    """Operator `op` on qubit i, identity elsewhere; qubit 0 is the LSB."""
    m = np.array([[1.0]])
    for k in range(N_QUBITS - 1, -1, -1):  # leftmost kron factor = MSB
        m = np.kron(m, op if k == i else I2)
    return m


def oracle_hamiltonian() -> np.ndarray:
    Hm = np.zeros((2**N_QUBITS, 2**N_QUBITS))
    for i in range(N_QUBITS - 1):
        Hm -= J * kron_at(PZ, i) @ kron_at(PZ, i + 1)
    for i in range(N_QUBITS):
        Hm -= HFIELD * kron_at(PX, i)
    return Hm


def oracle_ry(theta: float) -> np.ndarray:
    c, s = math.cos(theta / 2.0), math.sin(theta / 2.0)
    return np.array([[c, -s], [s, c]])


def oracle_cx(control: int, target: int) -> np.ndarray:
    dim = 2**N_QUBITS
    m = np.zeros((dim, dim))
    for b in range(dim):
        if (b >> control) & 1:
            m[b ^ (1 << target), b] = 1.0
        else:
            m[b, b] = 1.0
    return m


def oracle_prepared_state() -> np.ndarray:
    """Independent simulation of the fixed preparation circuit:
    RY(THETA1) on all qubits; CX(0,1) CX(1,2) CX(2,3); RY(THETA2) on all."""
    psi = np.zeros(2**N_QUBITS)
    psi[0] = 1.0
    for i in range(N_QUBITS):
        psi = kron_at(oracle_ry(THETA1), i) @ psi
    for i in range(N_QUBITS - 1):
        psi = oracle_cx(i, i + 1) @ psi
    for i in range(N_QUBITS):
        psi = kron_at(oracle_ry(THETA2), i) @ psi
    return psi


def group_value_z(m: int) -> float:
    s = [1.0 - 2.0 * ((m >> i) & 1) for i in range(N_QUBITS)]
    return -J * sum(s[i] * s[i + 1] for i in range(N_QUBITS - 1))


def group_value_x(m: int) -> float:
    s = [1.0 - 2.0 * ((m >> i) & 1) for i in range(N_QUBITS)]
    return -HFIELD * sum(s)


def dist_stats(probs: np.ndarray, value_fn) -> tuple[float, float]:
    vals = np.array([value_fn(m) for m in range(len(probs))])
    mu = float(probs @ vals)
    var = float(probs @ (vals - mu) ** 2)
    return mu, math.sqrt(var)


section("SECTION A: classical oracle (independent NumPy implementation)")

Hm = oracle_hamiltonian()
evals = np.linalg.eigvalsh(Hm)
E0 = float(evals[0])
psi = oracle_prepared_state()
E_psi_oracle = float(psi @ (Hm @ psi))
print(f"exact ground-state energy      E0        = {E0:.9f}")
print(f"oracle <psi|H|psi> (ansatz)    E_psi     = {E_psi_oracle:.9f}")
print(f"ansatz gap above ground state            = {E_psi_oracle - E0:.6f}")

# Exact measurement-setting distributions from the oracle state.
probs_z_oracle = np.abs(psi) ** 2
psi_x = psi.copy()
for i in range(N_QUBITS):
    psi_x = kron_at(H1, i) @ psi_x
probs_x_oracle = np.abs(psi_x) ** 2

mu_z, sigma_z = dist_stats(probs_z_oracle, group_value_z)
mu_x, sigma_x = dist_stats(probs_x_oracle, group_value_x)
print(f"grouped means: mu_Z = {mu_z:.9f}, mu_X = {mu_x:.9f}")
print(f"grouped sigmas: sigma_Z = {sigma_z:.6f}, sigma_X = {sigma_x:.6f}")
assert abs((mu_z + mu_x) - E_psi_oracle) < 1e-9, "estimator identity failed"
print("estimator identity mu_Z + mu_X == <psi|H|psi>: OK")

# --- Shot bounds (contract eps=0.05, delta=0.05, G=2 groups) -------------
A_Z = 3.0 * J        # |value| bound, Z group (3 bonds)
A_X = 4.0 * HFIELD   # |value| bound, X group (4 sites)
SUM_A = A_Z + A_X
G = 2

shots_worst: dict[str, int] = {}
for name, a in (("Z", A_Z), ("X", A_X)):
    eps_g = EPS * a / SUM_A
    delta_g = DELTA / G
    shots_worst[name] = math.ceil(2.0 * a * a * math.log(2.0 / delta_g) / eps_g**2)
print(f"worst-case (Hoeffding) shots: {shots_worst}, total {sum(shots_worst.values())}")

Z975 = 1.959963984540054
sigma_sum = sigma_z + sigma_x
shots_neyman: dict[str, int] = {}
for name, sg in (("Z", sigma_z), ("X", sigma_x)):
    shots_neyman[name] = max(1, math.ceil((Z975 / EPS) ** 2 * sigma_sum * sg))
print(f"Neyman (z=1.96) shots:        {shots_neyman}, total {sum(shots_neyman.values())}")

# =========================================================================
# SECTION B - ARIADION EXECUTION PATH
# =========================================================================

section("SECTION B: Ariadion execution path (version-pinned artifact)")

import ariadion  # noqa: E402
from ariadion import (  # noqa: E402
    Bit,
    Qubit,
    quantum,
    run,
    h,
    cx,
    x,
    ry,
    rad,
    SampledExecutionRequest,
    DensityMatrixExecutionRequest,
    TraceCaptureOptions,
    inspect_execution_trace,
)
from ariadion_noise import (  # noqa: E402
    BinaryReadoutChannel,
    DepolarizingChannel,
    ExecutableNoiseModel,
    GateChannelBinding,
    OneQubitGate,
)
from ariadion_runtime import build_density_noise_impact_report  # noqa: E402

print(f"ariadion version reported by SDK: {ariadion.__version__}")
assert ariadion.__version__ == ARIADION_VERSION


@quantum
def tfim_z_setting() -> tuple[Bit, Bit, Bit, Bit]:
    """Preparation circuit + joint Z-basis measurement (ZZ group)."""
    q0 = Qubit()
    q1 = Qubit()
    q2 = Qubit()
    q3 = Qubit()
    ry(q0, rad(1.1148874287564283))
    ry(q1, rad(1.1148874287564283))
    ry(q2, rad(1.1148874287564283))
    ry(q3, rad(1.1148874287564283))
    cx(q0, q1)
    cx(q1, q2)
    cx(q2, q3)
    ry(q0, rad(0.20641951023931937))
    ry(q1, rad(0.20641951023931937))
    ry(q2, rad(0.20641951023931937))
    ry(q3, rad(0.20641951023931937))
    return q0, q1, q2, q3


@quantum
def tfim_x_setting() -> tuple[Bit, Bit, Bit, Bit]:
    """Same preparation, terminal Hadamards -> joint X-basis (X group)."""
    q0 = Qubit()
    q1 = Qubit()
    q2 = Qubit()
    q3 = Qubit()
    ry(q0, rad(1.1148874287564283))
    ry(q1, rad(1.1148874287564283))
    ry(q2, rad(1.1148874287564283))
    ry(q3, rad(1.1148874287564283))
    cx(q0, q1)
    cx(q1, q2)
    cx(q2, q3)
    ry(q0, rad(0.20641951023931937))
    ry(q1, rad(0.20641951023931937))
    ry(q2, rad(0.20641951023931937))
    ry(q3, rad(0.20641951023931937))
    h(q0)
    h(q1)
    h(q2)
    h(q3)
    return q0, q1, q2, q3


@quantum
def bit_order_probe() -> tuple[Bit, Bit]:
    """X on the FIRST returned qubit only; used to pin down bit ordering."""
    a = Qubit()
    b = Qubit()
    x(a)
    return a, b


SETTINGS = {"Z": tfim_z_setting, "X": tfim_x_setting}

# --- B.1 exact ideal state-vector runs (with trace + Theonoe) ------------
exact_runs = {}
for name, fn in SETTINGS.items():
    res = run(fn, trace=TraceCaptureOptions(enabled=True))
    exact_runs[name] = res
    dist = res.classical_output_distribution
    order = dist.bit_order.name if hasattr(dist.bit_order, "name") else dist.bit_order
    print(f"[{name} setting] exact run: {len(dist.probabilities)} outcomes, "
          f"bit_order={order}")

probs_z_ariadion = np.array(exact_runs["Z"].classical_output_distribution.probabilities)
probs_x_ariadion = np.array(exact_runs["X"].classical_output_distribution.probabilities)

trace_inspections = {
    name: inspect_execution_trace(res.trace) for name, res in exact_runs.items()
}
print("Theonoe pre-observation inspection and execution-trace inspection captured "
      "for both settings (state-vector path only).")

# --- B.2 seeded sampled runs at every reported shot count ----------------
REPORTED_SHOT_COUNTS = {
    "Z": sorted({shots_worst["Z"], shots_neyman["Z"], 2000}),
    "X": sorted({shots_worst["X"], shots_neyman["X"], 2000}),
}
SAMPLE_SEEDS = {"Z": 101, "X": 202}

sampled_runs: dict[tuple[str, int], object] = {}
for name, fn in SETTINGS.items():
    for shots in REPORTED_SHOT_COUNTS[name]:
        seed = SAMPLE_SEEDS[name] * 1_000_000 + shots % 1_000_000
        res = run(fn, execution=SampledExecutionRequest(shots=shots, seed=seed))
        sampled_runs[(name, shots)] = res
        print(f"[{name} setting] sampled run: shots={shots}, seed={seed}")

# reproducibility pair: identical request twice
repro_a = run(tfim_z_setting, execution=SampledExecutionRequest(shots=2000, seed=777))
repro_b = run(tfim_z_setting, execution=SampledExecutionRequest(shots=2000, seed=777))

# --- B.3 density-matrix runs under a DECLARED TOY noise model ------------
# Toy model: depolarizing channel bound to every one-qubit gate used
# (RY, H) plus a symmetric readout channel. Ariadion's density path binds
# channels to one-qubit gates ONLY: the CX gates in this circuit execute
# noiselessly. This is a modeling omission, not a hardware claim.
NOISE_LEVELS = {"low": 0.005, "high": 0.02}
READOUT_P = 0.01


def toy_noise_model(p: float) -> ExecutableNoiseModel:
    return ExecutableNoiseModel(
        gate_channels=(
            GateChannelBinding(OneQubitGate.RY, DepolarizingChannel(p)),
            GateChannelBinding(OneQubitGate.H, DepolarizingChannel(p)),
        ),
        readout_channel=BinaryReadoutChannel(READOUT_P, READOUT_P),
    )


density_runs: dict[tuple[str, str], object] = {}
noise_reports: dict[tuple[str, str], object] = {}
for level, p in NOISE_LEVELS.items():
    for name, fn in SETTINGS.items():
        res = run(fn, execution=DensityMatrixExecutionRequest(noise_model=toy_noise_model(p)))
        density_runs[(name, level)] = res
        noise_reports[(name, level)] = build_density_noise_impact_report(res)
        print(f"[{name} setting] density run: depolarizing p={p}, readout p={READOUT_P}")

# bit-order probe (exact)
probe = run(bit_order_probe)
probe_probs = np.array(probe.classical_output_distribution.probabilities)

# =========================================================================
# SECTION C - PAPER-ARTIFACT ENERGY REDUCTION
# Ariadion exposes joint classical distributions / shot counts but NO
# public expectation-value helper. The reduction below is performed by
# this paper artifact. Because each setting's JOINT distribution is used,
# covariance among observables measured in the same setting is retained
# exactly (no per-observable marginalization).
# =========================================================================

section("SECTION C: paper-artifact energy reduction from joint distributions")

VALUE_FNS = {"Z": group_value_z, "X": group_value_x}


def energy_from_distributions(pz: np.ndarray, px: np.ndarray) -> float:
    ez = float(sum(pz[m] * group_value_z(m) for m in range(len(pz))))
    ex = float(sum(px[m] * group_value_x(m) for m in range(len(px))))
    return ez + ex


def energy_from_counts(counts: tuple[int, ...], value_fn) -> float:
    total = sum(counts)
    return sum(c * value_fn(m) for m, c in enumerate(counts)) / total


E_ariadion_ideal = energy_from_distributions(probs_z_ariadion, probs_x_ariadion)
print(f"Ariadion ideal energy (artifact reduction) = {E_ariadion_ideal:.9f}")
print(f"oracle <psi|H|psi>                          = {E_psi_oracle:.9f}")

sampled_energies: dict[tuple[str, int], float] = {}
for (name, shots), res in sampled_runs.items():
    sampled_energies[(name, shots)] = energy_from_counts(
        tuple(res.classical_output.counts), VALUE_FNS[name]
    )

E_hat_worst = (
    sampled_energies[("Z", shots_worst["Z"])] + sampled_energies[("X", shots_worst["X"])]
)
E_hat_neyman = (
    sampled_energies[("Z", shots_neyman["Z"])] + sampled_energies[("X", shots_neyman["X"])]
)
print(f"sampled energy @ worst-case shots  = {E_hat_worst:.6f} "
      f"(err {abs(E_hat_worst - E_psi_oracle):.6f}, budget {EPS})")
print(f"sampled energy @ Neyman shots      = {E_hat_neyman:.6f} "
      f"(err {abs(E_hat_neyman - E_psi_oracle):.6f})")

density_energies: dict[str, float] = {}
for level in NOISE_LEVELS:
    pz = np.array(density_runs[("Z", level)].reported_classical_output_distribution.probabilities)
    px = np.array(density_runs[("X", level)].reported_classical_output_distribution.probabilities)
    density_energies[level] = energy_from_distributions(pz, px)
    print(f"density-path energy (toy noise '{level}', p={NOISE_LEVELS[level]}) "
          f"= {density_energies[level]:.6f}")

# --- Coverage experiment (400 trials) ------------------------------------
# NOTE: run in the ORACLE'S sampler, drawing from Ariadion's exported ideal
# joint distributions. Repeating 400 x ~340k-shot Ariadion trajectory runs
# is computationally out of scope for a pure-Python simulator; this
# substitution is a declared paper-artifact reduction, seeded and recorded.
section("Coverage experiment (400 trials; artifact sampler over Ariadion ideal dists)")

TRIALS = 400
rng = np.random.default_rng(MASTER_SEED)
cover = {"worst": 0, "neyman": 0}
for _ in range(TRIALS):
    for scheme, alloc in (("worst", shots_worst), ("neyman", shots_neyman)):
        est = 0.0
        for name, probs in (("Z", probs_z_ariadion), ("X", probs_x_ariadion)):
            counts = rng.multinomial(alloc[name], probs / probs.sum())
            est += energy_from_counts(tuple(int(c) for c in counts), VALUE_FNS[name])
        if abs(est - E_ariadion_ideal) <= EPS:
            cover[scheme] += 1
coverage_worst = cover["worst"] / TRIALS
coverage_neyman = cover["neyman"] / TRIALS
print(f"coverage within eps={EPS}: worst-case allocation {coverage_worst:.3f}, "
      f"Neyman allocation {coverage_neyman:.3f} (targets: >= {1-DELTA}, ~0.95)")

# --- Audit screen + decision (unchanged from contract) -------------------
section("Audit screen and decision")

N1, N2, NM = 24, 9, 4
P1G, P2G, PMG = 2e-4, 5e-3, 1.5e-2
P0 = (1 - P1G) ** N1 * (1 - P2G) ** N2 * (1 - PMG) ** NM
T_RATIO = 0.01
print(f"toy screen: P0 = {P0:.3f}; T_quantum/T_classical = {T_RATIO}")
DECISION = "classical-only"
print(f"DECISION: {DECISION}  (4-qubit TFIM: exact classical diagonalization "
      f"is trivially cheaper; the quantum path is a methods demonstration only)")

# --- DNA-motif rejection example (purely classical analysis) -------------
section("DNA-motif rejection example (classical analysis; no quantum execution)")

DNA_N = 4096
PERIOD = 16
rng_dna = np.random.default_rng(MASTER_SEED + 1)
signal = np.zeros(DNA_N)
signal[::PERIOD] = 1.0
signal += 0.25 * rng_dna.standard_normal(DNA_N)
amps = signal / np.linalg.norm(signal)
freq = np.abs(np.fft.fft(amps)) ** 2
freq /= freq.sum()
qft_shots = 10_000
qft_counts = rng_dna.multinomial(qft_shots, freq)
k_star = int(np.argmax(qft_counts[1:]) + 1)
loading_ops = DNA_N * qft_shots  # Omega(N) amplitude-encoding work per shot
fft_ops = int(DNA_N * math.log2(DNA_N))
print(f"N={DNA_N}, planted period {PERIOD}; QFT-sampling peak at k={k_star} "
      f"(expected multiple of {DNA_N // PERIOD})")
print(f"state loading ~ {loading_ops:.1e} ops (Omega(N) per shot x {qft_shots} shots) "
      f"vs classical FFT = {fft_ops} ops")
DNA_DECISION = "classical-only"
print(f"DNA DECISION: {DNA_DECISION} (data loading dominates; FFT wins outright)")
assert k_star % (DNA_N // PERIOD) == 0, "QFT peak not at planted frequency"

# =========================================================================
# SECTION D - NUMERICAL TESTS
# =========================================================================

section("SECTION D: numerical tests")

# Test 1: Ariadion ideal agrees with the independent classical reference.
assert np.allclose(probs_z_ariadion, probs_z_oracle, atol=1e-9), "Z dist mismatch"
assert np.allclose(probs_x_ariadion, probs_x_oracle, atol=1e-9), "X dist mismatch"
assert abs(E_ariadion_ideal - E_psi_oracle) < 1e-9, "ideal energy mismatch"
print("TEST 1 PASS: Ariadion ideal distributions and energy match the "
      "independent NumPy oracle (atol 1e-9).")

# Test 2: grouped expectations use the correct bit ordering.
assert abs(probe_probs[1] - 1.0) < 1e-12 and abs(probe_probs[0]) < 1e-12, (
    "bit-order probe failed: first returned bit is not the LSB")
print("TEST 2 PASS: X on the first returned qubit puts all mass on outcome "
      "index 1 -> first returned bit is the LSB, as assumed by the reduction.")

# Test 3: empirical shot estimates satisfy the stated confidence experiment.
assert abs(E_hat_worst - E_psi_oracle) <= EPS, "worst-case sampled estimate outside eps"
assert coverage_worst >= 1 - DELTA, "worst-case coverage below 1-delta"
assert coverage_neyman >= 0.90, "Neyman coverage implausibly low"
print(f"TEST 3 PASS: worst-case Ariadion sampled estimate within eps; coverage "
      f"{coverage_worst:.3f} >= {1-DELTA} (worst), {coverage_neyman:.3f} (Neyman).")

# Test 4: identical seeds reproduce identical outputs.
assert tuple(repro_a.classical_output.counts) == tuple(repro_b.classical_output.counts), (
    "seeded reproducibility failed")
assert repro_a.classical_output.seed == repro_b.classical_output.seed == 777
print("TEST 4 PASS: identical SampledExecutionRequest(shots=2000, seed=777) "
      "twice -> identical counts.")

# Test 5: the audit decision remains classical-only.
assert DECISION == "classical-only" and DNA_DECISION == "classical-only"
print("TEST 5 PASS: audit decision is 'classical-only'; executing the circuit "
      "through Ariadion does not change the audit verdict.")

# Test 6: changing the modeled noise produces the expected, documented change.
gap_low = abs(density_energies["low"] - E_ariadion_ideal)
gap_high = abs(density_energies["high"] - E_ariadion_ideal)
assert gap_high > gap_low > 0, "noise sensitivity check failed"
assert abs(density_energies["high"]) < abs(density_energies["low"]), (
    "expected depolarizing noise to shrink |E| toward 0")
print(f"TEST 6 PASS: raising depolarizing p from {NOISE_LEVELS['low']} to "
      f"{NOISE_LEVELS['high']} moves the density-path energy monotonically "
      f"toward 0 (gaps {gap_low:.4f} -> {gap_high:.4f}), as documented.")

# =========================================================================
# SECTION E - ARTIFACTS, MANIFEST, HASHES
# =========================================================================

section("SECTION E: artifact emission")

ART.mkdir(exist_ok=True)


def to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, complex):
        return {"re": obj.real, "im": obj.imag}
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if hasattr(obj, "to_dict"):
        try:
            return to_jsonable(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "name") and hasattr(obj, "value"):  # Enum
        return obj.name
    return repr(obj)


def write_artifact(name: str, payload) -> Path:
    path = ART / name
    path.write_text(json.dumps(to_jsonable(payload), indent=2, sort_keys=True),
                    encoding="utf-8", newline="\n")
    print(f"wrote {path.name}")
    return path


written: list[Path] = []

# (1) compiled CircuitIR + source-to-operation provenance + ASCII circuit
for name, res in exact_runs.items():
    written.append(write_artifact(f"circuit_{name.lower()}.json", {
        "setting": name,
        "ascii_circuit": res.circuit,
        "circuit_ir": res.compilation.ir,
        "readout": res.compilation.readout,
    }))

# (2) exact ideal state-vector results
for name, res in exact_runs.items():
    written.append(write_artifact(f"ideal_{name.lower()}.json", {
        "setting": name,
        "distribution": res.classical_output_distribution,
        "pre_observation_amplitudes": res.pre_observation_state.amplitudes,
    }))

# (3) seeded sampled results at every reported shot count
for (name, shots), res in sampled_runs.items():
    co = res.classical_output
    written.append(write_artifact(f"sampled_{name.lower()}_{shots}.json", {
        "setting": name,
        "shots": shots,
        "seed": co.seed,
        "counts": list(co.counts),
        "energy_group_estimate_artifact_reduction": sampled_energies[(name, shots)],
    }))

# (4) exact density-matrix results under the declared toy noise model
for (name, level), res in density_runs.items():
    written.append(write_artifact(f"density_{name.lower()}_{level}.json", {
        "setting": name,
        "noise_level": level,
        "depolarizing_p": NOISE_LEVELS[level],
        "readout_p": READOUT_P,
        "physical_distribution": res.physical_classical_output_distribution,
        "reported_distribution": res.reported_classical_output_distribution,
        "provenance": res.provenance,
        "gate_noise_events": res.simulation.gate_noise_events,
    }))

# (5) Ariadion noise-impact reports
for (name, level), report in noise_reports.items():
    written.append(write_artifact(f"noise_impact_{name.lower()}_{level}.json", report))

# (6) Theonoe state / execution-trace inspection (state-vector path only)
for name, res in exact_runs.items():
    written.append(write_artifact(f"theonoe_{name.lower()}.json", {
        "setting": name,
        "pre_observation_inspection": res.pre_observation_inspection,
        "rendered_report": res.report,
        "trace_inspection": trace_inspections[name],
    }))

# (7) independent NumPy oracle results
written.append(write_artifact("oracle.json", {
    "E0_exact_diagonalization": E0,
    "E_psi_oracle": E_psi_oracle,
    "probs_z_oracle": probs_z_oracle,
    "probs_x_oracle": probs_x_oracle,
    "mu_z": mu_z, "mu_x": mu_x, "sigma_z": sigma_z, "sigma_x": sigma_x,
    "shots_worst": shots_worst, "shots_neyman": shots_neyman,
    "coverage_worst": coverage_worst, "coverage_neyman": coverage_neyman,
    "coverage_trials": TRIALS, "coverage_rng_seed": MASTER_SEED,
    "screen_P0": P0, "decision": DECISION,
    "dna_decision": DNA_DECISION, "dna_qft_peak": k_star,
}))

# (8) machine-readable experiment manifest
pip_freeze = subprocess.run(
    [sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, check=True
).stdout.strip().splitlines()

manifest = {
    "experiment": "TFIM grouped-energy audit demonstration (Appendix C)",
    "ariadion": {
        "role": ("author-developed, version-pinned research artifact; NOT a "
                 "hardware model and NOT independently validated except via "
                 "the NumPy oracle in this artifact"),
        "commit": ARIADION_COMMIT,
        "version": ARIADION_VERSION,
        "commit_is_tip_of_main": True,
        "newer_release_check": ("verified before freezing: only tag is v0.1.0rc1 "
                                "(older than pinned commit); no GitHub releases "
                                "exist; pinned commit is the newest intentional state"),
        "backend": ("ariadion-simulator-numpy (pure-Python/NumPy state-vector "
                    "and density-matrix simulator)"),
        "execution_modes": ["exact state-vector (+trace)", "seeded sampled",
                            "density-matrix"],
        "known_omissions_of_density_path": [
            "no modeled two-qubit CX noise (channels bind to one-qubit gates only)",
            "no leakage modeling",
            "no correlated-error modeling",
            "no device-calibration ingestion",
        ],
        "protection_requirement_report": ("NOT used: TFIM energy estimation has no "
                                          "natural accept/reject event and none was "
                                          "fabricated to obtain a reliability verdict"),
        "expectation_values": ("Ariadion exposes no public expectation-value helper; "
                               "energy reduction from joint distributions is performed "
                               "by this paper artifact (energy_from_distributions / "
                               "energy_from_counts in scripts/demo_tfim_audit.py)"),
    },
    "environment": {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependency_lock_pip_freeze": pip_freeze,
    },
    "circuit": {
        "ansatz": "RY(theta1)^x4; CX(0,1) CX(1,2) CX(2,3); RY(theta2)^x4",
        "theta1_rad": THETA1,
        "theta2_rad": THETA2,
        "angle_provenance": "scripts/_choose_angles.py (offline grid + coordinate descent)",
        "settings": {
            "Z": "joint Z-basis measurement of all returned qubits (ZZ group)",
            "X": "terminal Hadamard on every qubit, then joint Z-basis (X group)",
        },
        "bit_order": "TARGETS_LSB_FIRST: outcome index bit i = i-th returned qubit",
    },
    "hamiltonian": {"model": "open-chain TFIM", "n": N_QUBITS, "J": J, "h": HFIELD},
    "contract": {"eps": EPS, "delta": DELTA, "groups": {"Z": {"a": A_Z}, "X": {"a": A_X}}},
    "seeds": {
        "master_numpy_rng": MASTER_SEED,
        "sampled_run_seed_rule": "SAMPLE_SEEDS[setting]*1_000_000 + shots % 1_000_000",
        "sample_seeds": SAMPLE_SEEDS,
        "reproducibility_pair_seed": 777,
    },
    "reported_shot_counts": REPORTED_SHOT_COUNTS,
    "results": {
        "E0": E0,
        "E_psi_oracle": E_psi_oracle,
        "E_ariadion_ideal": E_ariadion_ideal,
        "E_hat_worst": E_hat_worst,
        "E_hat_neyman": E_hat_neyman,
        "density_energies": density_energies,
        "coverage_worst": coverage_worst,
        "coverage_neyman": coverage_neyman,
        "decision": DECISION,
        "dna_decision": DNA_DECISION,
    },
    "coverage_experiment_note": ("400 trials drawn by the paper artifact's seeded "
                                 "NumPy sampler from Ariadion's exported ideal joint "
                                 "distributions; repeating 400 full Ariadion sampled "
                                 "runs is out of scope for a pure-Python simulator"),
    "artifact_files": [p.name for p in written],
}
manifest_path = write_artifact("manifest.json", manifest)

# (9) SHA-256 hashes for every artifact file
hash_lines = []
for p in sorted(written + [manifest_path], key=lambda q: q.name):
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    hash_lines.append(f"{digest}  {p.name}")
(ART / "SHA256SUMS.txt").write_text("\n".join(hash_lines) + "\n",
                                    encoding="utf-8", newline="\n")
print("wrote SHA256SUMS.txt")

section("SUMMARY")
print(f"E0 (exact diag)            = {E0:.6f}")
print(f"E_psi (oracle)             = {E_psi_oracle:.6f}")
print(f"E (Ariadion ideal)         = {E_ariadion_ideal:.6f}")
print(f"E_hat (worst-case shots)   = {E_hat_worst:.6f}")
print(f"E_hat (Neyman shots)       = {E_hat_neyman:.6f}")
print(f"E (toy noise low/high)     = {density_energies['low']:.6f} / {density_energies['high']:.6f}")
print(f"coverage (worst/Neyman)    = {coverage_worst:.3f} / {coverage_neyman:.3f}")
print(f"DECISION                   = {DECISION}")
print("All six numerical tests passed. Artifacts + manifest + hashes in artifacts/.")
