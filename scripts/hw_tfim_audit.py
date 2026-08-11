"""Hardware-path TFIM audit: Qiskit implementation of the Appendix C circuits.

Purpose (three of the paper's open items):
1. INDEPENDENT VALIDATION OF ARIADION: the same preparation/measurement
   circuits are implemented in Qiskit (a third, independently developed
   stack) and the ideal distributions are compared against Ariadion's
   exported artifacts (artifacts/ideal_z.json, ideal_x.json) and against
   the in-script NumPy oracle.
2. HARDWARE BEHAVIOR: with --backend hardware this script submits the two
   measurement settings to a real IBM Quantum device via qiskit-ibm-runtime
   SamplerV2, ingests the device calibration snapshot (gate errors, readout
   errors, T1/T2), and evaluates the paper's Gate-4 screen P0 from MEASURED
   calibration data instead of representative rates.
3. CALIBRATION-GROUNDED SCREENING today: with --backend fake the same
   pipeline runs locally against an IBM fake backend that carries a real
   device's calibration snapshot and noise model, so every calculation is
   exercised end-to-end before hardware time is spent.

Energy reduction from joint counts is paper-artifact code (same convention
as scripts/demo_tfim_audit.py: outcome index bit i = qubit i, LSB-first).

Usage:
  python scripts/hw_tfim_audit.py --backend aer         # noiseless Aer check
  python scripts/hw_tfim_audit.py --backend fake        # FakeTorino w/ real calibration snapshot
  python scripts/hw_tfim_audit.py --backend hardware    # real device (needs QISKIT_IBM_TOKEN)

Artifacts land in artifacts/hardware/<backend-label>/ with manifest + SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent

# Same fixed circuit as Appendix C / scripts/demo_tfim_audit.py
THETA1 = 1.1148874287564283
THETA2 = 0.20641951023931937
N = 4
J = 1.0
HFIELD = 1.0
EPS = 0.05
DELTA = 0.05
SHOT_SEED = 20260811

# ---------------------------------------------------------------- oracle ---
I2 = np.eye(2)
PX = np.array([[0.0, 1.0], [1.0, 0.0]])
PZ = np.array([[1.0, 0.0], [0.0, -1.0]])
H1 = np.array([[1.0, 1.0], [1.0, -1.0]]) / math.sqrt(2.0)


def kron_at(op, i):
    m = np.array([[1.0]])
    for k in range(N - 1, -1, -1):
        m = np.kron(m, op if k == i else I2)
    return m


def oracle_state():
    def ry(t):
        c, s = math.cos(t / 2), math.sin(t / 2)
        return np.array([[c, -s], [s, c]])

    def cxm(c, t):
        dim = 2**N
        m = np.zeros((dim, dim))
        for b in range(dim):
            m[b ^ (1 << t) if (b >> c) & 1 else b, b] = 1.0
        return m

    psi = np.zeros(2**N)
    psi[0] = 1.0
    for i in range(N):
        psi = kron_at(ry(THETA1), i) @ psi
    for i in range(N - 1):
        psi = cxm(i, i + 1) @ psi
    for i in range(N):
        psi = kron_at(ry(THETA2), i) @ psi
    return psi


def oracle_hamiltonian():
    Hm = np.zeros((2**N, 2**N))
    for i in range(N - 1):
        Hm -= J * kron_at(PZ, i) @ kron_at(PZ, i + 1)
    for i in range(N):
        Hm -= HFIELD * kron_at(PX, i)
    return Hm


def group_value_z(m):
    s = [1.0 - 2.0 * ((m >> i) & 1) for i in range(N)]
    return -J * sum(s[i] * s[i + 1] for i in range(N - 1))


def group_value_x(m):
    s = [1.0 - 2.0 * ((m >> i) & 1) for i in range(N)]
    return -HFIELD * sum(s)


VALUE_FNS = {"Z": group_value_z, "X": group_value_x}


def energy_from_counts(counts_by_index, value_fn):
    total = sum(counts_by_index.values())
    return sum(c * value_fn(m) for m, c in counts_by_index.items()) / total


def stderr_from_counts(counts_by_index, value_fn):
    total = sum(counts_by_index.values())
    mu = energy_from_counts(counts_by_index, value_fn)
    var = sum(c * (value_fn(m) - mu) ** 2 for m, c in counts_by_index.items()) / total
    return math.sqrt(var / total)


# ---------------------------------------------------------------- qiskit ---
def build_circuits():
    from qiskit import QuantumCircuit

    def prep(qc):
        for q in range(N):
            qc.ry(THETA1, q)
        for q in range(N - 1):
            qc.cx(q, q + 1)
        for q in range(N):
            qc.ry(THETA2, q)

    z = QuantumCircuit(N, N, name="tfim_z_setting")
    prep(z)
    z.measure(range(N), range(N))

    x = QuantumCircuit(N, N, name="tfim_x_setting")
    prep(x)
    for q in range(N):
        x.h(q)
    x.measure(range(N), range(N))
    return {"Z": z, "X": x}


def counts_to_index(counts):
    """Qiskit count keys are 'c3c2c1c0' (clbit 0 rightmost). int(key,2) then
    has bit i = qubit i, matching the paper's LSB-first convention."""
    return {int(k.replace(" ", ""), 2): v for k, v in counts.items()}


