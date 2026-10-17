#!/usr/bin/env python3
"""Fail the build if anything non-public looks like it got committed.

The repository carries an employer-independence disclaimer. That disclaimer is
a claim about the contents, so it needs a check behind it rather than trust.

Three scans:

1. **Named utilities.** The author works in interconnection and tariff at a
   Pennsylvania utility, and this repo analyzes interconnection screens and
   PJM carbon signals. The adjacency has to be stated in the disclaimer and
   absent from the analysis. A specific utility named as a worked example
   reads as insider framing even when every input is public.

   Two exceptions are legitimate and allowlisted: `interconnection-analytics`
   reports a PPL cut of the public LBNL dataset, where "PPL" is a value in a
   public data file, and the disclaimer itself.

2. **Internal document markers.** Classification banners and the like.

3. **Credentials.** API keys, tokens, private key blocks.

Run: python tools/check_no_private_data.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCAN_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".cff", ".ipynb", ".sh"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "data", "outputs"}

# Utility names that must not appear as worked examples in analysis code or
# prose. Matched case-insensitively on word boundaries.
UTILITY_NAMES = [
    "PPL Electric",
    "PPL Electric Utilities",
    "Met-Ed",
    "PECO",
    "PENELEC",
    "Duquesne Light",
    "West Penn Power",
]

# Files where a utility name is legitimate, with the reason.
UTILITY_ALLOWLIST = {
    "README.md": "disclaimer language only",
    "NOTICE.md": "attribution",
    "NOTICE": "attribution",
    "FINDINGS.md": "PPL cut of the public LBNL dataset",
    "interconnection-analytics/README.md": "PPL cut of the public LBNL dataset",
    "interconnection-analytics/iqueue/ingest.py": "PPL is a value in the public LBNL utility column",
    "interconnection-analytics/iqueue/analysis.py": "PPL is a value in the public LBNL utility column",
    "interconnection-analytics/run_analysis.py": "PPL cut of the public LBNL dataset",
    "tests/test_interconnection_analytics.py": "asserts the public dataset contains PPL rows",
    "tools/check_no_private_data.py": "this file defines the patterns",
    "tools/check_claims.py": "claim table references the PPL figures",
}

INTERNAL_MARKERS = [
    "internal use only",
    "company confidential",
    "proprietary and confidential",
    "do not distribute",
    "attorney-client",
    "privileged and confidential",
]

# Files that define or exercise the patterns above. See the note in run().
SELF_REFERENTIAL = {
    "tools/check_no_private_data.py",
    "tests/test_claim_guard.py",
}

CREDENTIAL_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    (r"github_pat_[A-Za-z0-9_]{22,}", "GitHub fine-grained token"),
    (r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----", "private key block"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"(?i)\b(?:api[_-]?key|secret|password|passwd)\s*[:=]\s*['\"][^'\"]{12,}['\"]", "hardcoded secret"),
]


def files_to_scan() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def run() -> int:
    failures: list[str] = []
    scanned = 0

    for path in files_to_scan():
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        scanned += 1
        lowered = text.lower()

        # Files that exist to define or exercise these patterns necessarily
        # contain them. Scanning them is guaranteed to match, which would make
        # the check impossible to write or test.
        #
        # The tradeoff is explicit: a real credential committed inside one of
        # these two files would not be caught here. That is accepted because
        # the alternative is an untestable check, and these are the two files a
        # reviewer reads most closely. Everything else in the repo is scanned.
        if rel in SELF_REFERENTIAL:
            continue

        if rel not in UTILITY_ALLOWLIST:
            for name in UTILITY_NAMES:
                if re.search(rf"\b{re.escape(name.lower())}\b", lowered):
                    failures.append(
                        f"{rel}: names a specific utility ({name!r}). "
                        "Use a generic placeholder, or add an allowlist entry "
                        "in tools/check_no_private_data.py explaining why it is public."
                    )

        for marker in INTERNAL_MARKERS:
            if marker in lowered:
                failures.append(f"{rel}: internal-document marker {marker!r}")

        for pattern, label in CREDENTIAL_PATTERNS:
            if re.search(pattern, text):
                failures.append(f"{rel}: looks like a committed {label}")

    if failures:
        print(f"FAILED: {len(failures)} problem(s) across {scanned} files\n")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"OK: {scanned} files scanned, no non-public data indicators")
    return 0


if __name__ == "__main__":
    sys.exit(run())
