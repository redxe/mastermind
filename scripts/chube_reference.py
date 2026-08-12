#!/usr/bin/env python
"""CHUBE reference implementation (simulator-only, deterministic).

Convolutional Hamiltonian Updates with Basis Encoding — see
docs/research/chube-architecture.md. Status: PROPOSED / NOT EXECUTED research
support code. This module makes NO performance claims; it exists so the formal
definitions have one executable, testable meaning.

Variants implemented:
  A. Stateless filter  : encode window -> shared U_theta -> Pauli features.
  B. Recurrent channel : rho_M' = Tr_D[ V (rho_M (x) rho_D) V^dagger ].
  C. Coherent sweep    : U_sweep = prod_t exp(-i tau T^t h_theta T^-t) on 14 qubits.

All linear algebra is dense numpy/scipy; nothing here is efficient by design.
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import expm

N_BITS = 14
WINDOW = 8
N_WINDOWS = N_BITS - WINDOW + 1  # = 7

# Single-qubit primitives.
I2 = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Z = np.array([[1, 0], [0, -1]], dtype=complex)
H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
PLUS = np.array([1, 1], dtype=complex) / np.sqrt(2)
MINUS = np.array([1, -1], dtype=complex) / np.sqrt(2)


def windows(bits):
    """Return the seven overlapping eight-bit windows of a 14-bit input."""
    bits = list(bits)
    if len(bits) != N_BITS or any(b not in (0, 1) for b in bits):
        raise ValueError(f"input must be {N_BITS} bits")
    return [tuple(bits[t:t + WINDOW]) for t in range(N_WINDOWS)]


def _kron_all(ops):
    out = ops[0]
    for op in ops[1:]:
        out = np.kron(out, op)
    return out


def pauli_on(op, site, n_qubits):
    """Single-site operator embedded at `site` in an n-qubit register."""
    return _kron_all([op if j == site else I2 for j in range(n_qubits)])


def encode_window(w):
    """|phi_t> = H^{(x)8}|w_t>: 0 -> |+>, 1 -> |->. Returns a 256-dim vector."""
    if len(w) != WINDOW:
        raise ValueError("window must have 8 bits")
    return _kron_all([MINUS if b else PLUS for b in w])


def local_hamiltonian(theta):
    """Structured 8-qubit generator: sum of on-site X, on-site Z, and
    nearest-neighbor ZZ Pauli terms. theta has 8 + 8 + 7 = 23 coefficients."""
    theta = np.asarray(theta, dtype=float)
    if theta.shape != (2 * WINDOW + WINDOW - 1,):
        raise ValueError("theta must have 23 coefficients (8 X, 8 Z, 7 ZZ)")
    h = np.zeros((2 ** WINDOW, 2 ** WINDOW), dtype=complex)
    for j in range(WINDOW):
        h += theta[j] * pauli_on(X, j, WINDOW)
        h += theta[WINDOW + j] * pauli_on(Z, j, WINDOW)
    for j in range(WINDOW - 1):
        h += theta[2 * WINDOW + j] * (
            pauli_on(Z, j, WINDOW) @ pauli_on(Z, j + 1, WINDOW))
    return h


def shared_unitary(theta, tau):
    """U_theta = exp(-i H_theta tau)."""
    return expm(-1j * tau * local_hamiltonian(theta))


def default_observables():
    """Feature observables: Z_j and X_j for each of the 8 sites (K = 16)."""
    obs = [pauli_on(Z, j, WINDOW) for j in range(WINDOW)]
    obs += [pauli_on(X, j, WINDOW) for j in range(WINDOW)]
    return obs


def stateless_features(bits, theta, tau, observables=None):
    """Variant A: one shared U_theta reused across all seven windows.

    Returns (features, u) where features is a (7, K) real array and u is the
    single unitary object that was reused (so tests can verify sharing).
    Never allocates more than an eight-qubit (256-dim) state.
    """
    if observables is None:
        observables = default_observables()
    u = shared_unitary(theta, tau)  # built once, reused for every window
    assert u.shape == (2 ** WINDOW, 2 ** WINDOW)  # 8-qubit guard
    feats = np.empty((N_WINDOWS, len(observables)))
    for t, w in enumerate(windows(bits)):
        phi = u @ encode_window(w)
        assert phi.shape == (2 ** WINDOW,)  # never more than 8 qubits here
        for k, p in enumerate(observables):
            feats[t, k] = np.real(np.vdot(phi, p @ phi))
    return feats, u


def encode_chunk_density(chunk):
    """Density matrix of a phase-encoded chunk on len(chunk) qubits."""
    vec = _kron_all([MINUS if b else PLUS for b in chunk])
    return np.outer(vec, vec.conj())


def recurrent_step(rho_m, chunk, v):
    """Variant B: rho_M' = Tr_D[ V (rho_M (x) rho_D) V^dagger ].

    rho_m: density matrix on m memory qubits; chunk: (8 - m) fresh input bits;
    v: unitary on the full 8-qubit register (memory qubits first).
    """
    m_dim = rho_m.shape[0]
    d = len(chunk)
    m = int(np.log2(m_dim))
    if m + d != WINDOW:
        raise ValueError("memory qubits + chunk bits must equal 8")
    if v.shape != (2 ** WINDOW, 2 ** WINDOW):
        raise ValueError("step unitary must act on exactly 8 qubits")
    rho = np.kron(rho_m, encode_chunk_density(chunk))
    rho = v @ rho @ v.conj().T
    # Partial trace over the data register (last d qubits).
    d_dim = 2 ** d
    rho4 = rho.reshape(m_dim, d_dim, m_dim, d_dim)
    return np.einsum("ajbj->ab", rho4)


def sweep_factor_apply(state, u_local, t, n_qubits=N_BITS):
    """Apply exp(-i tau T^t h_theta T^-t) — i.e. the 8-qubit local update
    `u_local` translated to sites t..t+7 — to an n-qubit statevector, without
    ever materializing the dense 2^n x 2^n operator."""
    if not 0 <= t <= n_qubits - WINDOW:
        raise ValueError("offset out of range")
    if u_local.shape != (2 ** WINDOW, 2 ** WINDOW):
        raise ValueError("local update must act on exactly 8 qubits")
    left, right = 2 ** t, 2 ** (n_qubits - WINDOW - t)
    psi = state.reshape(left, 2 ** WINDOW, right)
    return np.einsum("ab,ibj->iaj", u_local, psi).reshape(-1)


def sweep_apply(bits, theta, tau):
    """Variant C: apply U_sweep = prod_t exp(-i tau T^t h_theta T^-t) to
    H^{(x)14}|x>.

    Factors are applied in increasing t (t = 0 factor acts first). Requires a
    full 14-qubit statevector; this is deliberately NOT an 8-qubit computation.
    The same local unitary object is reused (translated) at every offset.
    """
    u_local = shared_unitary(theta, tau)
    state = _kron_all([MINUS if b else PLUS for b in bits])
    for t in range(N_WINDOWS):
        state = sweep_factor_apply(state, u_local, t)
    return state


def seeded_theta(seed):
    """Deterministic parameter vector for tests and demos."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.5, size=2 * WINDOW + WINDOW - 1)