def ideal_distributions():
    from qiskit.quantum_info import Statevector

    circs = build_circuits()
    out = {}
    for name, qc in circs.items():
        bare = qc.remove_final_measurements(inplace=False)
        sv = Statevector.from_instruction(bare)
        out[name] = np.array(sv.probabilities())  # index bit i = qubit i
    return out


def calibration_snapshot(backend):
    """Pull per-instruction errors and qubit coherence data from the target."""
    snap = {"backend_name": getattr(backend, "name", str(backend)),
            "num_qubits": getattr(backend, "num_qubits", None),
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            "instruction_errors": {}, "qubit_properties": []}
    target = getattr(backend, "target", None)
    if target is None:
        return snap
    for op_name in target.operation_names:
        errs = []
        try:
            props_map = target[op_name]
        except Exception:
            continue
        for qargs, props in props_map.items():
            err = getattr(props, "error", None)
            if err is not None:
                errs.append({"qubits": list(qargs), "error": err,
                             "duration": getattr(props, "duration", None)})
        if errs:
            snap["instruction_errors"][op_name] = errs
    qprops = getattr(target, "qubit_properties", None)
    if qprops:
        for i, qp in enumerate(qprops):
            snap["qubit_properties"].append({
                "qubit": i,
                "t1": getattr(qp, "t1", None),
                "t2": getattr(qp, "t2", None),
                "frequency": getattr(qp, "frequency", None),
            })
    return snap


def screen_p0_from_calibration(transpiled, snap):
    """Paper's Gate-4 screen P0 = product over executed operations of
    (1 - measured error), using per-(gate,qubits) calibration entries."""
    err_lookup = {}
    for op_name, entries in snap["instruction_errors"].items():
        for e in entries:
            err_lookup[(op_name, tuple(e["qubits"]))] = e["error"]

    p0 = 1.0
    used = {"1q": 0, "2q": 0, "measure": 0, "missing": 0}
    for inst in transpiled.data:
        name = inst.operation.name
        if name in ("barrier", "delay"):
            continue
        qubits = tuple(transpiled.find_bit(q).index for q in inst.qubits)
        err = err_lookup.get((name, qubits))
        if err is None:
            # median fallback for this op class
            pool = [e["error"] for e in snap["instruction_errors"].get(name, [])]
            err = statistics.median(pool) if pool else None
        if err is None:
            used["missing"] += 1
            continue
        p0 *= (1.0 - err)
        if name == "measure":
            used["measure"] += 1
        elif len(qubits) == 2:
            used["2q"] += 1
        else:
            used["1q"] += 1
    return p0, used


# ----------------------------------------------------------------- modes ---
def run_aer(circs, shots_map):
    from qiskit_aer import AerSimulator
    from qiskit import transpile

    backend = AerSimulator(seed_simulator=SHOT_SEED)
    results = {}
    for name, qc in circs.items():
        tqc = transpile(qc, backend, seed_transpiler=SHOT_SEED)
        res = backend.run(tqc, shots=shots_map[name]).result()
        results[name] = {"counts": counts_to_index(res.get_counts()),
                         "transpiled": tqc, "job_id": None}
    return results, {"backend_name": "AerSimulator(noiseless)",
                     "captured_utc": datetime.now(timezone.utc).isoformat(),
                     "instruction_errors": {}, "qubit_properties": []}


def get_fake_backend(fake_name):
    import qiskit_ibm_runtime.fake_provider as fp
    cls = getattr(fp, fake_name)
    return cls()


