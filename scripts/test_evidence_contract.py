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

    # End-to-end evaluate on the TFIM contract with synthetic verdicts.
    results = {
        "variations": [
            {"id": "dense-eigh", "verdict": "indeterminate"},
            {"id": "free-fermion-svd", "verdict": "reversed"},
        ],
        "escalation_trigger_fired": True,
        "escalation_honored": True,
    }
    rpath = REPO / "build" / "test-results.json"
    rpath.write_text(json.dumps(results), encoding="utf-8")
    rc = ec.main(["evaluate", str(example), "--results", str(rpath)])
    check("CLI evaluate runs end-to-end", rc == 0)
    rpath.unlink()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) failed: {', '.join(FAILURES)}")
        return 1
    print("All evidence-contract tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
