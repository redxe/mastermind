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
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import jsonschema
import yaml

ENGINE_VERSION = "2.0.0"

REPO = Path(__file__).resolve().parents[1]
ENGINE_PATH = Path(__file__).resolve()
SCHEMA_PATH = REPO / "specs" / "evidence-contract.schema.json"
RESULTS_SCHEMA_PATH = REPO / "specs" / "evidence-results.schema.json"
REQUIREMENTS_PATH = REPO / "requirements-ci.txt"
PROTOCOL_PATH = REPO / "docs" / "research" / "locked-audit-protocol.md"
MANIFEST_PATH = REPO / "docs" / "research" / "claim-corpus-manifest.yaml"
SEAL_PATH = REPO / "specs" / "protocol-seal.json"

OUTCOMES = ["Stable", "Conditionally Stable", "Unresolved", "Reversed", "Not Auditable"]
VERDICTS = {"supported", "reversed", "indeterminate"}
CITATION_PREFIXES = ("doi:", "arXiv:", "arxiv:", "citation:")
SCALAR_TYPES = (str, int, float, bool)

# CLI exit codes: 0 = structurally valid evaluation (any scientific outcome,
# including Not Auditable); 2 = structurally invalid input (malformed schema,
# grid violation, seal failure, path violation, provenance failure).
EXIT_VALID = 0
EXIT_INVALID = 2


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_results_schema() -> dict:
    return json.loads(RESULTS_SCHEMA_PATH.read_text(encoding="utf-8"))


def load_contract(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def semantic_contract_checks(doc: dict) -> list[str]:
    """Structural guards beyond what JSON Schema can express."""
    problems: list[str] = []
    names = [m["name"] for m in doc.get("metrics", [])]
    for dup in {n for n in names if names.count(n) > 1}:
        problems.append(f"duplicate metric name {dup!r}")
    dims = doc.get("allowed_variations", {}).get("dimensions", [])
    dim_names = [d["name"] for d in dims]
    for dup in {n for n in dim_names if dim_names.count(n) > 1}:
        problems.append(f"duplicate dimension name {dup!r}")
    for d in dims:
        vals = d.get("values", [])
        if any(not isinstance(v, SCALAR_TYPES) for v in vals):
            problems.append(f"dimension {d['name']!r}: non-scalar allowed value")
            continue
        if len(set(vals)) != len(vals):
            problems.append(f"dimension {d['name']!r}: duplicate allowed values")
    rules = doc.get("baseline_policy", {}).get("escalation_rules", [])
    rule_ids = [r.get("id") for r in rules]
    for dup in {r for r in rule_ids if rule_ids.count(r) > 1}:
        problems.append(f"duplicate escalation rule id {dup!r}")
    return problems


def validate_contract(path: Path, schema: dict) -> list[str]:
    """Return a list of error strings (empty when valid)."""
    try:
        doc = load_contract(path)
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]
    if not errors:
        errors = semantic_contract_checks(doc)
    return errors


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
    """Return (files to hash, placeholder claim keys).

    The sealed set covers everything that can influence an evaluation: the
    contract schema, the results schema, the protocol, the corpus manifest,
    the evaluator engine itself, the pinned verification dependencies, and
    every non-placeholder contract.
    """
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = [SCHEMA_PATH, RESULTS_SCHEMA_PATH, PROTOCOL_PATH, MANIFEST_PATH,
             ENGINE_PATH, REQUIREMENTS_PATH]
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
        "engine_version": ENGINE_VERSION,
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
    if seal.get("engine_version") != ENGINE_VERSION:
        problems.append(
            f"seal engine_version {seal.get('engine_version')!r} does not match "
            f"the running engine {ENGINE_VERSION!r}; results sealed under a "
            "different engine cannot be evaluated by this one")
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


def load_json_strict(text: str) -> object:
    """Parse JSON, rejecting NaN and +/-Infinity literals."""
    def _reject(name: str) -> float:
        raise ValueError(f"non-finite JSON constant {name!r} rejected")
    return json.loads(text, parse_constant=_reject)


