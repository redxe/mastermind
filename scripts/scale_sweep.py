"""Scale sweep for the TFIM audit pipeline (performance-at-scale evidence).

Sweeps chain length n for the transverse-field Ising model audit used in
Appendix C and measures, per n:

  * classical FREE-FERMION exact ground energy (Jordan-Wigner / Pfeuty 1970;
    O(n^3) via singular values of an n x n matrix) -- the strongest matched
    classical baseline for this integrable family,
  * generic dense exact-diagonalization wall time (dense eigh, dim 2^n) --
    kept only to show what a structure-blind solver costs; it is NOT the
    classical opponent for this instance family,
  * classical statevector ansatz evaluation wall time (the oracle path),
  * Qiskit Aer sampled execution wall time at a fixed 4,096 shots,
  * audit arithmetic: the worst-case Hoeffding allocation (eq. worstcase-shots
    of the manuscript, finite-sample, delta = 0.05, G = 2 groups) and the
    Neyman variance-aware allocation (eq. neyman-shots, asymptotic normal,
    z_{1-delta/2}) at fixed epsilon = 0.05 * n (constant per-site precision).

Purpose: document where the classical baselines actually stand for this
family, and how the measurement budget grows, rather than asserting it.
Because the 1D TFIM is exactly solvable, the free-fermion baseline never
walls; the dense solver's exhaustion near n = 14 is a property of the
generic method, not of the instance family.

Outputs: artifacts/scale/sweep.json, sweep_table.txt, manifest.json, SHA256SUMS.txt.
"""
from __future__ import annotations

import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "artifacts" / "scale"
OUTDIR.mkdir(parents=True, exist_ok=True)

J = 1.0
G = 1.0  # matches demo_tfim_audit.py (HFIELD = 1.0)
THETA1 = 1.1148874287564283
THETA2 = 0.20641951023931937
SHOTS_FIXED = 4096
N_EXACT_MAX = 14
N_STATEVEC_MAX = 24
SEED = 20260811


def apply_1q(state, U, q, n):
    """Apply 2x2 unitary U to qubit q (bit q of the amplitude index, LSB-first)."""
    psi = state.reshape(2 ** (n - q - 1), 2, 2 ** q)
    psi = np.einsum("ab,xbz->xaz", U, psi)
    return psi.reshape(-1)


def apply_ry(state, theta, q, n):
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return apply_1q(state, np.array([[c, -s], [s, c]], dtype=complex), q, n)


def apply_cx(state, ctrl, targ, n):
    idx = np.arange(2 ** n)
    src = np.where(((idx >> ctrl) & 1) == 1, idx ^ (1 << targ), idx)
    return state[src]


def ansatz_state(n):
    psi = np.zeros(2 ** n, dtype=complex)
    psi[0] = 1.0
    for q in range(n):
        psi = apply_ry(psi, THETA1, q, n)
    for q in range(n - 1):
        psi = apply_cx(psi, q, q + 1, n)
    for q in range(n):
        psi = apply_ry(psi, THETA2, q, n)
    return psi


def tfim_diag_terms(n):
    """Return (zz_diag, energies of Z-basis) for the ZZ part; X handled by rotation."""
    dim = 2 ** n
    idx = np.arange(dim)
    bits = ((idx[:, None] >> np.arange(n)) & 1)  # LSB-first
    z = 1 - 2 * bits  # Z eigenvalue per qubit
    zz = np.sum(z[:, :-1] * z[:, 1:], axis=1)
    return zz.astype(float)


def free_fermion_ground_energy(n):
    """Exact ground energy of the open-chain TFIM via Jordan-Wigner free
    fermions (Lieb-Schultz-Mattis 1961; Pfeuty 1970). O(n^3) time.

    H = -J sum Z_i Z_{i+1} - g sum X_i  ==  (basis rotation)  ==
    -J sum X_i X_{i+1} - g sum Z_i  -> quadratic fermion form with
    A_ii = 2g, A_{i,i+1} = A_{i+1,i} = -J, B_{i,i+1} = -B_{i+1,i} = -J,
    constant -g n.  E0 = -(1/2) * sum of singular values of (A - B).
    """
    A = np.zeros((n, n))
    B = np.zeros((n, n))
    for i in range(n):
        A[i, i] = 2 * G
    for i in range(n - 1):
        A[i, i + 1] = A[i + 1, i] = -J
        B[i, i + 1] = -J
        B[i + 1, i] = J
    sv = np.linalg.svd(A - B, compute_uv=False)
    return float(-G * n + 0.5 * (np.trace(A) - np.sum(sv)))


