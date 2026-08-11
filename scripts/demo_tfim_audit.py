"""End-to-end Quantum Opportunity Audit demonstration (Appendix C of the manuscript).

Instance: 4-qubit open-chain transverse-field Ising model (TFIM),
    H = -J sum_i Z_i Z_{i+1} - h sum_i X_i,   J = h = 1.

The audit is run to completion: contract -> mechanism -> interface -> physical
calculation -> baseline -> decision. Everything is classically simulable by
construction; the point is to validate the audit *procedure* and the shot-
allocation mathematics, not to claim advantage. The expected (and obtained)
decision for this instance is `classical-only`.

Also includes the rejection case: DNA phase-encoding / QFT sampling vs. FFT.

Run:  python scripts/demo_tfim_audit.py
Requires: numpy.
"""

import numpy as np

rng = np.random.default_rng(20260811)

# ----------------------------------------------------------------------
# 1. Problem contract P (frozen)
n = 4
J = h = 1.0
eps_target = 0.05      # additive error on ground-state energy
delta_target = 0.05    # joint failure probability
print("=" * 72)
print("STEP 1  Problem contract: <E0> of 4-qubit TFIM, eps=0.05, delta=0.05")

# ----------------------------------------------------------------------
# 2. Exact diagonalization (ground truth + the classical baseline)
I2 = np.eye(2)
X = np.array([[0, 1], [1, 0]], dtype=float)
Z = np.array([[1, 0], [0, -1]], dtype=float)


def kron_at(op, i):
    mats = [I2] * n
    mats[i] = op
    out = mats[0]
    for m in mats[1:]:
        out = np.kron(out, m)
    return out


H = np.zeros((2**n, 2**n))
zz_terms = [(i, i + 1) for i in range(n - 1)]
for i, j in zz_terms:
    H += -J * kron_at(Z, i) @ kron_at(Z, j)
for i in range(n):
    H += -h * kron_at(X, i)

evals, evecs = np.linalg.eigh(H)
E0, psi0 = evals[0], evecs[:, 0]
print(f"STEP 2  Exact E0 = {E0:.6f}  (classical baseline: 16x16 eigh, ~microseconds)")

# ----------------------------------------------------------------------
# 3. Commuting-group construction: G = 2 (all-Z group, all-X group)
#    group Z: -J sum ZZ  -> weight a_Z = J*(n-1) = 3
#    group X: -h sum X   -> weight a_X = h*n     = 4
a = {"Z": J * (n - 1), "X": h * n}
sum_a = sum(a.values())
G = 2
print(f"STEP 3  Commuting groups G={G}, weights a_Z={a['Z']}, a_X={a['X']}, sum={sum_a}")

# per-shot group values: measure all qubits in Z (resp. X) basis
probs_z = np.abs(psi0) ** 2                       # Z-basis distribution
Hn = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
Un = Hn
for _ in range(n - 1):
    Un = np.kron(Un, Hn)
probs_x = np.abs(Un @ psi0) ** 2                  # X-basis distribution

bits = ((np.arange(2**n)[:, None] >> np.arange(n)[::-1]) & 1)  # basis-state bits
signs = 1 - 2 * bits                                            # Z eigenvalues per qubit


def group_value_z(state_idx):
    s = signs[state_idx]
    return -J * sum(s[:, i] * s[:, j] for i, j in zz_terms)


def group_value_x(state_idx):
    s = signs[state_idx]
    return -h * s.sum(axis=1)


# exact per-group means and variances (what a pilot run estimates)
idx = np.arange(2**n)
vz, vx = group_value_z(idx), group_value_x(idx)
mu = {"Z": probs_z @ vz, "X": probs_x @ vx}
sig = {"Z": np.sqrt(probs_z @ vz**2 - mu["Z"] ** 2),
       "X": np.sqrt(probs_x @ vx**2 - mu["X"] ** 2)}
print(f"        mu_Z={mu['Z']:.4f} sigma_Z={sig['Z']:.4f} (bound {a['Z']});"
      f" mu_X={mu['X']:.4f} sigma_X={sig['X']:.4f} (bound {a['X']})")
