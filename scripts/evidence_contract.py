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
verify-seal                         Recompute hashes and compare with the seal.
evaluate <contract.yaml> --results <results.json>
                                    Apply the standard-v1 aggregation rule and print
                                    the outcome: Stable, Conditionally Stable,
                                    Unresolved, Reversed, or Not Auditable.

The seal must be committed BEFORE any outcome-bearing evaluation (see
docs/research/locked-audit-protocol.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "specs" / "evidence-contract.schema.json"
PROTOCOL_PATH = REPO / "docs" / "research" / "locked-audit-protocol.md"
MANIFEST_PATH = REPO / "docs" / "research" / "claim-corpus-manifest.yaml"
SEAL_PATH = REPO / "specs" / "protocol-seal.json"

OUTCOMES = ["Stable", "Conditionally Stable", "Unresolved", "Reversed", "Not Auditable"]
VERDICTS = {"supported", "reversed", "indeterminate"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


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


def cmd_seal_protocol(args: argparse.Namespace) -> int:
    if SEAL_PATH.exists():
        print(f"error: seal already exists at {SEAL_PATH}; amendments require a new "
              "protocol version (see protocol §7)", file=sys.stderr)
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
    body = json.dumps(seal, indent=2, sort_keys=True)
    seal["seal_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    SEAL_PATH.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8", newline="\n")
    print(f"sealed {len(entries)} files -> {SEAL_PATH}")
    print(f"seal hash: {seal['seal_hash']}")
    return 0


def cmd_verify_seal(_args: argparse.Namespace) -> int:
    if not SEAL_PATH.exists():
        print("error: no seal found; run seal-protocol first", file=sys.stderr)
        return 1
    seal = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
    failed = False
    for rel, expected in seal["files"].items():
        path = REPO / rel
        if not path.exists():
            print(f"[FAIL] {rel}: missing")
            failed = True
            continue
        actual = sha256_file(path)
        if actual != expected:
            print(f"[FAIL] {rel}: hash mismatch (sealed {expected[:12]}..., "
                  f"actual {actual[:12]}...)")
            failed = True
        else:
            print(f"[OK ] {rel}")
    if failed:
        print("SEAL BROKEN: sealed files changed after sealing.", file=sys.stderr)
        return 1
    print("Seal intact.")
    return 0


def aggregate_standard_v1(verdicts: list[str], *, artifacts_ok: bool,
                          escalation_capped: bool) -> str:
    """Map per-variation verdicts to a final outcome (protocol §5)."""
    if not artifacts_ok:
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
    if escalation_capped and outcome == "Stable":
        outcome = "Conditionally Stable"
    return outcome


def cmd_evaluate(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    schema = load_schema()
    errors = validate_contract(contract_path, schema)
    if errors:
        print(f"error: contract fails schema validation: {errors[0]}", file=sys.stderr)
        return 1
    contract = load_contract(contract_path)
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))

    variations = results.get("variations", [])
    if not variations:
        print("error: results contain no variations", file=sys.stderr)
        return 1
    verdicts = []
    for var in variations:
        verdict = var.get("verdict")
        if verdict not in VERDICTS:
            print(f"error: variation {var.get('id')!r} has invalid verdict "
                  f"{verdict!r} (must be one of {sorted(VERDICTS)})", file=sys.stderr)
            return 1
        verdicts.append(verdict)

    policy = contract["missing_evidence_policy"]
    missing = [a for a in policy["required_artifacts"] if not (REPO / a).exists()]
    artifacts_ok = not (missing and policy["on_missing"] == "not-auditable")

    escalation_capped = bool(results.get("escalation_trigger_fired")
                             and not results.get("escalation_honored", False))

    outcome = aggregate_standard_v1(verdicts, artifacts_ok=artifacts_ok,
                                    escalation_capped=escalation_capped)

    report = {
        "contract_id": contract["contract_id"],
        "outcome": outcome,
        "verdicts": {v.get("id", f"variation-{i}"): v["verdict"]
                     for i, v in enumerate(variations)},
        "missing_artifacts": missing,
        "escalation_capped": escalation_capped,
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
