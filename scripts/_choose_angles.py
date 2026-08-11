"""Offline one-time helper: choose fixed literal angles for the demo ansatz.

Ansatz: RY(t1) on all 4 qubits; CX chain (0-1,1-2,2-3); RY(t2) on all 4.
TFIM: H = -J sum Z_i Z_{i+1} - h sum X_i, J=h=1, open chain, n=4.
"""
import numpy as np
from itertools import product

n = 4
I2 = np.eye(2); X = np.array([[0,1],[1,0]],float); Z = np.array([[1,0],[0,-1]],float)

def kron_at(op, i):
    m = np.array([[1.0]])
    for k in range(n):
        m = np.kron(m, op if k == i else I2)
    return m

H = np.zeros((16,16))
for i in range(n-1):
    H -= kron_at(Z,i) @ kron_at(Z,i+1)
for i in range(n):
    H -= kron_at(X,i)

def ry(t):
    c, s = np.cos(t/2), np.sin(t/2)
    return np.array([[c,-s],[s,c]])

def cx_mat(c, t):
    m = np.zeros((16,16))
    for b in range(16):
        bits = [(b >> (n-1-k)) & 1 for k in range(n)]  # MSB-first, qubit0 = MSB
        if bits[c]:
            bits[t] ^= 1
        b2 = sum(bit << (n-1-k) for k, bit in enumerate(bits))
        m[b2, b] = 1
    return m

CX01, CX12, CX23 = cx_mat(0,1), cx_mat(1,2), cx_mat(2,3)

def state(t1, t2):
    psi = np.zeros(16); psi[0] = 1
    U1 = np.array([[1.0]])
    for _ in range(n):
        U1 = np.kron(U1, ry(t1))
    psi = U1 @ psi
    psi = CX23 @ (CX12 @ (CX01 @ psi))
    U2 = np.array([[1.0]])
    for _ in range(n):
        U2 = np.kron(U2, ry(t2))
    return U2 @ psi

def energy(t1, t2):
    p = state(t1, t2)
    return float(p @ (H @ p))

best = (1e9, 0, 0)
for t1 in np.linspace(0, np.pi, 61):
    for t2 in np.linspace(-np.pi/2, np.pi/2, 61):
        e = energy(t1, t2)
        if e < best[0]:
            best = (e, t1, t2)

# refine
e, t1, t2 = best
for _ in range(60):
    for dt in (0.01, 0.001, 0.0001, 1e-5):
        moved = True
        while moved:
            moved = False
            for d1, d2 in ((dt,0),(-dt,0),(0,dt),(0,-dt)):
                e2 = energy(t1+d1, t2+d2)
                if e2 < e:
                    e, t1, t2 = e2, t1+d1, t2+d2
                    moved = True

E0 = float(np.linalg.eigvalsh(H)[0])
print(f"t1={t1!r} t2={t2!r} E={e!r} E0={E0!r}")
