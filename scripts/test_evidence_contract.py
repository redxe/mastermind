#!/usr/bin/env python
"""Tests for the evidence-contract schema, CLI, hash-locking, and aggregation rule.

Run directly (no pytest dependency): python scripts/test_evidence_contract.py
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import evidence_contract as ec  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[OK ] {name}")
    else:
        print(f"[FAIL] {name} {detail}")
        FAILURES.append(name)


def main() -> int:
    schema = ec.load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    check("schema is a valid Draft 2020-12 schema", True)

    example = REPO / "examples" / "tfim-evidence-contract.yaml"
    errors = ec.validate_contract(example, schema)
    check("TFIM example contract validates", not errors, "; ".join(errors[:3]))

    doc = ec.load_contract(example)

    # Schema must reject removal of each required top-level section.
    for field in ["claim", "baseline_policy", "metrics", "allowed_variations",
                  "decision_rules", "missing_evidence_policy", "outcome_taxonomy",
                  "environment"]:
        broken = copy.deepcopy(doc)
        del broken[field]
        errs = jsonschema.Draft202012Validator(schema)
        bad = list(errs.iter_errors(broken))
        check(f"schema rejects missing {field}", bool(bad))

    # Schema must reject a tampered outcome taxonomy and unknown fields.
    broken = copy.deepcopy(doc)
    broken["outcome_taxonomy"] = ["Pass", "Fail"]
    check("schema rejects altered outcome taxonomy",
          bool(list(jsonschema.Draft202012Validator(schema).iter_errors(broken))))
    broken = copy.deepcopy(doc)
    broken["surprise_field"] = 1
    check("schema rejects unknown top-level fields",
          bool(list(jsonschema.Draft202012Validator(schema).iter_errors(broken))))
    broken = copy.deepcopy(doc)
    broken["baseline_policy"]["escalation_rules"] = []
    check("schema rejects empty escalation rules",
          bool(list(jsonschema.Draft202012Validator(schema).iter_errors(broken))))

    # Corpus manifest parses and references this contract.
    manifest = yaml.safe_load(ec.MANIFEST_PATH.read_text(encoding="utf-8"))
    entry = manifest["claims"]["tfim-freefermion-baseline"]
    check("corpus manifest references the TFIM contract",
          entry["contract"] == "examples/tfim-evidence-contract.yaml")

    # Hash-locking: sealing must refuse placeholders without the pilot flag,
    # must be reproducible, and must detect tampering.
    files, placeholders = ec._sealed_files()
    check("placeholder claims detected before seal", len(placeholders) >= 1)
    check("sealed file set includes schema/protocol/manifest/contract",
          {ec.SCHEMA_PATH, ec.PROTOCOL_PATH, ec.MANIFEST_PATH, example} <= set(files))
    h1 = ec.sha256_file(example)
    h2 = ec.sha256_file(example)
    check("hashing is deterministic", h1 == h2)
    tampered = example.read_bytes() + b"\n# tampered"
    import hashlib
    check("tampering changes the hash",
          hashlib.sha256(tampered).hexdigest() != h1)

    # CLI: validate succeeds on the example, fails on a broken temp contract.
    rc = ec.main(["validate", str(example)])
    check("CLI validate exits 0 on valid contract", rc == 0)
    tmp = REPO / "build" / "test-broken-contract.yaml"
    tmp.parent.mkdir(exist_ok=True)
    broken = copy.deepcopy(doc)
    del broken["claim"]
    tmp.write_text(yaml.safe_dump(broken), encoding="utf-8")
    rc = ec.main(["validate", str(tmp)])
    check("CLI validate exits 1 on invalid contract", rc == 1)
    tmp.unlink()

    # Aggregation rule standard-v1 (protocol section 5).
    agg = ec.aggregate_standard_v1
    check("all supported -> Stable",
          agg(["supported"] * 3, artifacts_ok=True, escalation_unhonored=False) == "Stable")
    check("supported + indeterminate -> Conditionally Stable",
          agg(["supported", "indeterminate"], artifacts_ok=True,
              escalation_unhonored=False) == "Conditionally Stable")
    check("supported + reversed -> Unresolved",
          agg(["supported", "reversed"], artifacts_ok=True,
              escalation_unhonored=False) == "Unresolved")
    check("all reversed -> Reversed",
          agg(["reversed", "reversed"], artifacts_ok=True,
              escalation_unhonored=False) == "Reversed")
    check("only indeterminate -> Not Auditable",
          agg(["indeterminate"], artifacts_ok=True,
              escalation_unhonored=False) == "Not Auditable")
    check("missing artifacts -> Not Auditable",
          agg(["supported"] * 3, artifacts_ok=False,
              escalation_unhonored=False) == "Not Auditable")
    check("unhonored non-mandatory escalation caps Stable at Conditionally Stable",
          agg(["supported"] * 3, artifacts_ok=True,
              escalation_unhonored=True,
              strongest_known_required=False) == "Conditionally Stable")
    check("unhonored MANDATORY escalation -> Not Auditable",
          agg(["supported"] * 3, artifacts_ok=True,
              escalation_unhonored=True,
              strongest_known_required=True) == "Not Auditable")
    check("honored escalation leaves Stable intact even when mandatory",
          agg(["supported"] * 3, artifacts_ok=True,
              escalation_unhonored=False,
              strongest_known_required=True) == "Stable")

    # --- Seal-hash verification (adversarial) -------------------------------
    files, placeholders = ec._sealed_files()
    seal = ec.build_seal(files, placeholders)
    check("freshly built seal verifies", ec.verify_seal_data(seal) == [])
    tampered_seal = copy.deepcopy(seal)
    tampered_seal["placeholders_forced"] = False
    check("modified seal metadata is rejected",
          any("seal_hash mismatch" in p for p in ec.verify_seal_data(tampered_seal)))
    tampered_seal = copy.deepcopy(seal)
    first_key = next(iter(tampered_seal["files"]))
    del tampered_seal["files"][first_key]
    check("deleted file entry is rejected",
          bool(ec.verify_seal_data(tampered_seal)))
    tampered_seal = copy.deepcopy(seal)
    tampered_seal["files"]["specs/injected.yaml"] = "0" * 64
    check("added file entry is rejected",
          bool(ec.verify_seal_data(tampered_seal)))
    check("malformed seal (non-object) is rejected",
          bool(ec.verify_seal_data(["not", "a", "seal"])))
    check("malformed seal (no files) is rejected",
          bool(ec.verify_seal_data({"seal_hash": "0" * 64})))
    check("malformed seal (no seal_hash) is rejected",
          bool(ec.verify_seal_data({"files": {"x": "0" * 64}})))
    # Changed referenced file: rewrite an entry hash and recompute the seal
    # hash so only the file-content check can catch it.
    tampered_seal = copy.deepcopy(seal)
    rel = next(iter(tampered_seal["files"]))
    tampered_seal["files"][rel] = "f" * 64
    tampered_seal["seal_hash"] = ec.compute_seal_hash(tampered_seal)
    check("changed referenced file is rejected",
          any("hash mismatch" in p for p in ec.verify_seal_data(tampered_seal)))

    # --- Results schema and derived verdicts --------------------------------
    results_schema = ec.load_results_schema()
    jsonschema.Draft202012Validator.check_schema(results_schema)
    check("results schema is a valid Draft 2020-12 schema", True)

    def passing_metrics() -> dict:
        return {
            "energy-accuracy": {"value": 0.5, "uncertainty": 1.0,
                                "uncertainty_sources": ["shot-noise", "baseline"]},
            "cost-crossover": {"value": 0.01, "uncertainty": 0.005, "reference": 1.0,
                               "uncertainty_sources": ["shot-noise", "baseline"]},
        }

    def full_grid_results(**overrides) -> dict:
        names, grid = ec.expected_variation_grid(doc)
        variations = []
        for i, combo in enumerate(sorted(grid, key=repr)):
            variations.append({
                "id": f"var-{i}",
                "dimensions": dict(zip(names, combo)),
                "metrics": passing_metrics(),
            })
        res = {
            "contract_id": doc["contract_id"],
            "variations": variations,
            "baseline": {
                "identity": "free-fermion-svd (scripts/scale_sweep.py)",
                "evidence": ["scripts/scale_sweep.py"],
                "matched_inputs": True,
            },
            "escalation": {"trigger_fired": True, "honored": True},
        }
        res.update(overrides)
        return res

    def evaluate(res: dict) -> dict:
        rpath = REPO / "build" / "test-results.json"
        rpath.parent.mkdir(exist_ok=True)
        rpath.write_text(json.dumps(res), encoding="utf-8")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ec.main(["evaluate", str(example), "--results", str(rpath)])
        rpath.unlink()
        report = json.loads(buf.getvalue())
        report["_rc"] = rc
        return report

    report = evaluate(full_grid_results())
    check("full passing grid with verified escalation -> Stable",
          report["outcome"] == "Stable", str(report))

    # Adversarial: caller-supplied verdicts are rejected by the results schema.
    res = full_grid_results()
    res["variations"][0]["verdict"] = "supported"
    report = evaluate(res)
    check("caller-supplied verdict fails closed as Not Auditable",
          report["outcome"] == "Not Auditable")

    # Adversarial: a single favorable variation cannot produce Stable.
    res = full_grid_results()
    res["variations"] = res["variations"][:1]
    report = evaluate(res)
    check("single favorable variation cannot yield Stable (not-auditable policy)",
          report["outcome"] == "Not Auditable")

    # Adversarial: duplicate variation combination is rejected.
    res = full_grid_results()
    res["variations"][1]["dimensions"] = dict(res["variations"][0]["dimensions"])
    report = evaluate(res)
    check("duplicate variation combination fails closed",
          report["outcome"] == "Not Auditable")

    # Adversarial: unknown dimension name is rejected.
    res = full_grid_results()
    res["variations"][0]["dimensions"]["favorable_knob"] = 1
    report = evaluate(res)
    check("unknown dimension fails closed", report["outcome"] == "Not Auditable")

    # Adversarial: undeclared dimension value is rejected.
    res = full_grid_results()
    res["variations"][0]["dimensions"]["transpiler_seed"] = 99999
    report = evaluate(res)
    check("undeclared dimension value fails closed",
          report["outcome"] == "Not Auditable")

    # Adversarial: contract_id mismatch is rejected.
    res = full_grid_results(contract_id="some-other-claim")
    report = evaluate(res)
    check("contract_id mismatch fails closed", report["outcome"] == "Not Auditable")

    # Uncovered mandatory uncertainty source -> that variation is indeterminate.
    res = full_grid_results()
    res["variations"][0]["metrics"]["energy-accuracy"]["uncertainty_sources"] = ["shot-noise"]
    report = evaluate(res)
    check("missing mandatory uncertainty source -> Conditionally Stable",
          report["outcome"] == "Conditionally Stable")

    # Confident tolerance failure -> reversed -> Unresolved with the rest supported.
    res = full_grid_results()
    res["variations"][0]["metrics"]["energy-accuracy"] = {
        "value": 50.0, "uncertainty": 1.0,
        "uncertainty_sources": ["shot-noise", "baseline"]}
    report = evaluate(res)
    check("confident metric failure -> Unresolved",
          report["outcome"] == "Unresolved")

    # Non-confident tolerance failure -> indeterminate, not reversed.
    res = full_grid_results()
    res["variations"][0]["metrics"]["energy-accuracy"] = {
        "value": 1.5, "uncertainty": 1.0,
        "uncertainty_sources": ["shot-noise", "baseline"]}
    report = evaluate(res)
    check("non-confident failure is indeterminate -> Conditionally Stable",
          report["outcome"] == "Conditionally Stable")

    # evidence_missing on one variation -> indeterminate for that variation.
    res = full_grid_results()
    res["variations"][0]["evidence_missing"] = True
    report = evaluate(res)
    check("evidence_missing variation is indeterminate -> Conditionally Stable",
          report["outcome"] == "Conditionally Stable")

    # Adversarial: missing required metric cannot be supported.
    res = full_grid_results()
    del res["variations"][0]["metrics"]["cost-crossover"]
    report = evaluate(res)
    check("missing required metric -> Conditionally Stable at best",
          report["outcome"] == "Conditionally Stable")

    # Adversarial: escalation booleans without verifiable baseline evidence.
    res = full_grid_results()
    res["baseline"]["evidence"] = ["build/does-not-exist.dat"]
    report = evaluate(res)
    check("unverifiable baseline evidence with strongest_known_required fails closed",
          report["outcome"] == "Not Auditable")

    res = full_grid_results()
    res["baseline"]["matched_inputs"] = False
    report = evaluate(res)
    check("unmatched baseline inputs with strongest_known_required fail closed",
          report["outcome"] == "Not Auditable")

    # Adversarial: honored=true is not trusted when evidence is unverifiable
    # (already covered above); trigger fired + honored=false is Not Auditable
    # under the mandatory policy.
    res = full_grid_results()
    res["escalation"]["honored"] = False
    report = evaluate(res)
    check("unhonored mandatory escalation is Not Auditable end-to-end",
          report["outcome"] == "Not Auditable")

    # Missing baseline block entirely -> results schema rejection.
    res = full_grid_results()
    del res["baseline"]
    report = evaluate(res)
    check("results without baseline block fail closed",
          report["outcome"] == "Not Auditable")

    # --- Schema: extended prospective variation dimensions ------------------
    validator = jsonschema.Draft202012Validator(schema)
    for dim in ["architecture_variant", "encoding", "memory_qubits", "task",
                "depth", "parameter_sharing", "uncomputation", "noise_rate",
                "sequence_length"]:
        extended = copy.deepcopy(doc)
        extended["allowed_variations"]["dimensions"].append(
            {"name": dim, "values": ["a", "b"]})
        check(f"schema accepts prospective dimension {dim}",
              not list(validator.iter_errors(extended)))
    still_bad = copy.deepcopy(doc)
    still_bad["allowed_variations"]["dimensions"].append(
        {"name": "totally_unknown_dim", "values": [1]})
    check("schema still rejects unknown dimension names",
          bool(list(validator.iter_errors(still_bad))))
    check("existing TFIM contract remains valid under extended schema",
          not ec.validate_contract(example, schema))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) failed: {', '.join(FAILURES)}")
        return 1
    print("All evidence-contract tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