assert abs(mu["Z"] + mu["X"] - E0) < 1e-9, "estimator normalization check"
print("        estimator check: mu_Z + mu_X == E0  (exact)")

# ----------------------------------------------------------------------
# 4. Shot allocation, both regimes (manuscript eqs worstcase-shots / neyman-shots)
eps, delta = eps_target, delta_target
N_worst = {}
for g in a:
    eps_g = eps * a[g] / sum_a
    delta_g = delta / G
    N_worst[g] = int(np.ceil(2 * a[g] ** 2 * np.log(2 / delta_g) / eps_g**2))
z = 1.959963984540054
sum_sigma = sum(sig.values())
N_ney_tot = z**2 * sum_sigma**2 / eps**2
N_ney = {g: int(np.ceil(N_ney_tot * sig[g] / sum_sigma)) for g in a}
print(f"STEP 4  Worst-case shots: {N_worst}  total={sum(N_worst.values()):,}")
print(f"        Neyman shots (true sigmas): {N_ney}  total={sum(N_ney.values()):,}")

# ----------------------------------------------------------------------
# 5. Simulated sampling experiment + empirical coverage of both allocations
def run_trial(N):
    zs = rng.choice(2**n, size=N["Z"], p=probs_z)
    xs = rng.choice(2**n, size=N["X"], p=probs_x)
    return group_value_z(zs).mean() + group_value_x(xs).mean()


trials = 400
for name, N in [("worst-case", N_worst), ("Neyman", N_ney)]:
    est = np.array([run_trial(N) for _ in range(trials)])
    cover = np.mean(np.abs(est - E0) <= eps)
    print(f"STEP 5  {name}: mean err={np.abs(est - E0).mean():.4f}, "
          f"coverage(|err|<=eps)={cover:.3f}  (target >= {1 - delta})")

# ----------------------------------------------------------------------
# 6. Physical audit (toy screen) and decision
# hypothetical hardware ansatz for this state: ~3 layers, ~9 CZ, 24 1q gates, 4 meas
N1, N2, Nm = 24, 9, 4
p1, p2, pm, tratio = 2e-4, 5e-3, 1.5e-2, 0.01
P0 = (1 - p1) ** N1 * (1 - p2) ** N2 * (1 - pm) ** Nm * np.exp(-tratio)
print(f"STEP 6  Toy screen P0 = {P0:.3f} (fine), but baseline solves instance exactly")
print("        in microseconds at every accuracy.")
print("DECISION: classical-only (gate 5 fails: no regime where the QPU wins).")
print("The audit procedure completed all gates and produced a defensible rejection.")

# ----------------------------------------------------------------------
# 7. Rejection case: DNA phase encoding vs. FFT
print("=" * 72)
N = 4096
motif = rng.integers(0, 4, size=16)
seq = np.tile(motif, N // 16)                       # strongly periodic sequence
phases = np.exp(1j * (np.pi / 2) * seq)
spectrum = np.abs(np.fft.fft(phases)) ** 2 / N**2   # QFT sampling distribution
p_k = spectrum / spectrum.sum()
shots = 10_000
samples = rng.choice(N, size=shots, p=p_k)
top_true = int(np.argmax(p_k))
top_est = int(np.bincount(samples, minlength=N).argmax())
print(f"DNA REJECTION CASE  N={N} bases, period-16 motif (best case for the quantum route)")
print(f"  state preparation from classical data: Theta(N) = {N} amplitude loads/shot")
print(f"  classical FFT: N log2 N = {int(N * np.log2(N)):,} ops, returns FULL spectrum once")
print(f"  QFT sampling: each shot returns ONE k; with {shots:,} shots the top peak was"
      f" {'found' if top_est == top_true else 'NOT found'} (true k={top_true}, sampled k={top_est})")
print(f"  loading cost alone: {shots:,} shots x Theta(N) = {shots * N:,} operations")
print("  >> even when sampling succeeds, the quantum route pays more in loading than")
print("     the classical FFT pays for the complete answer.")
print("  DECISION: classical-only under the stated access model (as the manuscript argues).")
