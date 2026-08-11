"""Scale sweep for the TFIM audit pipeline (performance-at-scale evidence).

Sweeps chain length n for the transverse-field Ising model audit used in
Appendix C and measures, per n:

  * classical exact-diagonalization wall time (dense eigh, dim 2^n),
  * classical statevector ansatz evaluation wall time (the oracle path),
  * Qiskit Aer sampled execution wall time at a fixed 4,096 shots,
  * audit arithmetic: worst-case and Neyman shot budgets for the grouped
    Z- and X-setting measurements at fixed epsilon = 0.05 * n (constant
    per-site precision).

Purpose: document where the classical baseline wall actually is for this
family, and how the measurement budget grows, rather than asserting it.
Dense exact diagonalization is O(8^n) time / O(4^n) memory and is capped at
n = 14 here; statevector simulation continues to n = 24.

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
    # worst case variances: |ZZ| <= n-1 per string sum bound -> var <= (n-1)^2 ; X sum var <= n^2
    wz, wx = float((n - 1) ** 2), float(n ** 2)
    worst = {"Z": int(np.ceil(2 * wz * (np.sqrt(wz) + np.sqrt(wx)) / (np.sqrt(wz) * eps ** 2))) if wz > 0 else 0,
             "X": int(np.ceil(2 * wx * (np.sqrt(wz) + np.sqrt(wx)) / (np.sqrt(wx) * eps ** 2)))}
    sz, sx_ = np.sqrt(max(vz, 1e-12)), np.sqrt(max(vx, 1e-12))
    ney = {"Z": int(np.ceil(J ** 2 * sz * (J * sz + G * sx_) / (eps / 2) ** 2 / J ** 2)),
           "X": int(np.ceil(G ** 2 * sx_ * (J * sz + G * sx_) / (eps / 2) ** 2 / G ** 2))}
    # Simple Neyman: N_k = sigma_k * sum(sigma) / eps_k^2 with eps split evenly
    tot_sigma = J * sz + G * sx_
    ney = {"Z": int(np.ceil(J * sz * tot_sigma / (eps / np.sqrt(2)) ** 2)),
           "X": int(np.ceil(G * sx_ * tot_sigma / (eps / np.sqrt(2)) ** 2))}
    return {"E_ansatz": -J * mz - G * mx, "var_Z": vz, "var_X": vx, "eps": eps,
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
        if n <= N_EXACT_MAX:
            t0 = time.perf_counter()
            row["E0_exact"] = exact_ground_energy(n)
            row["t_exact_diag_s"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        row["t_aer_4096shots_s"] = aer_sample_time(n, SHOTS_FIXED)
        rng_rows.append(row)
        print(f"n={n:2d} done: sv={row['t_statevector_s']:.3f}s"
              + (f" eig={row['t_exact_diag_s']:.3f}s" if "t_exact_diag_s" in row else " eig=skipped")
              + f" aer={row['t_aer_4096shots_s']:.3f}s neyman={row['neyman_total']:,}")

    lines = [f"{'n':>3} {'dim':>10} {'eig (s)':>10} {'statevec (s)':>13} {'aer 4096 (s)':>13} {'eps':>6} {'Neyman shots':>13} {'worst shots':>13}",
             "-" * 90]
    for r in rng_rows:
        eig = f"{r['t_exact_diag_s']:.3f}" if "t_exact_diag_s" in r else "--"
        lines.append(f"{r['n']:>3} {r['dim']:>10,} {eig:>10} {r['t_statevector_s']:>13.3f} "
                     f"{r['t_aer_4096shots_s']:>13.3f} {r['eps']:>6.2f} {r['neyman_total']:>13,} {r['worst_total']:>13,}")
    table = "\n".join(lines)
    print("\n" + table)

    (OUTDIR / "sweep.json").write_text(json.dumps(rng_rows, indent=1), encoding="utf-8")
    (OUTDIR / "sweep_table.txt").write_text(table + "\n", encoding="utf-8")
    import qiskit
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "qiskit": qiskit.__version__,
        "params": {"J": J, "g": G, "theta1": THETA1, "theta2": THETA2,
                   "shots_fixed": SHOTS_FIXED, "eps_rule": "0.05*n", "seed": SEED},
        "note": "Wall times are single-run measurements on one workstation; scaling trend, not benchmark.",
    }
    (OUTDIR / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    sums = []
    for f in sorted(OUTDIR.glob("*")):
        if f.name == "SHA256SUMS.txt":
            continue
        sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (OUTDIR / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"\nwrote artifacts to {OUTDIR}")


if __name__ == "__main__":
    main()
