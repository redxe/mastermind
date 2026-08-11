"""Bounded Schwinger-model instantiation for Section 9's workflow checklist.

Model: lattice Schwinger model (QED in 1+1D), Kogut--Susskind staggered
fermions, open boundary conditions, gauge links eliminated via Gauss's law,
mapped to N qubits by Jordan--Wigner. Dimensionless Hamiltonian
(Klco et al., PRA 98, 032331 (2018) conventions):

  H = x * sum_{n=0}^{N-2} (sp_n sm_{n+1} + h.c.)
    + (mu/2) * sum_n (-1)^n Z_n
    + sum_{n=0}^{N-2} L_n^2,
  L_n = eps0 + (1/2) * sum_{l<=n} (Z_l + (-1)^l).

Bounded instance: N = 4 sites (4 qubits, dim 16), x = 0.6, mu = 0.1,
eps0 = 0 (zero background field). Truncation statement: with OBC and Gauss
law, link fields are exactly eliminated -- the only truncations are lattice
spacing (fixed by x) and volume (N = 4); no bosonic cutoff is needed.

Question instantiated: the real-time response
  C(t) = <psi0| O(t) O(0) |psi0>,  O = Z_{N/2} (charge density at a bulk site)
for t in [0, 5] with total error epsilon = 0.05 split as:
  eps_trotter = 0.02 (2nd-order Trotter, empirical error vs exact expm),
  eps_meas    = 0.03 (per-point Hadamard-test statistical error, 1 sigma).

Outputs (artifacts/schwinger/): results.json, budget_table.txt, manifest.json,
SHA256SUMS.txt. Baseline is exact diagonalization (dim 16); everything here is
classical and serves as the pre-registered baseline the workflow demands.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.linalg import expm

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "artifacts" / "schwinger"
OUTDIR.mkdir(parents=True, exist_ok=True)

N = 4
X_HOP = 0.6
MU = 0.1
EPS0 = 0.0
T_GRID = [0.5, 1.0, 2.0, 3.0, 5.0]
EPS_TROTTER = 0.02
EPS_MEAS = 0.03

I2 = np.eye(2)
SX = np.array([[0, 1], [1, 0]], dtype=complex)
SY = np.array([[0, -1j], [1j, 0]], dtype=complex)
SZ = np.array([[1, 0], [0, -1]], dtype=complex)
PAULI = {"I": I2, "X": SX, "Y": SY, "Z": SZ}


def kron_chain(ops):
    # qubit 0 = leftmost lattice site; LSB-first convention matches the paper
    m = ops[0]
    for o in ops[1:]:
        m = np.kron(o, m)
    return m


def pauli_op(string):
    """string like 'XZYI' with index i = qubit i."""
    return kron_chain([PAULI[c] for c in string])


def single(op, n):
    s = ["I"] * N
    s[n] = op
    return pauli_op("".join(s))


def build_hamiltonian():
    dim = 2 ** N
    H = np.zeros((dim, dim), dtype=complex)
    # hopping: x * (sp_n sm_{n+1} + h.c.) = (x/2)(X_n X_{n+1} + Y_n Y_{n+1})
    for n in range(N - 1):
        sxn, sxn1 = single("X", n), single("X", n + 1)
        syn, syn1 = single("Y", n), single("Y", n + 1)
        H += (X_HOP / 2.0) * (sxn @ sxn1 + syn @ syn1)
    # mass term
    for n in range(N):
        H += (MU / 2.0) * ((-1) ** n) * single("Z", n)
    # electric energy: sum over links of L_n^2
    for n in range(N - 1):
        L = EPS0 * np.eye(2 ** N, dtype=complex)
        for l in range(n + 1):
            L += 0.5 * (single("Z", l) + ((-1) ** l) * np.eye(2 ** N))
        H += L @ L
    return H


def pauli_decompose(H):
    terms = {}
    for combo in itertools.product("IXYZ", repeat=N):
        s = "".join(combo)
        P = pauli_op(s)
        c = np.trace(P @ H).real / (2 ** N)
        if abs(c) > 1e-12:
            terms[s] = c
    return terms


def qubitwise_commute(a, b):
    return all(pa == "I" or pb == "I" or pa == pb for pa, pb in zip(a, b))


def group_terms(terms):
    groups = []
    for s in sorted(terms, key=lambda k: -abs(terms[k])):
        for g in groups:
            if all(qubitwise_commute(s, m) for m in g):
                g.append(s)
                break
        else:
            groups.append([s])
    return groups


def trotter2_step(h_parts, dt):
    """Second-order Trotter step from a list of Hermitian parts."""
    halves = [expm(-1j * h * dt / 2) for h in h_parts]
    U = np.eye(2 ** N, dtype=complex)
    for u in halves:
        U = u @ U
    for u in reversed(halves):
        U = u @ U
    return U


def main():
    H = build_hamiltonian()
    assert np.allclose(H, H.conj().T)
    evals, evecs = np.linalg.eigh(H)
    E0 = evals[0]
    psi0 = evecs[:, 0]

    terms = pauli_decompose(H)
    groups = group_terms(terms)

    # ground-state variance per group -> Neyman shot allocation for <H>
    group_stats = []
    for g in groups:
        Og = sum(terms[s] * pauli_op(s) for s in g)
        mean = (psi0.conj() @ Og @ psi0).real
        var = (psi0.conj() @ (Og @ Og) @ psi0).real - mean ** 2
        group_stats.append({"paulis": g, "mean": mean, "variance": max(var, 0.0)})
    sigmas = np.array([np.sqrt(gs["variance"]) for gs in group_stats])
    eps_H = 0.01 * abs(E0)  # 1% relative precision target on <H>
    if sigmas.sum() > 0:
        shots = np.ceil(sigmas * sigmas.sum() / eps_H ** 2).astype(int)
    else:
        shots = np.zeros(len(sigmas), dtype=int)
    total_energy_shots = int(shots.sum())

    # real-time response C(t) = <psi0| O(t) O |psi0>, O = Z at bulk site N//2
    O = single("Z", N // 2)
    exact_C = {}
    for t in T_GRID:
        U = expm(-1j * H * t)
        exact_C[t] = complex(psi0.conj() @ U.conj().T @ O @ U @ O @ psi0)

    # 2nd-order Trotter with parts: hopping (odd/even bonds), mass, electric
    h_hop_even = sum(
        (X_HOP / 2.0) * (single("X", n) @ single("X", n + 1) + single("Y", n) @ single("Y", n + 1))
        for n in range(0, N - 1, 2))
    h_hop_odd = sum(
        ((X_HOP / 2.0) * (single("X", n) @ single("X", n + 1) + single("Y", n) @ single("Y", n + 1))
         for n in range(1, N - 1, 2)), np.zeros((2 ** N, 2 ** N), dtype=complex))
    h_diag = H - h_hop_even - h_hop_odd  # mass + electric (diagonal in Z)
    parts = [h_hop_even, h_hop_odd, h_diag]

    trotter = {}
    for t in T_GRID:
        r = 1
        while True:
            U = np.linalg.matrix_power(trotter2_step(parts, t / r), r)
            Ct = complex(psi0.conj() @ U.conj().T @ O @ U @ O @ psi0)
            err = abs(Ct - exact_C[t])
            if err <= EPS_TROTTER or r > 4096:
                break
            r *= 2
        trotter[t] = {"steps": r, "C_trotter": [Ct.real, Ct.imag],
                      "C_exact": [exact_C[t].real, exact_C[t].imag],
                      "abs_error": err}

    # Hadamard-test measurement budget: Re and Im each estimated from a
    # +/-1-valued ancilla measurement, variance <= 1 per shot.
    shots_per_point = int(np.ceil(1.0 / EPS_MEAS ** 2))  # per quadrature
    total_response_shots = 2 * shots_per_point * len(T_GRID)

    lines = []
    lines.append(f"Schwinger model, N={N} staggered sites (OBC, links eliminated), x={X_HOP}, mu={MU}, eps0={EPS0}")
    lines.append(f"Hilbert dim = {2**N}; exact E0 = {E0:.9f}")
    lines.append(f"Pauli terms = {len(terms)}; qubit-wise-commuting groups = {len(groups)}")
    lines.append(f"<H> to +/-{eps_H:.4f} (1% of |E0|), Neyman over groups: {total_energy_shots:,} shots")
    lines.append("")
    lines.append(f"{'t':>5} {'Re C exact':>12} {'Im C exact':>12} {'Trotter r':>10} {'|err|':>10}")
    for t in T_GRID:
        d = trotter[t]
        lines.append(f"{t:>5} {d['C_exact'][0]:>12.6f} {d['C_exact'][1]:>12.6f} {d['steps']:>10} {d['abs_error']:>10.2e}")
    lines.append("")
    lines.append(f"Hadamard-test budget: {shots_per_point:,} shots/quadrature/point x 2 x {len(T_GRID)} points = {total_response_shots:,} shots (eps_meas={EPS_MEAS}, 1 sigma)")
    table = "\n".join(lines)
    print(table)

    results = {
        "model": {"N": N, "x": X_HOP, "mu": MU, "eps0": EPS0, "boundary": "open",
                  "truncation": "links eliminated exactly via Gauss law (OBC); only lattice spacing and volume truncations remain"},
        "exact": {"E0": E0, "spectrum": evals.tolist()},
        "pauli_terms": terms,
        "groups": group_stats,
        "energy_budget": {"eps_H": eps_H, "shots_per_group": shots.tolist(), "total_shots": total_energy_shots},
        "response": {str(t): trotter[t] for t in T_GRID},
        "measurement_budget": {"eps_meas": EPS_MEAS, "shots_per_quadrature_per_point": shots_per_point,
                               "total_shots": total_response_shots},
        "error_split": {"eps_trotter": EPS_TROTTER, "eps_meas": EPS_MEAS},
    }
    (OUTDIR / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    (OUTDIR / "budget_table.txt").write_text(table + "\n", encoding="utf-8")
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "note": "Fully classical baseline instantiation of the Section 9 workflow for a bounded model; no quantum execution claimed.",
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
