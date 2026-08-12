#!/usr/bin/env python
"""Evidence-contract CLI: validate, seal, verify, and evaluate claim-support contracts.

Subcommands
-----------
validate <contract.yaml> [...]      Validate contracts against the JSON schema.
seal-protocol [--force-placeholders]
                                    Hash-lock the protocol, schema, corpus manifest,
                                    and every referenced contract into
                                    specs/protocol-seal.json. Refuses to overwrite an
                                    existing seal and refuses placeholder claims
                                    unless --force-placeholders (pilot only).
verify-seal                         Recompute the seal hash and every file hash,
                                    and check sealed-set coverage against the
                                    corpus manifest. Rejects modified metadata,
                                    added/deleted entries, malformed seals, and
                                    changed referenced files.
evaluate <contract.yaml> --results <results.json>
                                    Validate the results document against
                                    specs/evidence-results.schema.json, DERIVE
                                    per-variation verdicts from recorded metrics
                                    (caller-supplied verdicts are never accepted),
                                    enforce the complete declared variation grid,
                                    verify baseline-escalation evidence, and print
                                    the outcome: Stable, Conditionally Stable,
                                    Unresolved, Reversed, or Not Auditable.
                                    Structural violations fail closed as
                                    Not Auditable.

The seal must be committed BEFORE any outcome-bearing evaluation (see
docs/research/locked-audit-protocol.md).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "specs" / "evidence-contract.schema.json"
RESULTS_SCHEMA_PATH = REPO / "specs" / "evidence-results.schema.json"
PROTOCOL_PATH = REPO / "docs" / "research" / "locked-audit-protocol.md"
MANIFEST_PATH = REPO / "docs" / "research" / "claim-corpus-manifest.yaml"
SEAL_PATH = REPO / "specs" / "protocol-seal.json"

OUTCOMES = ["Stable", "Conditionally Stable", "Unresolved", "Reversed", "Not Auditable"]
VERDICTS = {"supported", "reversed", "indeterminate"}
CITATION_PREFIXES = ("doi:", "arXiv:", "arxiv:", "citation:")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_results_schema() -> dict:
    return json.loads(RESULTS_SCHEMA_PATH.read_text(encoding="utf-8"))


def load_contract(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_contract(path: Path, schema: dict) -> list[str]:
    """Return a list of error strings (empty when valid)."""
    try:
        doc = load_contract(path)
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def cmd_validate(args: argparse.Namespace) -> int:
    schema = load_schema()
    failed = False
    for name in args.contracts:
        path = Path(name)
        errors = validate_contract(path, schema)
        if errors:
            failed = True
            print(f"[FAIL] {path}")
            for err in errors:
                print(f"       {err}")
        else:
            print(f"[OK ] {path}")
    return 1 if failed else 0


def _sealed_files() -> tuple[list[Path], list[str]]:
    """Return (files to hash, placeholder claim keys)."""
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = [SCHEMA_PATH, PROTOCOL_PATH, MANIFEST_PATH]
    placeholders: list[str] = []
    for key, claim in manifest.get("claims", {}).items():
        if claim.get("status") == "placeholder" or not claim.get("contract"):
            placeholders.append(key)
            continue
        files.append(REPO / claim["contract"])
    return files, placeholders


def compute_seal_hash(seal: dict) -> str:
    """Canonical hash of a seal document with its own seal_hash removed."""
    body = {k: v for k, v in seal.items() if k != "seal_hash"}
    return hashlib.sha256(
        json.dumps(body, indent=2, sort_keys=True).encode("utf-8")).hexdigest()


def build_seal(files: list[Path], placeholders: list[str]) -> dict:
    entries = {str(p.relative_to(REPO)).replace("\\", "/"): sha256_file(p) for p in files}
    seal = {
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "placeholders_forced": bool(placeholders),
        "placeholder_claims": placeholders,
        "files": entries,
        "seal_note": "Outcome-bearing evaluation is permitted only after this file "
                     "is committed. Any change to a sealed file invalidates results "
                     "obtained under this seal.",
    }
    seal["seal_hash"] = compute_seal_hash(seal)
    return seal


def cmd_seal_protocol(args: argparse.Namespace) -> int:
    if SEAL_PATH.exists():
        print(f"error: seal already exists at {SEAL_PATH}; amendments require a new "
              "protocol version (see protocol \u00a77)", file=sys.stderr)
        return 1
    files, placeholders = _sealed_files()
    if placeholders and not args.force_placeholders:
        print("error: corpus contains placeholder claims: " + ", ".join(placeholders),
              file=sys.stderr)
        print("       fill them in before sealing, or pass --force-placeholders "
              "(pilot only)", file=sys.stderr)
        return 1
    schema = load_schema()
    for path in files:
        if path.suffix in (".yaml", ".yml") and path != MANIFEST_PATH:
            errors = validate_contract(path, schema)
            if errors:
                print(f"error: {path} fails schema validation; refusing to seal",
                      file=sys.stderr)
                for err in errors:
                    print(f"       {err}", file=sys.stderr)
                return 1
    seal = build_seal(files, placeholders)
    SEAL_PATH.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8", newline="\n")
    print(f"sealed {len(seal['files'])} files -> {SEAL_PATH}")
    print(f"seal hash: {seal['seal_hash']}")
    return 0


def verify_seal_data(seal: object) -> list[str]:
    """Return a list of problems (empty when the seal is intact).

    Checks, in order:
    1. Structure: the seal is a JSON object with a `files` mapping and a
       `seal_hash` string. Malformed seals are rejected.
    2. Integrity: `seal_hash` is recomputed over the canonical serialization of
       the seal with `seal_hash` removed. Any edit to seal metadata, or any
       added/deleted/modified file entry, changes the recomputed hash.
    3. Referenced files: every sealed file must exist and hash to its recorded
       value.
    4. Coverage: the sealed file set must equal the set currently required by
       the corpus manifest (schema, protocol, manifest, and every non-placeholder
       contract). Entries added to or dropped from either side are rejected.
    """
    problems: list[str] = []
    if not isinstance(seal, dict):
        return ["malformed seal: not a JSON object"]
    files = seal.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("malformed seal: missing or empty 'files' mapping")
    recorded = seal.get("seal_hash")
    if not isinstance(recorded, str) or len(recorded) != 64:
        problems.append("malformed seal: missing or malformed 'seal_hash'")
    if problems:
        return problems
    recomputed = compute_seal_hash(seal)
    if recomputed != recorded:
        problems.append(
            f"seal_hash mismatch: recorded {recorded[:12]}..., "
            f"recomputed {recomputed[:12]}... (seal metadata or file entries "
            "were modified after sealing)")
    for rel, expected in files.items():
        if not isinstance(rel, str) or not isinstance(expected, str):
            problems.append(f"malformed seal entry: {rel!r}")
            continue
        path = REPO / rel
        if not path.exists():
            problems.append(f"{rel}: sealed file missing")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{rel}: hash mismatch (sealed {expected[:12]}..., "
                            f"actual {actual[:12]}...)")
    try:
        expected_files, _ = _sealed_files()
        expected_set = {str(p.relative_to(REPO)).replace("\\", "/")
                        for p in expected_files}
        sealed_set = set(files)
        for extra in sorted(sealed_set - expected_set):
            problems.append(f"{extra}: sealed entry no longer required by the manifest")
        for missing in sorted(expected_set - sealed_set):
            problems.append(f"{missing}: required by the manifest but absent from the seal")
    except Exception as exc:  # manifest unreadable -> fail closed
        problems.append(f"could not derive the required sealed file set: {exc}")
    return problems


def cmd_verify_seal(_args: argparse.Namespace) -> int:
    if not SEAL_PATH.exists():
        print("error: no seal found; run seal-protocol first", file=sys.stderr)
        return 1
    try:
        seal = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"SEAL BROKEN: malformed seal JSON: {exc}", file=sys.stderr)
        return 1
    problems = verify_seal_data(seal)
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        print("SEAL BROKEN: see failures above.", file=sys.stderr)
        return 1
    for rel in sorted(seal["files"]):
        print(f"[OK ] {rel}")
    print("Seal intact (metadata hash, file hashes, and coverage all verified).")
    return 0


def aggregate_standard_v1(verdicts: list[str], *, artifacts_ok: bool,
                          escalation_unhonored: bool,
                          strongest_known_required: bool = False) -> str:
    """Map per-variation verdicts to a final outcome (protocol §5).

    Baseline-escalation consequences are two distinct conditions:
    - strongest_known_required=True and an unhonored trigger -> Not Auditable
      (the strongest known baseline is mandatory for auditability).
    - strongest_known_required=False and an unhonored trigger -> outcome capped
      at Conditionally Stable (stronger baseline recommended, not mandatory).
    """
    if not artifacts_ok:
        return "Not Auditable"
    if escalation_unhonored and strongest_known_required:
        return "Not Auditable"
    supported = verdicts.count("supported")
    reversed_ = verdicts.count("reversed")
    if supported and not reversed_:
        outcome = "Stable" if supported == len(verdicts) else "Conditionally Stable"
    elif supported and reversed_:
        outcome = "Unresolved"
    elif reversed_:
        outcome = "Reversed"
    else:
        outcome = "Not Auditable"
    if escalation_unhonored and outcome == "Stable":
        outcome = "Conditionally Stable"
    return outcome


def validate_results(results: object) -> list[str]:
    """Validate a results document against the results schema."""
    schema = load_results_schema()
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(results),
                          key=lambda e: list(e.absolute_path))
    ]


def _metric_threshold(spec: dict, recorded: dict) -> tuple[float | None, str | None]:
    """Return (pass threshold for recorded['value'], problem)."""
    tol = spec["tolerance"]
    kind = tol["kind"]
    if kind == "absolute":
        return float(tol["value"]), None
    if kind == "relative":
        ref = recorded.get("reference")
        if ref is None or ref == 0:
            return None, "relative tolerance requires a nonzero 'reference'"
        return float(tol["value"]) * abs(float(ref)), None
    if kind == "standard-errors":
        unc = recorded.get("uncertainty")
        if unc is None or unc <= 0:
            return None, "standard-errors tolerance requires positive 'uncertainty'"
        return float(tol["value"]) * float(unc), None
    return None, f"unknown tolerance kind {kind!r}"


def derive_verdict(contract: dict, variation: dict, z: float) -> tuple[str, list[str]]:
    """Derive supported | reversed | indeterminate from recorded metrics.

    Caller-supplied verdicts are never accepted. Rules:
    - Every contract metric with required_for_support=true must be recorded,
      pass its tolerance, and cover all mandatory uncertainty sources.
    - A required metric failing its tolerance by more than z standard errors
      (at the contract's alpha) is a confident reversal.
    - Anything short of full support without a confident reversal is
      indeterminate (fail closed).
    """
    reasons: list[str] = []
    if variation.get("evidence_missing"):
        return "indeterminate", ["evidence missing for this variation"]
    metrics_spec = {m["name"]: m for m in contract["metrics"]}
    recorded = variation["metrics"]
    unknown = set(recorded) - set(metrics_spec)
    if unknown:
        return "indeterminate", [f"unknown metric(s) recorded: {sorted(unknown)}"]
    required_sources = set(
        contract["decision_rules"]["confidence_model"].get("uncertainty_sources", []))
    any_indeterminate = False
    any_reversed = False
    for name, spec in metrics_spec.items():
        if not spec.get("required_for_support", True):
            continue
        rec = recorded.get(name)
        if rec is None:
            any_indeterminate = True
            reasons.append(f"{name}: required metric not recorded")
            continue
        covered = set(rec.get("uncertainty_sources", []))
        if required_sources and not required_sources <= covered:
            any_indeterminate = True
            reasons.append(f"{name}: mandatory uncertainty sources not covered: "
                           f"{sorted(required_sources - covered)}")
            continue
        threshold, problem = _metric_threshold(spec, rec)
        if problem:
            any_indeterminate = True
            reasons.append(f"{name}: {problem}")
            continue
        value = float(rec["value"])
        if value <= threshold:
            continue
        unc = rec.get("uncertainty")
        if unc is not None and unc > 0 and (value - z * float(unc)) > threshold:
            any_reversed = True
            reasons.append(f"{name}: fails tolerance with confident reversal "
                           f"(value {value}, threshold {threshold}, z={z:.3f})")
        else:
            any_indeterminate = True
            reasons.append(f"{name}: fails tolerance without confident reversal")
    if any_reversed:
        return "reversed", reasons
    if any_indeterminate:
        return "indeterminate", reasons
    return "supported", reasons


def expected_variation_grid(contract: dict) -> tuple[list[str], set[tuple]]:
    """Return (dimension names, set of allowed value combinations)."""
    dims = contract["allowed_variations"]["dimensions"]
    names = [d["name"] for d in dims]
    grid = set(itertools.product(*(tuple(d["values"]) for d in dims)))
    return names, grid


def check_variation_grid(contract: dict, variations: list[dict]) -> tuple[dict, list[str], list[str]]:
    """Enforce the complete declared variation grid.

    Returns (combo -> variation, fatal problems, missing combo labels).
    Fatal problems: unknown dimensions, undeclared values, incomplete dimension
    sets, and duplicate combinations. Missing combos are returned separately so
    the missing-evidence policy can decide their consequence.
    """
    names, grid = expected_variation_grid(contract)
    seen: dict[tuple, dict] = {}
    problems: list[str] = []
    dim_values = {d["name"]: set(d["values"])
                  for d in contract["allowed_variations"]["dimensions"]}
    for var in variations:
        dims = var["dimensions"]
        unknown = set(dims) - set(names)
        if unknown:
            problems.append(f"variation {var['id']!r}: unknown dimension(s) {sorted(unknown)}")
            continue
        missing_dims = set(names) - set(dims)
        if missing_dims:
            problems.append(f"variation {var['id']!r}: missing dimension(s) {sorted(missing_dims)}")
            continue
        bad_values = [f"{k}={dims[k]!r}" for k in names if dims[k] not in dim_values[k]]
        if bad_values:
            problems.append(f"variation {var['id']!r}: undeclared value(s) {bad_values}")
            continue
        combo = tuple(dims[k] for k in names)
        if combo in seen:
            problems.append(f"variation {var['id']!r}: duplicate of combination {combo}")
            continue
        seen[combo] = var
    missing = [", ".join(f"{n}={v}" for n, v in zip(names, combo))
               for combo in sorted(grid - set(seen), key=repr)]
    return seen, problems, missing


def verify_baseline_evidence(results: dict) -> tuple[bool, list[str]]:
    """Verify explicit baseline identity, evidence, and matched inputs.

    Every evidence entry must be an existing repo-relative path or a citation
    prefixed doi:/arXiv:/citation:. Anything unverifiable fails closed.
    """
    problems: list[str] = []
    baseline = results["baseline"]
    if not baseline["identity"].strip():
        problems.append("baseline identity is empty")
    if baseline["matched_inputs"] is not True:
        problems.append("baseline inputs were not matched to the quantum side")
    for entry in baseline["evidence"]:
        if entry.startswith(CITATION_PREFIXES):
            continue
        if (REPO / entry).exists():
            continue
        problems.append(f"baseline evidence unverifiable: {entry!r} is neither an "
                        "existing repo path nor a doi:/arXiv:/citation: reference")
    return not problems, problems


def cmd_evaluate(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    schema = load_schema()
    errors = validate_contract(contract_path, schema)
    if errors:
        print(f"error: contract fails schema validation: {errors[0]}", file=sys.stderr)
        return 1
    contract = load_contract(contract_path)

    def fail_closed(reasons: list[str]) -> int:
        report = {
            "contract_id": contract["contract_id"],
            "outcome": "Not Auditable",
            "fail_closed_reasons": reasons,
        }
        print(json.dumps(report, indent=2))
        return 0

    try:
        results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail_closed([f"results unreadable: {exc}"])

    schema_errors = validate_results(results)
    if schema_errors:
        return fail_closed(["results fail the results schema (caller-supplied "
                            "verdicts are not accepted)"] + schema_errors[:5])
    if results["contract_id"] != contract["contract_id"]:
        return fail_closed([f"results contract_id {results['contract_id']!r} does not "
                            f"match contract {contract['contract_id']!r}"])

    policy = contract["missing_evidence_policy"]
    missing_artifacts = [a for a in policy["required_artifacts"]
                         if not (REPO / a).exists()]
    artifacts_ok = not (missing_artifacts and policy["on_missing"] == "not-auditable")

    # Enforce the complete declared variation grid.
    by_combo, grid_problems, missing_combos = check_variation_grid(
        contract, results["variations"])
    if grid_problems:
        return fail_closed(grid_problems)
    if missing_combos and policy["on_missing"] == "not-auditable":
        return fail_closed([f"missing variation: {m}" for m in missing_combos])

    # Derive per-variation verdicts from recorded metrics; never trust callers.
    alpha = contract["decision_rules"]["confidence_model"]["alpha"]
    z = NormalDist().inv_cdf(1 - alpha / 2)
    verdicts: list[str] = []
    verdict_report: dict[str, dict] = {}
    for combo, var in by_combo.items():
        verdict, reasons = derive_verdict(contract, var, z)
        verdicts.append(verdict)
        verdict_report[var["id"]] = {"verdict": verdict, "reasons": reasons}
    # Missing combos under indeterminate-variation policy count as indeterminate.
    for m in missing_combos:
        verdicts.append("indeterminate")
        verdict_report[f"<missing: {m}>"] = {
            "verdict": "indeterminate", "reasons": ["variation not evaluated"]}

    # Baseline escalation: booleans alone are never sufficient.
    baseline_ok, baseline_problems = verify_baseline_evidence(results)
    escalation = results["escalation"]
    honored_verified = bool(escalation["honored"]) and baseline_ok
    escalation_unhonored = bool(escalation["trigger_fired"]) and not honored_verified
    strongest_required = bool(contract["baseline_policy"]["strongest_known_required"])
    if strongest_required and not baseline_ok:
        return fail_closed(["strongest_known_required is true but the baseline "
                            "cannot be verified"] + baseline_problems)

    outcome = aggregate_standard_v1(verdicts, artifacts_ok=artifacts_ok,
                                    escalation_unhonored=escalation_unhonored,
                                    strongest_known_required=strongest_required)

    report = {
        "contract_id": contract["contract_id"],
        "outcome": outcome,
        "verdicts": verdict_report,
        "missing_artifacts": missing_artifacts,
        "missing_variations": missing_combos,
        "baseline_verified": baseline_ok,
        "baseline_problems": baseline_problems,
        "escalation_unhonored": escalation_unhonored,
        "strongest_known_required": strongest_required,
    }
    print(json.dumps(report, indent=2))
    return 0 if outcome in OUTCOMES else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_contract",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate contracts against the schema")
    p_val.add_argument("contracts", nargs="+")
    p_val.set_defaults(func=cmd_validate)

    p_seal = sub.add_parser("seal-protocol", help="hash-lock the protocol and corpus")
    p_seal.add_argument("--force-placeholders", action="store_true",
                        help="allow sealing with placeholder claims (pilot only)")
    p_seal.set_defaults(func=cmd_seal_protocol)

    p_ver = sub.add_parser("verify-seal", help="verify the existing seal")
    p_ver.set_defaults(func=cmd_verify_seal)

    p_eval = sub.add_parser("evaluate", help="evaluate results against a contract")
    p_eval.add_argument("contract")
    p_eval.add_argument("--results", required=True)
    p_eval.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
