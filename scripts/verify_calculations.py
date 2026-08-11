"""Verify every numerical claim in Section 4 of the manuscript.

Run:  python scripts/verify_calculations.py
Requires: numpy (standard library math would suffice; numpy used for clarity).

Each block prints the manuscript value and the independently derived value.
"""

import math

PASS = True


def check(name, computed, manuscript, rel_tol=0.02):
    global PASS
    ok = math.isclose(computed, manuscript, rel_tol=rel_tol)
    PASS = PASS and ok
    print(f"{'OK ' if ok else 'FAIL'} {name}: computed={computed:.6g}, manuscript={manuscript:.6g}")


print("=" * 70)
print("1. Hoeffding bound for a single observable in [-1, 1]")
print("   Range b-a = 2  =>  N >= 2 ln(2/delta) / eps^2   (NOT ln(2/delta)/(2 eps^2))")
eps, delta = 0.01, 0.05
n_hoeffding = 2 * math.log(2 / delta) / eps**2
print(f"   eps={eps}, delta={delta}  ->  N >= {n_hoeffding:,.0f}")
check("single-observable Hoeffding (corrected eq:hoeffding)", n_hoeffding, 73778, rel_tol=0.01)

print("=" * 70)
print("2. Toy noise screen P0 (eq:nisq-screen worked example)")
lnP0 = 600 * math.log(0.9998) + 300 * math.log(0.995) + 40 * math.log(0.985) - 0.15
check("ln P0", lnP0, -2.38, rel_tol=0.01)
check("P0", math.exp(lnP0), 0.093, rel_tol=0.01)

print("=" * 70)
print("3. Grouped worst-case (union-bound Hoeffding) shot budget, eq:worstcase-shots")
G = 40
a_g = 0.025          # each group's weight; sum_g a_g = 1 (declared toy normalization)
sum_a = G * a_g
eps_g = eps * a_g / sum_a           # proportional error allocation
delta_g = delta / G                 # union bound
# per-shot outcome of group g lies in [-a_g, a_g], range 2 a_g:
N_g = 2 * a_g**2 * math.log(2 / delta_g) / eps_g**2
N_total_worst = G * math.ceil(N_g)
t_worst_h = N_total_worst * 2e-3 / 3600  # ASSUMPTION: 2 ms per shot
print(f"   N_g = {N_g:,.0f}  (manuscript: ~1.5e5)")
print(f"   N_total = {N_total_worst:,.0f}  (manuscript: ~5.9e6)")
print(f"   wall time at 2 ms/shot = {t_worst_h:.2f} h  (manuscript: ~3.3 h)")
check("N_g", N_g, 1.5e5, rel_tol=0.02)
check("N_total worst-case", N_total_worst, 5.9e6, rel_tol=0.01)
check("hours worst-case", t_worst_h, 3.3, rel_tol=0.01)

print("=" * 70)
print("4. Variance-aware (Neyman) budget, eq:neyman-shots")
z = 1.959963984540054  # z_{1-0.05/2}
sigma_g = a_g          # sigma_g at its bound (worst case for this formula)
sum_sigma = G * sigma_g
N_neyman = z**2 * sum_sigma**2 / eps**2
t_neyman_min = math.ceil(N_neyman) * 2e-3 / 60
print(f"   N = {N_neyman:,.0f}  (manuscript: ~3.8e4)")
print(f"   wall time at 2 ms/shot = {t_neyman_min:.2f} min  (manuscript: ~1.3 min)")
check("N Neyman", N_neyman, 3.8e4, rel_tol=0.02)
check("minutes Neyman", t_neyman_min, 1.3, rel_tol=0.02)
print(f"   ratio worst-case / Neyman = {N_total_worst / N_neyman:.0f}x")
print("   NOTE: guarantees differ. Hoeffding: finite-sample, distribution-free,")
print("   joint confidence via union bound. Neyman: asymptotic CLT on Var(H_hat)=")
print("   sum_g sigma_g^2/N_g, requires measured variances (pilot cost G*N_pilot).")

print("=" * 70)
print("5. Surface-code screening distance and memory floor (eq:distance)")
L, delta_qec, A, ratio = 1e10, 1e-2, 0.1, 0.1
d_min = 2 * math.log(delta_qec / (A * L)) / math.log(ratio) - 1
d = math.ceil(round(d_min, 9))  # round first: d_min is exactly 21.0 up to fp noise
if d % 2 == 0:
    d += 1  # surface-code distances are odd
mem = 2 * d**2 - 1
check("screening distance d", d, 21, rel_tol=0)
check("rotated-code memory qubits/logical (2d^2-1)", mem, 881, rel_tol=0)
check("1000-logical-qubit memory floor", 1000 * mem, 881000, rel_tol=0)
print("   (memory-only floor: excludes factories, routing, buffer, control)")

print("=" * 70)
print("ALL CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