def exact_ground_energy(n):
    dim = 2 ** n
    H = np.zeros((dim, dim))
    zz = tfim_diag_terms(n)
    H[np.arange(dim), np.arange(dim)] = -J * zz
    # transverse field: -g * sum X_i -> off-diagonal bit flips
    idx = np.arange(dim)
    for q in range(n):
        flipped = idx ^ (1 << q)
        H[idx, flipped] += -G
    return float(np.linalg.eigvalsh(H)[0])


def variances_and_budget(psi, n):
    dim = 2 ** n
    p = np.abs(psi) ** 2
    zz = tfim_diag_terms(n)
    mz = float(p @ zz)
    vz = float(p @ zz ** 2 - mz ** 2)
    # X setting: rotate by H on every qubit == measure sum X in Z basis of rotated state
    had = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    psix = psi.copy()
    for q in range(n):
        psix = apply_1q(psix, had, q, n)
    px = np.abs(psix) ** 2
    idx = np.arange(dim)
    bits = ((idx[:, None] >> np.arange(n)) & 1)
    sx = np.sum(1 - 2 * bits, axis=1).astype(float)
    mx = float(px @ sx)
    vx = float(px @ sx ** 2 - mx ** 2)

    eps = 0.05 * n  # constant per-site precision
    delta = 0.05    # joint failure probability (matches the manuscript contract)
    n_groups = 2
    z = 1.959963984540054  # z_{1 - delta/2} for delta = 0.05
    # Group weights a_g = sum |c_j| per commuting group (shot values lie in [-a_g, a_g]).
    a_z, a_x = J * (n - 1), G * n
    a_tot = a_z + a_x
    # Worst-case allocation (manuscript eq. worstcase-shots): eps_g = eps*a_g/sum(a),
    # delta_g = delta/G, Hoeffding per group -> N_g = 2 (sum a)^2 ln(2G/delta) / eps^2,
    # identical for every group. Finite-sample, distribution-free.
    n_worst = int(np.ceil(2 * a_tot ** 2 * np.log(2 * n_groups / delta) / eps ** 2))
    worst = {"Z": n_worst, "X": n_worst}
    # Neyman variance-aware allocation (manuscript eq. neyman-shots): asymptotic,
    # N_total = z^2 (sum sigma)^2 / eps^2 split as N_g proportional to sigma_g.
    sz, sx_ = np.sqrt(max(vz, 1e-12)), np.sqrt(max(vx, 1e-12))
    tot_sigma = J * sz + G * sx_
    ney = {"Z": int(np.ceil(z ** 2 * J * sz * tot_sigma / eps ** 2)),
           "X": int(np.ceil(z ** 2 * G * sx_ * tot_sigma / eps ** 2))}
    return {"E_ansatz": -J * mz - G * mx, "var_Z": vz, "var_X": vx, "eps": eps,
            "delta": delta, "z_quantile": z,
            "worst": worst, "neyman": ney,
            "worst_total": worst["Z"] + worst["X"], "neyman_total": ney["Z"] + ney["X"]}


def aer_sample_time(n, shots):
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator
    qc = QuantumCircuit(n)
    for q in range(n):
        qc.ry(THETA1, q)
    for q in range(n - 1):
        qc.cx(q, q + 1)
    for q in range(n):
        qc.ry(THETA2, q)
    qc.measure_all()
    sim = AerSimulator(seed_simulator=SEED)
    tqc = transpile(qc, sim)
    t0 = time.perf_counter()
    sim.run(tqc, shots=shots).result()
    return time.perf_counter() - t0