def find_nonfinite(obj: object, path: str = "$") -> list[str]:
    """Return paths of every non-finite number anywhere in a JSON document."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, float) and not math.isfinite(obj):
        return [f"{path}: non-finite number"]
    problems: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            problems += find_nonfinite(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            problems += find_nonfinite(v, f"{path}[{i}]")
    return problems


def check_repo_path(rel: str) -> tuple[Path | None, str | None]:
    """Validate a repo-relative path (structural check only).

    Rejects absolute paths, traversal components, and paths that resolve
    outside the repository. Existence is checked by the caller.
    """
    p = Path(rel)
    if p.is_absolute():
        return None, f"absolute path rejected: {rel!r}"
    if any(part == ".." for part in p.parts):
        return None, f"path traversal rejected: {rel!r}"
    full = (REPO / p).resolve()
    try:
        full.relative_to(REPO.resolve())
    except ValueError:
        return None, f"path escapes the repository: {rel!r}"
    return full, None


def check_artifact(entry: dict) -> tuple[str | None, str | None]:
    """Verify one {path, sha256} artifact entry.

    Returns (structural_problem, evidence_problem). Path-shape violations and
    directories are structural; a missing file or digest mismatch is an
    evidence problem whose consequence is decided by the missing-evidence
    policy.
    """
    full, problem = check_repo_path(entry["path"])
    if problem:
        return problem, None
    if full.is_dir():
        return f"directory where a regular file is required: {entry['path']!r}", None
    if not full.is_file():
        return None, f"missing artifact {entry['path']!r}"
    if sha256_file(full) != entry["sha256"]:
        return None, f"digest mismatch for {entry['path']!r}"
    return None, None


def check_uncertainty_budget(name: str, budget: dict,
                             required_sources: set[str]
                             ) -> tuple[float, list[str], list[str]]:
    """Validate a quantitative uncertainty budget.

    Returns (total standard uncertainty, structural problems, coverage
    problems). Every required source must appear as a component carrying a
    numeric estimate or a declared exact/deterministic justification; a list
    of source names alone can never satisfy this. The recorded total must be
    consistent with the declared aggregation of the components.
    """
    structural: list[str] = []
    coverage: list[str] = []
    comps = budget["components"]
    total = float(budget["total"])
    estimates = [float(c["estimate"]) for c in comps.values() if "estimate" in c]
    if budget["aggregation"] == "rss":
        calc = math.sqrt(sum(e * e for e in estimates))
    else:  # sum
        calc = sum(estimates)
    if abs(calc - total) > 1e-9 + 1e-6 * max(abs(calc), abs(total)):
        structural.append(f"{name}: recorded total uncertainty {total} is "
                          f"inconsistent with {budget['aggregation']} of "
                          f"components ({calc})")
    for src in sorted(required_sources):
        if src not in comps:
            coverage.append(f"{name}: mandatory uncertainty source {src!r} has "
                            "no quantified component")
    return total, structural, coverage


def _scale_factor(rule: dict, rec: dict, total_unc: float) -> tuple[float | None, str | None]:
    scale = rule.get("scale", "absolute")
    if scale == "absolute":
        return 1.0, None
    if scale == "relative":
        ref = rec.get("reference")
        if ref is None or float(ref) == 0.0:
            return None, "relative scale requires a nonzero 'reference'"
        return abs(float(ref)), None
    if total_unc <= 0:
        return None, "standard-errors scale requires positive total uncertainty"
    return total_unc, None


def evaluate_metric(spec: dict, rec: dict, z: float,
                    required_sources: set[str]) -> dict:
    """Apply one metric's typed executable decision semantics.

    Returns {"support": bool|None, "reversed": bool, "structural": [...],
    "reasons": [...]}. `support` is None when the metric is indeterminate.

    - Support is a point comparison of the recorded value against the typed
      support operator/bound.
    - Reversal is only possible for role=reversal-capable metrics, and only
      when the value is confidently (at z total standard uncertainties, using
      the contract's corrected alpha) on the declared opposite side of the
      explicit reversal bound. Support-only metrics can never produce a
      reversal, no matter how badly they fail.
    """
    out = {"support": None, "reversed": False, "structural": [], "reasons": []}
    name = spec["name"]
    value = float(rec["value"])
    if spec["domain"] == "nonnegative" and value < 0:
        out["structural"].append(
            f"{name}: negative value for a nonnegative-domain metric")
        return out
    total, structural, coverage = check_uncertainty_budget(
        name, rec["uncertainty_budget"], required_sources)
    if structural:
        out["structural"] += structural
        return out
    if coverage:
        out["reasons"] += coverage
        return out
    sup = spec["support"]
    factor, err = _scale_factor(sup, rec, total)
    if err:
        out["structural"].append(f"{name}: {err}")
        return out
    op = sup["operator"]
    if op == "le":
        ok = value <= sup["bound"] * factor
    elif op == "ge":
        ok = value >= sup["bound"] * factor
    elif op == "abs_le":
        ok = abs(value) <= sup["bound"] * factor
    else:  # between (absolute scale)
        ok = sup["lower"] <= value <= sup["upper"]
    out["support"] = ok
    if not ok:
        out["reasons"].append(f"{name}: support condition {op} failed "
                              f"(value {value})")
    if spec["role"] == "reversal-capable":
        rev = spec["reversal"]
        rfactor, err = _scale_factor(rev, rec, total)
        if err:
            out["structural"].append(f"{name}: reversal {err}")
            return out
        thr = rev["bound"] * rfactor
        if rev["operator"] == "le":
            confident = (value + z * total) <= thr
        else:  # ge
            confident = (value - z * total) >= thr
        if confident:
            out["reversed"] = True
            out["reasons"].append(
                f"{name}: confidently satisfies reversal condition "
                f"{rev['operator']} {thr} (value {value}, z={z:.3f}, u={total})")
    return out


def corrected_z(contract: dict, n_variations: int) -> tuple[float, dict]:
    """Return the z quantile after the declared multiple-comparisons correction.

    The comparison family is (number of grid cells) x (number of required
    metrics). Only 'none' and 'bonferroni' are implemented; the schema rejects
    anything else so the evaluator can never silently ignore a declared method.
    """
    cm = contract["decision_rules"]["confidence_model"]
    alpha = cm["alpha"]
    method = cm.get("multiple_comparisons", "bonferroni")
    n_metrics = sum(1 for m in contract["metrics"]
                    if m.get("required_for_support", True))
    family = max(1, n_variations * n_metrics)
    alpha_adj = alpha / family if method == "bonferroni" else alpha
    z = NormalDist().inv_cdf(1 - alpha_adj / 2)
    return z, {"method": method, "family_size": family,
               "alpha": alpha, "alpha_adjusted": alpha_adj, "z": z}


def derive_verdict(contract: dict, variation: dict, z: float
                   ) -> tuple[str, list[str], list[str]]:
    """Derive supported | reversed | indeterminate for one variation.

    Returns (verdict, reasons, structural problems). Caller-supplied verdicts
    are never accepted. Deterministic combination (combination_rule
    standard-v1):
    - any confidently-triggered reversal-capable metric -> reversed, unless
      every required support condition also passes (contradictory evidence),
      which is indeterminate;
    - all required metrics recorded, covered, and passing -> supported;
    - anything else -> indeterminate (fail closed).
    """
    reasons: list[str] = []
    structural: list[str] = []
    if variation.get("evidence_missing"):
        return "indeterminate", ["evidence missing for this variation"], []
    # Per-variation artifact accounting.
    artifact_problems: list[str] = []
    for entry in variation["artifacts"]:
        s, e = check_artifact(entry)
        if s:
            structural.append(f"variation {variation['id']!r}: {s}")
        elif e:
            artifact_problems.append(f"variation {variation['id']!r}: {e}")
    if structural:
        return "indeterminate", reasons, structural
    if artifact_problems:
        return "indeterminate", artifact_problems, []
    metrics_spec = {m["name"]: m for m in contract["metrics"]}
    recorded = variation["metrics"]
    unknown = set(recorded) - set(metrics_spec)
    if unknown:
        return "indeterminate", [], [
            f"variation {variation['id']!r}: unknown metric(s) {sorted(unknown)}"]
    required_sources = set(
        contract["decision_rules"]["confidence_model"].get("uncertainty_sources", []))
    all_required_pass = True
    any_reversal = False
    for name, spec in metrics_spec.items():
        required = spec.get("required_for_support", True)
        rec = recorded.get(name)
        if rec is None:
            if required:
                all_required_pass = False
                reasons.append(f"{name}: required metric not recorded")
            continue
        res = evaluate_metric(spec, rec, z, required_sources)
        structural += res["structural"]
        reasons += res["reasons"]
        if res["reversed"]:
            any_reversal = True
        if required and res["support"] is not True:
            all_required_pass = False
    if structural:
        return "indeterminate", reasons, structural
    if any_reversal and all_required_pass:
        return "indeterminate", reasons + [
            "contradictory evidence: reversal condition met while all support "
            "conditions pass"], []
    if any_reversal:
        return "reversed", reasons, []
    if all_required_pass:
        return "supported", reasons, []
    return "indeterminate", reasons, []


def expected_variation_grid(contract: dict) -> tuple[list[str], set[tuple]]:
    """Return (dimension names, set of allowed value combinations)."""
    dims = contract["allowed_variations"]["dimensions"]
    names = [d["name"] for d in dims]
    grid = set(itertools.product(*(tuple(d["values"]) for d in dims)))
    return names, grid


def check_variation_grid(contract: dict, variations: list[dict]) -> tuple[dict, list[str], list[str]]:
    """Enforce the complete declared variation grid.

    Returns (combo -> variation, structural problems, missing combo labels).
    Structural problems: duplicate variation ids, unknown dimensions,
    undeclared or non-scalar values, incomplete dimension sets, and duplicate
    combinations. Missing combos are returned separately so the
    missing-evidence policy can decide their consequence.
    """
    names, grid = expected_variation_grid(contract)
    seen: dict[tuple, dict] = {}
    problems: list[str] = []
    ids = [v["id"] for v in variations]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"duplicate variation id {dup!r}")
    dim_values = {d["name"]: set(d["values"])
                  for d in contract["allowed_variations"]["dimensions"]}
    for var in variations:
        dims = var["dimensions"]
        nonscalar = [k for k, v in dims.items() if not isinstance(v, SCALAR_TYPES)]
        if nonscalar:
            problems.append(f"variation {var['id']!r}: non-scalar dimension "
                            f"value(s) for {sorted(nonscalar)}")
            continue
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


def check_baseline(contract: dict, results: dict) -> tuple[dict, list[str]]:
    """Honest baseline accounting.

    Returns (baseline report, structural problems). The report records what
    can actually be established:
    - baseline_id must exactly match a frozen identifier from the contract
      (the initial baseline id or an escalation rule's expected baseline id);
    - artifact evidence must be repo-relative regular files with matching
      SHA-256 digests (this is the only thing called 'verified' here);
    - citations are recorded as citation-present; a citation can establish
      provenance but never proves the baseline was executed;
    - escalation trigger criteria are locked contract text; whether a trigger
      holds may require human judgment, so the evaluator echoes the locked
      criteria and the recorded trigger evidence instead of pretending it can
      determine the strongest known algorithm in the literature.
    """
    structural: list[str] = []
    baseline = results["baseline"]
    escalation = results["escalation"]
    policy = contract["baseline_policy"]
    rules = {r["id"]: r for r in policy["escalation_rules"]}
    declared_ids = {policy["initial_baseline_id"]} | {
        r["expected_baseline_id"] for r in policy["escalation_rules"]}
    bid = baseline["baseline_id"]
    if bid not in declared_ids:
        structural.append(f"baseline_id {bid!r} is not a frozen identifier "
                          f"declared by the contract ({sorted(declared_ids)})")
    rule_id = escalation.get("rule_id")
    fired = bool(escalation["trigger_fired"])
    honored = bool(escalation["honored"])
    trigger_criteria = None
    if fired:
        if rule_id not in rules:
            structural.append(f"escalation rule_id {rule_id!r} does not match a "
                              "declared escalation rule")
        else:
            trigger_criteria = rules[rule_id]["trigger"]
            if honored and bid != rules[rule_id]["expected_baseline_id"]:
                structural.append(
                    f"escalation claimed honored but baseline_id {bid!r} is not "
                    f"the rule's expected baseline "
                    f"{rules[rule_id]['expected_baseline_id']!r}")
    artifacts_verified = bool(baseline["artifacts"])
    for entry in baseline["artifacts"]:
        s, e = check_artifact(entry)
        if s:
            structural.append(f"baseline artifact: {s}")
            artifacts_verified = False
        elif e:
            structural.append(f"baseline artifact: {e} (baseline provenance "
                              "cannot be established)")
            artifacts_verified = False
    if baseline["matched_inputs"] is not True:
        structural.append("baseline inputs were not matched to the quantum side")
    if honored and not baseline["artifacts"]:
        structural.append("escalation claimed honored without artifact evidence; "
                          "citations alone cannot prove the baseline was executed")
    report = {
        "baseline_id": bid,
        "artifacts_verified": artifacts_verified,
        "citations_recorded": list(baseline.get("citations", [])),
        "citation_status": "citation-present" if baseline.get("citations") else "none",
        "trigger_fired": fired,
        "trigger_criteria_locked": trigger_criteria,
        "trigger_evidence_recorded": list(escalation.get("trigger_evidence", [])),
        "honored": honored,
    }
    return report, structural


def _bind_contract_to_seal(contract_arg: str) -> tuple[Path | None, dict | None, list[str]]:
    """Refuse to evaluate unless the contract is bound to a verified seal.

    Requires: the seal exists and verifies (including engine version); the
    supplied contract path is repo-relative and resolves inside the repo; it
    is the exact contract referenced by the manifest claim entry; its hash
    appears in the seal; and the current file contents match that hash.
    """
    problems: list[str] = []
    if not SEAL_PATH.exists():
        return None, None, ["no protocol seal exists; production evaluation "
                            "requires a committed, verified seal"]
    try:
        seal = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, None, [f"malformed seal JSON: {exc}"]
    seal_problems = verify_seal_data(seal)
    if seal_problems:
        return None, None, [f"seal verification failed: {p}" for p in seal_problems]
    full, problem = check_repo_path(contract_arg)
    if problem:
        return None, None, [f"contract path: {problem}"]
    if not full.is_file():
        return None, None, [f"contract file not found: {contract_arg!r}"]
    rel = str(full.relative_to(REPO.resolve())).replace("\\", "/")
    try:
        contract = load_contract(full)
    except yaml.YAMLError as exc:
        return None, None, [f"contract YAML parse error: {exc}"]
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    claim_key = contract.get("corpus", {}).get("claim_key")
    entry = manifest.get("claims", {}).get(claim_key)
    if not entry:
        problems.append(f"claim_key {claim_key!r} not found in the corpus manifest")
    elif entry.get("contract") != rel:
        problems.append(f"manifest entry for {claim_key!r} references "
                        f"{entry.get('contract')!r}, not {rel!r}")
    if rel not in seal.get("files", {}):
        problems.append(f"contract {rel!r} is not in the sealed file set")
    elif sha256_file(full) != seal["files"][rel]:
        problems.append(f"contract {rel!r} was modified after sealing")
    if problems:
        return None, None, problems
    return full, contract, []


def cmd_evaluate(args: argparse.Namespace) -> int:
    def emit(report: dict, status: str) -> int:
        report["evaluation_status"] = status
        report["engine_version"] = ENGINE_VERSION
        print(json.dumps(report, indent=2))
        return EXIT_VALID if status == "valid" else EXIT_INVALID

    def invalid(reasons: list[str], contract_id: str | None = None) -> int:
        return emit({"contract_id": contract_id, "outcome": "Not Auditable",
                     "invalid_reasons": reasons}, "invalid")

    # 1. Bind to the sealed protocol.
    contract_path, contract, bind_problems = _bind_contract_to_seal(args.contract)
    if bind_problems:
        return invalid(bind_problems)
    schema = load_schema()
    errors = validate_contract(contract_path, schema)
    if errors:
        return invalid([f"contract fails validation: {e}" for e in errors[:5]],
                       contract.get("contract_id"))
    cid = contract["contract_id"]

    # 2. Load results with strict number handling.
    try:
        results = load_json_strict(Path(args.results).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return invalid([f"results unreadable or contain non-finite numbers: {exc}"], cid)
    nonfinite = find_nonfinite(results)
    if nonfinite:
        return invalid([f"non-finite number(s): {p}" for p in nonfinite[:5]], cid)

    schema_errors = validate_results(results)
    if schema_errors:
        return invalid(["results fail the results schema (caller-supplied "
                        "verdicts are not accepted)"] + schema_errors[:5], cid)
    if results["contract_id"] != cid:
        return invalid([f"results contract_id {results['contract_id']!r} does "
                        f"not match contract {cid!r}"], cid)

    policy = contract["missing_evidence_policy"]
    on_missing = policy["on_missing"]
    missing_global = [a for a in policy["required_artifacts"]
                      if not (REPO / a).exists()]
    artifacts_ok = not (missing_global and on_missing == "not-auditable")

    # 3. Enforce the complete declared variation grid (structural).
    by_combo, grid_problems, missing_combos = check_variation_grid(
        contract, results["variations"])
    if grid_problems:
        return invalid(grid_problems, cid)

    # 4. Baseline accounting (provenance failures are structural).
    baseline_report, baseline_problems = check_baseline(contract, results)
    if baseline_problems:
        return invalid(baseline_problems, cid)

    # 5. Derive verdicts with the corrected alpha.
    z, correction = corrected_z(contract, len(expected_variation_grid(contract)[1]))
    verdicts: list[str] = []
    verdict_report: dict[str, dict] = {}
    structural_all: list[str] = []
    for combo, var in by_combo.items():
        verdict, reasons, structural = derive_verdict(contract, var, z)
        structural_all += structural
        if on_missing == "not-auditable" and any(
                "missing artifact" in r or "digest mismatch" in r for r in reasons):
            # Under not-auditable, per-variation artifact failure voids the
            # whole audit (a scientific outcome, not a structural error).
            artifacts_ok = False
        verdicts.append(verdict)
        verdict_report[var["id"]] = {"verdict": verdict, "reasons": reasons}
    if structural_all:
        return invalid(structural_all, cid)
    for m in missing_combos:
        verdicts.append("indeterminate")
        verdict_report[f"<missing: {m}>"] = {
            "verdict": "indeterminate", "reasons": ["variation not evaluated"]}
    if missing_combos and on_missing == "not-auditable":
        artifacts_ok = False

    # 6. Escalation consequence (scientific).
    strongest_required = bool(contract["baseline_policy"]["strongest_known_required"])
    honored_verified = (baseline_report["honored"]
                        and baseline_report["artifacts_verified"])
    escalation_unhonored = baseline_report["trigger_fired"] and not honored_verified

    outcome = aggregate_standard_v1(verdicts, artifacts_ok=artifacts_ok,
                                    escalation_unhonored=escalation_unhonored,
                                    strongest_known_required=strongest_required)

    report = {
        "contract_id": cid,
        "outcome": outcome,
        "verdicts": verdict_report,
        "missing_artifacts": missing_global,
        "missing_variations": missing_combos,
        "baseline": baseline_report,
        "escalation_unhonored": escalation_unhonored,
        "strongest_known_required": strongest_required,
        "multiple_comparisons": correction,
    }
    return emit(report, "valid")


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