def run_sampler(backend, circs, shots_map, label):
    """SamplerV2 path: works in local testing mode (fake/Aer-from-backend)
    and against real hardware."""
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_ibm_runtime import SamplerV2

    pm = generate_preset_pass_manager(optimization_level=3, backend=backend,
                                      seed_transpiler=SHOT_SEED)
    sampler = SamplerV2(mode=backend)
    results = {}
    for name, qc in circs.items():
        tqc = pm.run(qc)
        job = sampler.run([tqc], shots=shots_map[name])
        job_id = getattr(job, "job_id", lambda: None)()
        res = job.result()[0]
        counts = res.data.c.get_counts() if hasattr(res.data, "c") else \
            next(iter(res.data.values())).get_counts()
        results[name] = {"counts": counts_to_index(counts),
                         "transpiled": tqc, "job_id": job_id}
        print(f"[{name}] {label}: shots={shots_map[name]}, job_id={job_id}")
    return results


def run_hardware(circs, shots_map, backend_name=None):
    from qiskit_ibm_runtime import QiskitRuntimeService

    token = os.environ.get("QISKIT_IBM_TOKEN")
    kwargs = {}
    if token:
        kwargs = {"channel": "ibm_quantum_platform", "token": token}
    service = QiskitRuntimeService(**kwargs)
    if backend_name:
        backend = service.backend(backend_name)
    else:
        backend = service.least_busy(operational=True, simulator=False, min_num_qubits=N)
    print(f"selected hardware backend: {backend.name} ({backend.num_qubits} qubits)")
    snap = calibration_snapshot(backend)
    results = run_sampler(backend, circs, shots_map, f"hardware:{backend.name}")
    return results, snap, backend


