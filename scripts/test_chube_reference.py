#!/usr/bin/env python
"""Tests for the CHUBE reference implementation (deterministic, simulator-only).

Run directly (no pytest dependency): python scripts/test_chube_reference.py
These tests establish definitional correctness only; they make and support no
performance claims.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import chube_reference as ch  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[OK ] {name}")
    else:
        print(f"[FAIL] {name} {detail}")
        FAILURES.append(name)


def main() -> int:
    rng = np.random.default_rng(1234)
    bits = list(rng.integers(0, 2, size=ch.N_BITS))
    theta = ch.seeded_theta(1234)
    tau = 0.37

    # Windowing: exactly seven windows, correct indices.
    ws = ch.windows(bits)
    check("fourteen bits give exactly seven windows", len(ws) == 7)
    check("window indices are correct",
          all(ws[t] == tuple(bits[t:t + 8]) for t in range(7)))
    try:
        ch.windows(bits[:13])
        check("wrong-length input rejected", False)
    except ValueError:
        check("wrong-length input rejected", True)

    # Encoding: 0 -> |+>, 1 -> |->, normalized.
    plus = ch.encode_window((0,) * 8)
    check("all-zeros window encodes to |+>^8",
          np.allclose(plus, np.full(256, 1 / 16)))
    minus1 = ch.encode_window((1,) + (0,) * 7)
    expected = np.kron(ch.MINUS, ch._kron_all([ch.PLUS] * 7))
    check("leading 1 encodes first qubit to |->", np.allclose(minus1, expected))
    for w in ws:
        if abs(np.linalg.norm(ch.encode_window(w)) - 1.0) > 1e-12:
            check("encoded states are normalized", False, f"window {w}")
            break
    else:
        check("encoded states are normalized", True)
    # Distinct windows are orthogonal (basis states in a rotated basis).
    w_a, w_b = (0,) * 8, (0,) * 7 + (1,)
    check("distinct windows encode orthogonally",
          abs(np.vdot(ch.encode_window(w_a), ch.encode_window(w_b))) < 1e-12)

    # Shared unitary: unitarity / norm preservation, and reuse across windows.
    u = ch.shared_unitary(theta, tau)
    check("Hamiltonian evolution is unitary (preserves norm)",
          np.allclose(u.conj().T @ u, np.eye(256), atol=1e-10))
    feats, u_used = ch.stateless_features(bits, theta, tau)
    check("stateless features have shape (7, 16)", feats.shape == (7, 16))
    u_again = ch.shared_unitary(theta, tau)
    check("same parameters give the same shared unitary across windows",
          np.allclose(u_used, u_again))
    check("feature values are real expectations in [-1, 1]",
          bool(np.all(np.abs(feats) <= 1 + 1e-9)))

    # Eight-qubit guard: variant A objects never exceed 256 dimensions.
    check("stateless variant uses at most eight qubits",
          u_used.shape == (256, 256))

    # Recurrent channel: trace preservation, correct register split.
    m = 2
    rho_m = np.zeros((2 ** m, 2 ** m), dtype=complex)
    rho_m[0, 0] = 1.0
    v = ch.shared_unitary(theta, tau)  # any 8-qubit unitary is a valid V
    chunk = tuple(bits[:8 - m])
    rho_next = ch.recurrent_step(rho_m, chunk, v)
    check("recurrent update preserves density-matrix trace",
          abs(np.trace(rho_next).real - 1.0) < 1e-10)
    check("recurrent update keeps memory dimension",
          rho_next.shape == (2 ** m, 2 ** m))
    evals = np.linalg.eigvalsh(rho_next)
    check("recurrent output is positive semidefinite",
          bool(np.all(evals > -1e-10)))
    try:
        ch.recurrent_step(rho_m, tuple(bits[:5]), v)  # 2 + 5 != 8
        check("memory/data split must total eight qubits", False)
    except ValueError:
        check("memory/data split must total eight qubits", True)

    # Sweep: translated factors address the intended sites. All checks act on
    # vectors (the dense 2^14 x 2^14 operator is never materialized).
    n = ch.N_BITS
    u_local = ch.shared_unitary(theta, tau)
    psi = ch._kron_all([ch.MINUS if b else ch.PLUS for b in bits])

    def z_on_vec(vec, site):
        v = vec.reshape(2 ** site, 2, 2 ** (n - site - 1)).copy()
        v[:, 1, :] *= -1
        return v.reshape(-1)

    f0_psi = ch.sweep_factor_apply(psi, u_local, 0)
    ref = np.einsum("ab,bj->aj", u_local,
                    psi.reshape(2 ** 8, 2 ** (n - 8))).reshape(-1)
    check("sweep factor at t=0 acts on sites 0..7 and leaves 8..13 alone",
          np.allclose(f0_psi, ref))
    f6_psi = ch.sweep_factor_apply(psi, u_local, 6)
    ref6 = np.einsum("ab,ib->ia", u_local,
                     psi.reshape(2 ** 6, 2 ** 8)).reshape(-1)
    check("sweep factor at t=6 acts on sites 6..13 and leaves 0..5 alone",
          np.allclose(f6_psi, ref6))
    # A factor at offset 3 commutes with Z on site 2 (outside its window) but
    # not with Z on site 3 (inside it):
    lhs = ch.sweep_factor_apply(z_on_vec(psi, 2), u_local, 3)
    rhs = z_on_vec(ch.sweep_factor_apply(psi, u_local, 3), 2)
    check("t=3 factor commutes with Z on site 2 (outside its window)",
          np.allclose(lhs, rhs))
    lhs = ch.sweep_factor_apply(z_on_vec(psi, 3), u_local, 3)
    rhs = z_on_vec(ch.sweep_factor_apply(psi, u_local, 3), 3)
    check("t=3 factor does not commute with Z on site 3 (inside its window)",
          not np.allclose(lhs, rhs))
    try:
        ch.sweep_factor_apply(psi, u_local, 7)
        check("sweep offset out of range rejected", False)
    except ValueError:
        check("sweep offset out of range rejected", True)

    # Sweep preserves norm end to end.
    out = ch.sweep_apply(bits, theta, tau)
    check("full sweep preserves statevector norm",
          abs(np.linalg.norm(out) - 1.0) < 1e-10)
    check("full sweep uses the fourteen-qubit register",
          out.shape == (2 ** 14,))

    # Determinism: seed-controlled outputs are reproducible.
    feats2, _ = ch.stateless_features(bits, ch.seeded_theta(1234), tau)
    check("seed-controlled output is reproducible",
          np.allclose(feats, feats2))
    feats3, _ = ch.stateless_features(bits, ch.seeded_theta(9999), tau)
    check("different seed changes the output",
          not np.allclose(feats, feats3))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) failed: {', '.join(FAILURES)}")
        return 1
    print("All CHUBE reference tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