def main():
    rng_rows = []
    for n in range(4, N_STATEVEC_MAX + 1, 2):
        row = {"n": n, "dim": 2 ** n}
        t0 = time.perf_counter()
        psi = ansatz_state(n)
        row["t_statevector_s"] = time.perf_counter() - t0
        budget = variances_and_budget(psi, n)
        row.update(budget)
        if n == 4:
            assert abs(budget["E_ansatz"] - (-4.653959235148468)) < 1e-9, \
                f"n=4 ansatz energy mismatch: {budget['E_ansatz']}"
        t0 = time.perf_counter()
        row["E0_free_fermion"] = free_fermion_ground_energy(n)
        row["t_free_fermion_s"] = time.perf_counter() - t0
        if n <= N_EXACT_MAX:
            t0 = time.perf_counter()
            row["E0_exact"] = exact_ground_energy(n)
            row["t_exact_diag_s"] = time.perf_counter() - t0
            assert abs(row["E0_exact"] - row["E0_free_fermion"]) < 1e-8, \
                f"n={n}: free-fermion E0 {row['E0_free_fermion']} != dense {row['E0_exact']}"
        t0 = time.perf_counter()
        row["t_aer_4096shots_s"] = aer_sample_time(n, SHOTS_FIXED)
        rng_rows.append(row)
        print(f"n={n:2d} done: ff={row['t_free_fermion_s']:.4f}s sv={row['t_statevector_s']:.3f}s"
              + (f" eig={row['t_exact_diag_s']:.3f}s" if "t_exact_diag_s" in row else " eig=skipped")
              + f" aer={row['t_aer_4096shots_s']:.3f}s neyman={row['neyman_total']:,}")

    lines = [f"{'n':>3} {'dim':>10} {'ff (s)':>9} {'eig (s)':>10} {'statevec (s)':>13} {'aer 4096 (s)':>13} {'eps':>6} {'Neyman shots':>13} {'worst shots':>13}",
             "-" * 104]
    for r in rng_rows:
        eig = f"{r['t_exact_diag_s']:.3f}" if "t_exact_diag_s" in r else "--"
        lines.append(f"{r['n']:>3} {r['dim']:>10,} {r['t_free_fermion_s']:>9.5f} {eig:>10} {r['t_statevector_s']:>13.3f} "
                     f"{r['t_aer_4096shots_s']:>13.3f} {r['eps']:>6.2f} {r['neyman_total']:>13,} {r['worst_total']:>13,}")
    table = "\n".join(lines)
    print("\n" + table)

    (OUTDIR / "sweep.json").write_text(json.dumps(rng_rows, indent=1), encoding="utf-8", newline="\n")
    (OUTDIR / "sweep_table.txt").write_text(table + "\n", encoding="utf-8", newline="\n")
    import qiskit
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "qiskit": qiskit.__version__,
        "params": {"J": J, "g": G, "theta1": THETA1, "theta2": THETA2,
                   "shots_fixed": SHOTS_FIXED, "eps_rule": "0.05*n", "delta": 0.05, "seed": SEED},
        "shot_formulas": {
            "worst": "N_g = ceil(2 (sum_h a_h)^2 ln(2G/delta) / eps^2), Hoeffding + union bound; finite-sample",
            "neyman": "N_g = ceil(z_{1-delta/2}^2 sigma_g (sum_h sigma_h) / eps^2); asymptotic normal, variance-target",
        },
        "baselines": {
            "free_fermion": "exact E0 via Jordan-Wigner (Pfeuty 1970), O(n^3); the matched classical opponent",
            "dense_eigh": "generic structure-blind solver, O(8^n); shown for contrast only, capped at n=14",
        },
        "note": "Wall times are single-run measurements on one workstation; scaling trend, not benchmark.",
    }
    (OUTDIR / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    sums = []
    for f in sorted(OUTDIR.glob("*")):
        if f.name == "SHA256SUMS.txt":
            continue
        sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (OUTDIR / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    print(f"\nwrote artifacts to {OUTDIR}")


if __name__ == "__main__":
    main()
