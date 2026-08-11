"""Fault-tolerant resource estimation for the manuscript's worked example (Section 4).

Runs the Microsoft (Azure Quantum) Resource Estimator locally via the `qdk`
Python package, replacing the paper's back-of-envelope screening numbers
(d >= 21, ~881k physical qubits) with tool output plus a sensitivity table.

Two workloads are estimated:

  A. The screening scenario from Section 4: 1,000 logical qubits and ~1e10
     fault locations. We map "fault locations" to a T-count-dominated logical
     workload (tCount = 1e10), stated explicitly as a modeling choice. This is
     a SYNTHETIC SENSITIVITY SCENARIO, not a compiled algorithm: no algorithmic
     trace or logical circuit backs the 1e10 T count, so the outputs quantify
     how the estimator's layered models respond to inputs of this size, and
     must not be quoted as a resource estimate for any actual application.

  B. The 4-qubit TFIM audit circuit from Appendix C (8 RY rotations, 3 CX,
     4 measurements) as a floor demonstration: even a trivial circuit incurs
     non-trivial FT overhead once rotations must be synthesized.

Sensitivity axes: qubit model (gate-based ns, 1e-3 vs 1e-4 error; Majorana
1e-4 vs 1e-6), total error budget (1e-1, 1e-2, 1e-3).

Outputs: artifacts/estimator/results.json, sensitivity_table.txt, manifest.
No network access is required; the estimator runs fully locally.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from qdk.estimator import LogicalCounts

ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "artifacts" / "estimator"
OUTDIR.mkdir(parents=True, exist_ok=True)

QUBIT_MODELS = [
    "qubit_gate_ns_e3",
    "qubit_gate_ns_e4",
    "qubit_maj_ns_e4",
    "qubit_maj_ns_e6",
]
ERROR_BUDGETS = [1e-1, 1e-2, 1e-3]

WORKLOADS = {
    # Section 4 screening scenario: 1,000 logical qubits, L = 1e10 fault
    # locations mapped to a T-count-dominated workload.
    "screening_1000q_1e10T": LogicalCounts({
        "numQubits": 1000,
        "tCount": 10_000_000_000,
        "rotationCount": 0,
        "rotationDepth": 0,
        "cczCount": 0,
        "measurementCount": 0,
    }),
    # Appendix C TFIM audit circuit (one measurement-setting instance):
    # 8 arbitrary-angle RY rotations (depth 2), 3 CX (Clifford, free at the
    # logical level), 4 terminal measurements.
    "tfim_audit_4q": LogicalCounts({
        "numQubits": 4,
        "tCount": 0,
        "rotationCount": 8,
        "rotationDepth": 2,
        "cczCount": 0,
        "measurementCount": 4,
    }),
}


def qec_scheme_for(qubit_model: str) -> str:
    return "floquet_code" if "maj" in qubit_model else "surface_code"


def run_all():
    rows = []
    full = {}
    for wname, counts in WORKLOADS.items():
        for qm in QUBIT_MODELS:
            for budget in ERROR_BUDGETS:
                params = {
                    "qubitParams": {"name": qm},
                    "qecScheme": {"name": qec_scheme_for(qm)},
                    "errorBudget": budget,
                }
                try:
                    res = run_one(counts, params)
                except Exception as exc:  # record failures honestly
                    rows.append((wname, qm, budget, "FAILED: %s" % exc))
                    continue
                key = f"{wname}|{qm}|budget={budget:g}"
                full[key] = res
                pq = res["physicalCounts"]["physicalQubits"]
                rt_ns = res["physicalCounts"]["runtime"]
                dist = res["logicalQubit"]["codeDistance"]
                lq = res["physicalCounts"]["breakdown"]["algorithmicLogicalQubits"]
                factories = res["physicalCounts"]["breakdown"].get("numTfactories", 0)
                rows.append((wname, qm, budget, dist, lq, pq, rt_ns, factories))
    return rows, full


def run_one(counts: LogicalCounts, params: dict) -> dict:
    result = counts.estimate(params)
    return json.loads(result.json) if hasattr(result, "json") and isinstance(result.json, str) else dict(result)


def fmt_time(ns: float) -> str:
    s = ns / 1e9
    if s < 1:
        return f"{ns/1e6:.1f} ms"
    if s < 3600:
        return f"{s:.1f} s"
    if s < 86400:
        return f"{s/3600:.2f} h"
    return f"{s/86400:.1f} d"


def main():
    rows, full = run_all()

    lines = []
    hdr = f"{'workload':<24} {'qubit model':<18} {'budget':>8} {'d':>4} {'logQ':>6} {'phys qubits':>14} {'runtime':>10} {'T-fac':>6}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in rows:
        if len(r) == 4:
            lines.append(f"{r[0]:<24} {r[1]:<18} {r[2]:>8g} {r[3]}")
        else:
            wname, qm, budget, dist, lq, pq, rt, fac = r
            lines.append(f"{wname:<24} {qm:<18} {budget:>8g} {dist:>4} {lq:>6} {pq:>14,} {fmt_time(rt):>10} {fac:>6}")
    table = "\n".join(lines)
    print(table)

    (OUTDIR / "sensitivity_table.txt").write_text(table + "\n", encoding="utf-8", newline="\n")
    (OUTDIR / "results.json").write_text(json.dumps(full, indent=1), encoding="utf-8", newline="\n")

    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tool": "Microsoft (Azure Quantum) Resource Estimator via qdk Python package, run locally",
        "workloads": {k: dict(v) for k, v in WORKLOADS.items()},
        "modeling_choices": [
            "Section 4's L=1e10 fault locations mapped to tCount=1e10 on 1000 logical qubits (T-count-dominated workload).",
            "screening_1000q_1e10T is a SYNTHETIC sensitivity scenario, not a compiled algorithm; do not quote as an application estimate.",
            "Post-layout logical qubit counts are model-dependent outputs of the estimator's layout model, not absolute corrections.",
            "Gate-based models use surface_code QEC; Majorana models use floquet_code.",
            "TFIM audit circuit counts taken from the untranspiled logical circuit: 8 RY, 3 CX (Clifford), 4 measurements.",
        ],
        "pip_freeze": freeze.splitlines(),
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