# ------------------------------------------------------------------ main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["aer", "fake", "hardware"], default="fake")
    ap.add_argument("--fake-name", default="FakeTorino")
    ap.add_argument("--backend-name", default=None,
                    help="fixed IBM backend name for --backend hardware "
                         "(default: least_busy, which is NOT reproducible)")
    ap.add_argument("--shots-scheme", choices=["neyman", "worst"], default="neyman")
    args = ap.parse_args()

    # oracle reference
    psi = oracle_state()
    Hm = oracle_hamiltonian()
    E_ref = float(psi @ (Hm @ psi))
    pz_oracle = np.abs(psi) ** 2
    psi_x = psi.copy()
    for i in range(N):
        psi_x = kron_at(H1, i) @ psi_x
    px_oracle = np.abs(psi_x) ** 2

    # shot budgets (identical arithmetic to demo_tfim_audit.py)
    def stats(probs, fn):
        vals = np.array([fn(m) for m in range(len(probs))])
        mu = float(probs @ vals)
        return mu, math.sqrt(float(probs @ (vals - mu) ** 2))

    _, sz = stats(pz_oracle, group_value_z)
    _, sx = stats(px_oracle, group_value_x)
    Z975 = 1.959963984540054
    shots_neyman = {"Z": math.ceil((Z975 / EPS) ** 2 * (sz + sx) * sz),
                    "X": math.ceil((Z975 / EPS) ** 2 * (sz + sx) * sx)}
    shots_worst = {}
    for name, a in (("Z", 3.0), ("X", 4.0)):
        eps_g, delta_g = EPS * a / 7.0, DELTA / 2
        shots_worst[name] = math.ceil(2 * a * a * math.log(2 / delta_g) / eps_g**2)
    shots_map = shots_neyman if args.shots_scheme == "neyman" else shots_worst
    print(f"shot budget ({args.shots_scheme}): {shots_map}")

    # cross-validation: Qiskit ideal vs oracle vs Ariadion artifacts
    ideal = ideal_distributions()
    assert np.allclose(ideal["Z"], pz_oracle, atol=1e-9)
    assert np.allclose(ideal["X"], px_oracle, atol=1e-9)
    cross = {"qiskit_vs_oracle": "PASS (atol 1e-9)"}
    for name, fname in (("Z", "ideal_z.json"), ("X", "ideal_x.json")):
        f = REPO / "artifacts" / fname
        if f.exists():
            ar = json.loads(f.read_text())["distribution"]["probabilities"]
            ok = np.allclose(np.array(ar), ideal[name], atol=1e-9)
            cross[f"qiskit_vs_ariadion_{name}"] = "PASS (atol 1e-9)" if ok else "FAIL"
            assert ok, f"Qiskit and Ariadion disagree on {name} setting"
    print("cross-validation (Qiskit vs oracle vs Ariadion artifacts):", cross)

    circs = build_circuits()
    backend_obj = None
    if args.backend == "aer":
        results, snap = run_aer(circs, shots_map)
        label = "aer"
    elif args.backend == "fake":
        backend_obj = get_fake_backend(args.fake_name)
        snap = calibration_snapshot(backend_obj)
        results = run_sampler(backend_obj, circs, shots_map, f"fake:{args.fake_name}")
        label = f"fake_{args.fake_name.lower()}"
    else:
        results, snap, backend_obj = run_hardware(circs, shots_map, args.backend_name)
        label = f"hardware_{snap['backend_name']}"

    # energy + error bars from counts (paper-artifact reduction)
    E_hat, se2 = 0.0, 0.0
    per_setting = {}
    for name in ("Z", "X"):
        e = energy_from_counts(results[name]["counts"], VALUE_FNS[name])
        se = stderr_from_counts(results[name]["counts"], VALUE_FNS[name])
        per_setting[name] = {"energy": e, "stderr": se}
        E_hat += e
        se2 += se * se
    E_se = math.sqrt(se2)
    print(f"\nE_ref (oracle exact)  = {E_ref:.6f}")
    print(f"E_hat ({label})       = {E_hat:.6f} +/- {E_se:.6f} (1 sigma)")
    print(f"deviation             = {E_hat - E_ref:+.6f} "
          f"({abs(E_hat - E_ref) / E_se:.1f} sigma)" if E_se > 0 else "")

    # calibration-grounded Gate-4 screen
    screen = None
    if snap["instruction_errors"]:
        p0s, useds = {}, {}
        for name in ("Z", "X"):
            p0, used = screen_p0_from_calibration(results[name]["transpiled"], snap)
            p0s[name], useds[name] = p0, used
        screen = {"P0_per_setting": p0s, "op_counts": useds}
        print(f"Gate-4 screen from measured calibration: P0_Z={p0s['Z']:.3f}, "
              f"P0_X={p0s['X']:.3f}")

    # archive
    outdir = REPO / "artifacts" / "hardware" / label
    outdir.mkdir(parents=True, exist_ok=True)
    from qiskit import qasm3

    files = []

    def emit(name, payload):
        p = outdir / name
        p.write_text(json.dumps(payload, indent=2, sort_keys=True),
                     encoding="utf-8", newline="\n")
        files.append(p)
        print(f"wrote {p.relative_to(REPO)}")

    for name in ("Z", "X"):
        emit(f"counts_{name.lower()}.json", {
            "setting": name, "shots": shots_map[name],
            "counts_by_outcome_index": {str(k): v for k, v in results[name]["counts"].items()},
            "job_id": results[name]["job_id"],
            "energy_estimate": per_setting[name]["energy"],
            "stderr": per_setting[name]["stderr"],
        })
        (outdir / f"transpiled_{name.lower()}.qasm3").write_text(
            qasm3.dumps(results[name]["transpiled"]), encoding="utf-8", newline="\n")
        files.append(outdir / f"transpiled_{name.lower()}.qasm3")
    emit("calibration_snapshot.json", snap)

    import qiskit, qiskit_aer, qiskit_ibm_runtime
    pip_freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                                capture_output=True, text=True, check=True
                                ).stdout.strip().splitlines()
    emit("manifest.json", {
        "purpose": ("hardware-path TFIM audit: independent Qiskit implementation "
                    "of the Appendix C circuits, cross-validated against the "
                    "NumPy oracle and Ariadion's exported ideal distributions"),
        "backend": label,
        "backend_kind": args.backend,
        "shots_scheme": args.shots_scheme,
        "shots": shots_map,
        "seed": SHOT_SEED if args.backend == "aer" else
                "device/sampler internal (job_id recorded)",
        "versions": {"python": platform.python_version(),
                     "qiskit": qiskit.__version__,
                     "qiskit_aer": qiskit_aer.__version__,
                     "qiskit_ibm_runtime": qiskit_ibm_runtime.__version__},
        "dependency_lock_pip_freeze": pip_freeze,
        "results": {"E_ref_oracle": E_ref, "E_hat": E_hat, "E_stderr": E_se,
                    "per_setting": per_setting},
        "cross_validation": cross,
        "calibration_screen": screen,
        "honesty": ("fake-backend runs use an archived real-device calibration "
                    "snapshot and noise model, not live hardware; hardware runs "
                    "are subject to drift between calibration and execution; "
                    "no advantage claim is made or implied"),
    })

    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
             for p in sorted(files, key=lambda q: q.name)]
    (outdir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8", newline="\n")
    print("wrote SHA256SUMS.txt")
    print("\nDONE.")


if __name__ == "__main__":
    main()
