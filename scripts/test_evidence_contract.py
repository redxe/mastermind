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

    # --- Contract semantic guards -------------------------------------------
    broken = copy.deepcopy(doc)
    broken["metrics"].append(copy.deepcopy(broken["metrics"][0]))
    check("duplicate metric names rejected",
          any("duplicate metric" in p for p in ec.semantic_contract_checks(broken)))
    broken = copy.deepcopy(doc)
    broken["allowed_variations"]["dimensions"].append(
        copy.deepcopy(broken["allowed_variations"]["dimensions"][0]))
    check("duplicate dimension names rejected",
          any("duplicate dimension" in p for p in ec.semantic_contract_checks(broken)))
    broken = copy.deepcopy(doc)
    broken["allowed_variations"]["dimensions"][1]["values"] = [1234, 1234]
    check("duplicate allowed values rejected",
          any("duplicate allowed values" in p for p in ec.semantic_contract_checks(broken)))
    broken = copy.deepcopy(doc)
    broken["allowed_variations"]["dimensions"][1]["values"] = [[1, 2], 5678]
    check("non-scalar allowed values rejected",
          any("non-scalar" in p for p in ec.semantic_contract_checks(broken)))
    broken = copy.deepcopy(doc)
    broken["baseline_policy"]["escalation_rules"][1]["id"] = \
        broken["baseline_policy"]["escalation_rules"][0]["id"]
    check("duplicate escalation rule ids rejected",
          any("duplicate escalation rule id" in p
              for p in ec.semantic_contract_checks(broken)))
    broken = copy.deepcopy(doc)
    broken["decision_rules"]["confidence_model"]["multiple_comparisons"] = "holm"
    check("unimplemented correction method (holm) rejected by schema",
          bool(list(jsonschema.Draft202012Validator(schema).iter_errors(broken))))
    broken = copy.deepcopy(doc)
    broken["metrics"][0]["role"] = "support-only"
    broken["metrics"][0]["reversal"] = {"operator": "le", "bound": -1.0}
    check("reversal block on a support-only metric rejected by schema",
          bool(list(jsonschema.Draft202012Validator(schema).iter_errors(broken))))
    broken = copy.deepcopy(doc)
    del broken["metrics"][1]["reversal"]
    check("reversal-capable metric without reversal block rejected by schema",
          bool(list(jsonschema.Draft202012Validator(schema).iter_errors(broken))))

    # --- Results schema and the sealed evaluation engine ---------------------
    results_schema = ec.load_results_schema()
    jsonschema.Draft202012Validator.check_schema(results_schema)
    check("results schema is a valid Draft 2020-12 schema", True)

    build_dir = REPO / "build"
    build_dir.mkdir(exist_ok=True)
    art_path = "examples/tfim-evidence-contract.yaml"
    art_sha = ec.sha256_file(REPO / art_path)
    baseline_art = "scripts/evidence_contract.py"
    baseline_sha = ec.sha256_file(REPO / baseline_art)

    def budget(*ests: float) -> dict:
        import math as _m
        return {"components": {name: {"estimate": e}
                               for name, e in zip(["shot-noise", "baseline"], ests)},
                "aggregation": "rss",
                "total": _m.sqrt(sum(e * e for e in ests))}

    def passing_metrics() -> dict:
        return {
            "energy-accuracy": {"value": 0.5, "uncertainty_budget": budget(0.8, 0.6)},
            "cost-crossover": {"value": 0.01, "uncertainty_budget": budget(0.003, 0.004)},
        }

    def full_grid_results(contract_doc: dict | None = None, **overrides) -> dict:
        cdoc = contract_doc or doc
        names, grid = ec.expected_variation_grid(cdoc)
        variations = []
        for i, combo in enumerate(sorted(grid, key=repr)):
            variations.append({
                "id": f"var-{i}",
                "dimensions": dict(zip(names, combo)),
                "metrics": passing_metrics(),
                "artifacts": [{"path": art_path, "sha256": art_sha}],
            })
        res = {
            "contract_id": cdoc["contract_id"],
            "variations": variations,
            "baseline": {
                "baseline_id": "free-fermion-svd",
                "identity": "free-fermion-svd (scripts/scale_sweep.py)",
                "artifacts": [{"path": baseline_art, "sha256": baseline_sha}],
                "citations": ["doi:10.1016/0003-4916(70)90270-8"],
                "matched_inputs": True,
            },
            "escalation": {"rule_id": "integrable-exact", "trigger_fired": True,
                           "honored": True,
                           "trigger_evidence": ["TFIM is integrable (Pfeuty 1970)"]},
        }
        res.update(overrides)
        return res

    import contextlib
    import io

    def evaluate(res: dict | None, contract_rel: str = "examples/tfim-evidence-contract.yaml",
                 raw: str | None = None) -> dict:
        rpath = build_dir / "test-results.json"
        rpath.write_text(raw if raw is not None else json.dumps(res),
                         encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ec.main(["evaluate", contract_rel, "--results", str(rpath)])
        rpath.unlink()
        report = json.loads(buf.getvalue())
        report["_rc"] = rc
        return report

    orig_seal_path = ec.SEAL_PATH
    orig_manifest_path = ec.MANIFEST_PATH
    temp_seal = build_dir / "test-seal.json"
    temp_manifest = build_dir / "test-manifest.yaml"
    temp_contract = build_dir / "test-variant-contract.yaml"

    def install_seal() -> None:
        files, placeholders = ec._sealed_files()
        seal = ec.build_seal(files, placeholders)
        temp_seal.write_text(json.dumps(seal), encoding="utf-8")
        ec.SEAL_PATH = temp_seal

    def install_variant(vdoc: dict) -> str:
        rel = "build/test-variant-contract.yaml"
        temp_contract.write_text(yaml.safe_dump(vdoc), encoding="utf-8")
        temp_manifest.write_text(yaml.safe_dump(
            {"claims": {vdoc["corpus"]["claim_key"]:
                        {"contract": rel, "status": "drafted"}}}), encoding="utf-8")
        ec.MANIFEST_PATH = temp_manifest
        install_seal()
        return rel

    try:
        # Seal binding: refuse to evaluate without a seal.
        ec.SEAL_PATH = build_dir / "no-such-seal.json"
        report = evaluate(full_grid_results())
        check("evaluation refuses to run without a protocol seal",
              report["_rc"] == 2 and report["evaluation_status"] == "invalid"
              and any("seal" in r for r in report["invalid_reasons"]))

        # Install a temporary seal over the real sealed set (unit-test seal
        # only; the repository's real protocol seal is never created here).
        install_seal()
        loaded_seal = json.loads(temp_seal.read_text(encoding="utf-8"))
        check("temp seal records the engine version",
              loaded_seal["engine_version"] == ec.ENGINE_VERSION)
        check("sealed set includes results schema, engine, and requirements",
              {ec.RESULTS_SCHEMA_PATH, ec.ENGINE_PATH, ec.REQUIREMENTS_PATH}
              <= set(ec._sealed_files()[0]))
        wrong_engine = copy.deepcopy(loaded_seal)
        wrong_engine["engine_version"] = "0.0.1"
        wrong_engine["seal_hash"] = ec.compute_seal_hash(wrong_engine)
        check("seal with mismatched engine version rejected",
              any("engine_version" in p for p in ec.verify_seal_data(wrong_engine)))

        report = evaluate(full_grid_results())
        check("full passing grid with verified escalation -> Stable (exit 0)",
              report["outcome"] == "Stable" and report["_rc"] == 0
              and report["evaluation_status"] == "valid", str(report)[:300])
        check("report includes Bonferroni family accounting",
              report["multiple_comparisons"]["method"] == "bonferroni"
              and report["multiple_comparisons"]["family_size"] == 24)
        check("baseline citation labeled citation-present, never verified-by-citation",
              report["baseline"]["citation_status"] == "citation-present"
              and report["baseline"]["artifacts_verified"] is True)

        # Seal binding: absolute and traversal contract paths are refused.
        report = evaluate(full_grid_results(),
                          contract_rel=str(REPO / "examples" / "tfim-evidence-contract.yaml"))
        check("absolute contract path refused", report["_rc"] == 2)
        report = evaluate(full_grid_results(),
                          contract_rel="examples/../examples/tfim-evidence-contract.yaml")
        check("traversal contract path refused", report["_rc"] == 2)
        report = evaluate(full_grid_results(),
                          contract_rel="specs/evidence-contract.schema.json")
        check("contract not referenced by the manifest refused", report["_rc"] == 2)

        # Seal binding: contract modified after sealing is refused.
        vdoc = copy.deepcopy(doc)
        rel = install_variant(vdoc)
        temp_contract.write_text(temp_contract.read_text(encoding="utf-8")
                                 + "\n# tampered\n", encoding="utf-8")
        report = evaluate(full_grid_results(vdoc), contract_rel=rel)
        check("contract modified after sealing refused",
              report["_rc"] == 2
              and any("modified after sealing" in r or "hash mismatch" in r
                      for r in report["invalid_reasons"]), str(report)[:300])

        # Restore the standard sealed env for the remaining tests.
        ec.MANIFEST_PATH = orig_manifest_path
        install_seal()

        # Structural: caller-supplied verdicts rejected, exit 2.
        res = full_grid_results()
        res["variations"][0]["verdict"] = "supported"
        report = evaluate(res)
        check("caller-supplied verdict is a structural error (exit 2)",
              report["_rc"] == 2 and report["evaluation_status"] == "invalid")

        # Scientific: incomplete grid -> Not Auditable, exit 0.
        res = full_grid_results()
        res["variations"] = res["variations"][:1]
        report = evaluate(res)
        check("single favorable variation -> Not Auditable (exit 0)",
              report["outcome"] == "Not Auditable" and report["_rc"] == 0
              and report["evaluation_status"] == "valid")

        # Structural grid violations, exit 2.
        res = full_grid_results()
        res["variations"][1]["dimensions"] = dict(res["variations"][0]["dimensions"])
        check("duplicate variation combination exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][1]["id"] = res["variations"][0]["id"]
        check("duplicate variation ids exit 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["dimensions"]["favorable_knob"] = 1
        check("unknown dimension exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["dimensions"]["transpiler_seed"] = 99999
        check("undeclared dimension value exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["dimensions"]["transpiler_seed"] = [1234]
        check("non-scalar dimension value exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results(contract_id="some-other-claim")
        check("contract_id mismatch exits 2", evaluate(res)["_rc"] == 2)

        # Finite, domain-valid numbers.
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"]["value"] = float("nan")
        check("NaN metric value exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"]["value"] = float("inf")
        check("Infinity metric value exits 2", evaluate(res)["_rc"] == 2)
        raw = json.dumps(full_grid_results()).replace('"value": 0.5', '"value": 1e999', 1)
        check("overflowing literal (1e999) exits 2", evaluate(None, raw=raw)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"]["value"] = -0.5
        report = evaluate(res)
        check("negative value for nonnegative-domain metric exits 2",
              report["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"][
            "uncertainty_budget"]["components"]["shot-noise"]["estimate"] = -0.1
        check("negative uncertainty component exits 2", evaluate(res)["_rc"] == 2)

        # Quantitative uncertainty budgets.
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"][
            "uncertainty_budget"]["total"] = 5.0
        check("budget total inconsistent with components exits 2",
              evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"]["uncertainty_budget"] = {
            "components": {"shot-noise": {"estimate": 1.0}},
            "aggregation": "rss", "total": 1.0}
        report = evaluate(res)
        check("missing mandatory source component -> Conditionally Stable (exit 0)",
              report["outcome"] == "Conditionally Stable" and report["_rc"] == 0)
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"] = {
            "value": 0.5, "uncertainty_sources": ["shot-noise", "baseline"]}
        check("name-list-only uncertainty (no budget) exits 2",
              evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["metrics"]["energy-accuracy"]["uncertainty_budget"] = {
            "components": {"shot-noise": {"estimate": 1.0},
                           "baseline": {"exact": True,
                                        "justification": "exact free-fermion energy, deterministic"}},
            "aggregation": "rss", "total": 1.0}
        report = evaluate(res)
        check("exact/deterministic component with justification accepted",
              report["outcome"] == "Stable" and report["_rc"] == 0)

        # Typed decision semantics: a support-only failure can NEVER reverse.
        res = full_grid_results()
        for var in res["variations"]:
            var["metrics"]["energy-accuracy"]["value"] = 50.0
        report = evaluate(res)
        check("support-only failure everywhere is never Reversed",
              report["outcome"] == "Not Auditable" and report["_rc"] == 0
              and all(v["verdict"] != "reversed"
                      for v in report["verdicts"].values()), str(report)[:300])

        # Only a confidently opposite cost-crossover margin reverses.
        res = full_grid_results()
        res["variations"][0]["metrics"]["cost-crossover"]["value"] = -2.55
        report = evaluate(res)
        check("confident negative crossover margin -> reversed -> Unresolved",
              report["outcome"] == "Unresolved" and report["_rc"] == 0)
        res = full_grid_results()
        res["variations"][0]["metrics"]["cost-crossover"]["value"] = -0.051
        report = evaluate(res)
        check("marginally negative crossover (not confident) is indeterminate",
              report["outcome"] == "Conditionally Stable" and report["_rc"] == 0)

        # Bonferroni changes a boundary verdict: same evidence, corrected vs raw.
        boundary = full_grid_results()
        for var in boundary["variations"]:
            var["metrics"]["cost-crossover"] = {"value": -2.05,
                                                "uncertainty_budget": budget(0.8, 0.6)}
        report_bonf = evaluate(boundary)
        vdoc = copy.deepcopy(doc)
        vdoc["decision_rules"]["confidence_model"]["multiple_comparisons"] = "none"
        rel = install_variant(vdoc)
        report_none = evaluate(full_grid_results(vdoc, variations=boundary["variations"]),
                               contract_rel=rel)
        ec.MANIFEST_PATH = orig_manifest_path
        install_seal()
        check("uncorrected alpha reverses the boundary case",
              report_none["outcome"] == "Reversed" and report_none["_rc"] == 0,
              str(report_none)[:200])
        check("Bonferroni correction changes the boundary verdict",
              report_bonf["outcome"] == "Not Auditable" and report_bonf["_rc"] == 0
              and all(v["verdict"] != "reversed"
                      for v in report_bonf["verdicts"].values()), str(report_bonf)[:200])

        # Per-variation artifact accounting.
        res = full_grid_results()
        res["variations"][0]["artifacts"] = [{"path": "build/does-not-exist.dat",
                                              "sha256": "0" * 64}]
        report = evaluate(res)
        check("missing variation artifact under not-auditable voids the audit (exit 0)",
              report["outcome"] == "Not Auditable" and report["_rc"] == 0)
        res = full_grid_results()
        res["variations"][0]["artifacts"] = [{"path": art_path, "sha256": "0" * 64}]
        report = evaluate(res)
        check("artifact digest mismatch under not-auditable voids the audit (exit 0)",
              report["outcome"] == "Not Auditable" and report["_rc"] == 0)
        res = full_grid_results()
        res["variations"][0]["artifacts"] = [{"path": str(REPO / art_path),
                                              "sha256": art_sha}]
        check("absolute artifact path exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["artifacts"] = [{"path": "../outside.dat",
                                              "sha256": "0" * 64}]
        check("traversal artifact path exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["variations"][0]["artifacts"] = [{"path": "scripts", "sha256": "0" * 64}]
        check("directory artifact exits 2", evaluate(res)["_rc"] == 2)

        # indeterminate-variation policy: only the affected variation degrades.
        vdoc = copy.deepcopy(doc)
        vdoc["missing_evidence_policy"]["on_missing"] = "indeterminate-variation"
        rel = install_variant(vdoc)
        res = full_grid_results(vdoc)
        res["variations"][0]["artifacts"] = [{"path": "build/does-not-exist.dat",
                                              "sha256": "0" * 64}]
        report = evaluate(res, contract_rel=rel)
        ec.MANIFEST_PATH = orig_manifest_path
        install_seal()
        check("missing artifact under indeterminate-variation degrades only that "
              "variation (Conditionally Stable, exit 0)",
              report["outcome"] == "Conditionally Stable" and report["_rc"] == 0
              and report["verdicts"]["var-0"]["verdict"] == "indeterminate",
              str(report)[:300])

        # evidence_missing / missing metric behave as indeterminate.
        res = full_grid_results()
        res["variations"][0]["evidence_missing"] = True
        report = evaluate(res)
        check("evidence_missing variation -> Conditionally Stable",
              report["outcome"] == "Conditionally Stable" and report["_rc"] == 0)
        res = full_grid_results()
        del res["variations"][0]["metrics"]["cost-crossover"]
        report = evaluate(res)
        check("missing required metric -> Conditionally Stable at best",
              report["outcome"] == "Conditionally Stable" and report["_rc"] == 0)

        # Honest baseline enforcement.
        res = full_grid_results()
        res["baseline"]["baseline_id"] = "my-favorite-baseline"
        check("undeclared baseline_id exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["baseline"]["artifacts"] = [{"path": baseline_art, "sha256": "0" * 64}]
        check("baseline artifact digest mismatch is a provenance failure (exit 2)",
              evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["baseline"]["artifacts"] = []
        report = evaluate(res)
        check("citation-only baseline cannot prove an honored escalation (exit 2)",
              report["_rc"] == 2
              and any("citations alone" in r for r in report["invalid_reasons"]))
        res = full_grid_results()
        res["baseline"]["matched_inputs"] = False
        check("unmatched baseline inputs exit 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["escalation"]["rule_id"] = "no-such-rule"
        check("unknown escalation rule_id exits 2", evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["baseline"]["baseline_id"] = "dense-eigh"
        check("honored escalation with the wrong baseline_id exits 2",
              evaluate(res)["_rc"] == 2)
        res = full_grid_results()
        res["escalation"]["honored"] = False
        report = evaluate(res)
        check("honestly-declared unhonored mandatory escalation -> Not Auditable (exit 0)",
              report["outcome"] == "Not Auditable" and report["_rc"] == 0
              and report["evaluation_status"] == "valid")
        report = evaluate(full_grid_results())
        check("trigger criteria are echoed as locked text, not executed",
              isinstance(report["baseline"]["trigger_criteria_locked"], str)
              and report["baseline"]["trigger_evidence_recorded"])

        # Missing baseline block entirely -> structural.
        res = full_grid_results()
        del res["baseline"]
        check("results without baseline block exit 2", evaluate(res)["_rc"] == 2)
    finally:
        ec.SEAL_PATH = orig_seal_path
        ec.MANIFEST_PATH = orig_manifest_path
        for f in (temp_seal, temp_manifest, temp_contract):
            if f.exists():
                f.unlink()


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
