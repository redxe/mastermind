"""Cross-platform artifact integrity check.

Walks every SHA256SUMS.txt under artifacts/ (including the top-level Ariadion
set) and verifies each listed file's SHA-256 against the recorded hash, byte
for byte. Exits nonzero on any mismatch or missing file. No dependencies.

Usage: python scripts/verify_artifacts.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"


def check_sums_file(sums_path: Path) -> list[str]:
    errors = []
    base = sums_path.parent
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        expected, _, name = line.partition("  ")
        target = base / name
        if not target.is_file():
            errors.append(f"MISSING  {target.relative_to(ROOT)}")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"MISMATCH {target.relative_to(ROOT)}\n"
                          f"  expected {expected}\n  actual   {actual}")
    return errors


def main() -> int:
    sums_files = sorted(ART.rglob("SHA256SUMS.txt"))
    if not sums_files:
        print("ERROR: no SHA256SUMS.txt files found under artifacts/")
        return 1
    total, failures = 0, []
    for sf in sums_files:
        n = len([ln for ln in sf.read_text(encoding="utf-8").splitlines() if ln.strip()])
        total += n
        errs = check_sums_file(sf)
        status = "OK " if not errs else "FAIL"
        print(f"[{status}] {sf.relative_to(ROOT)} ({n} files)")
        failures.extend(errs)
    if failures:
        print("\n".join(failures))
        print(f"\n{len(failures)} integrity failure(s) across {total} hashed files.")
        return 1
    print(f"\nAll {total} hashed files verified across {len(sums_files)} manifests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
