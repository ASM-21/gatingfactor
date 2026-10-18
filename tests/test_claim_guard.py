"""Tests for the prose guard.

The point of these is injection testing: a guard that has never been shown to
fail is indistinguishable from a guard that cannot fail. Two real bugs in
sibling repos were exactly this. One compared a wrapped markdown blockquote
against a raw substring and so never matched; the other scanned forbidden
phrases line by line and so missed any phrase that wrapped across a newline.
Both silently passed for weeks.

Each test here deliberately breaks something and asserts the guard notices.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "tools" / "check_claims.py"


def run_guard(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "tools/check_claims.py"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def inject(path: Path, old: str, new: str) -> None:
    """Edit a file and assert the edit actually landed.

    This helper exists because the first version of these tests was bitten by
    the very bug they were written to catch. The guarded phrases are wrapped
    markdown blockquotes, so a phrase like "not calibrated to any real circuit"
    does not appear contiguously in the source; it is split across a line break
    and a "> " prefix. A plain str.replace matched nothing, changed nothing,
    and the test then "passed" against an unmodified file while reporting that
    the guard had a hole.

    So every injection asserts it changed the text. A test that cannot prove it
    broke something cannot prove the guard caught something.
    """
    before = path.read_text()
    after = before.replace(old, new)
    assert after != before, (
        f"injection did not land: {old!r} is not a contiguous substring of "
        f"{path.name}. It is probably wrapped across lines; pick a fragment "
        f"that sits on one line."
    )
    path.write_text(after)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A copy of the repo's prose, results, and guard. Cheap: no source code."""
    dest = tmp_path / "repo"
    (dest / "tools").mkdir(parents=True)
    shutil.copy(GUARD, dest / "tools" / "check_claims.py")
    shutil.copytree(REPO / "data" / "processed", dest / "data" / "processed")
    shutil.copytree(REPO / "outputs", dest / "outputs")
    for md in ("README.md", "FINDINGS.md"):
        shutil.copy(REPO / md, dest / md)
    for track in (
        "interconnection-analytics",
        "hosting-capacity-sim",
        "tariff-explorer",
        "carbon-aware-der",
    ):
        (dest / track).mkdir(exist_ok=True)
        shutil.copy(REPO / track / "README.md", dest / track / "README.md")
    return dest


def test_guard_passes_on_the_real_repo():
    """Baseline. If this fails, every other test here is meaningless."""
    result = run_guard(REPO)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK:" in result.stdout


def test_guard_passes_on_sandbox(sandbox: Path):
    assert run_guard(sandbox).returncode == 0


def test_catches_a_changed_figure(sandbox: Path):
    """Edit a number in the prose without rerunning the pipeline."""
    readme = sandbox / "interconnection-analytics" / "README.md"
    inject(readme, "1.55x to 2.06x", "1.20x to 1.30x")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "1.55x to 2.06x" in result.stdout


def test_catches_drifted_results(sandbox: Path):
    """Change the results without updating the prose. The other direction."""
    import pandas as pd

    path = sandbox / "data" / "processed" / "interconnection-analytics" / "cohort_outcomes.parquet"
    df = pd.read_parquet(path)
    df.loc[df.cohort_start == 1995, "completion_rate"] = 0.9
    df.to_parquet(path, index=False)
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "drifted" in result.stdout


def test_catches_deleted_disclaimer(sandbox: Path):
    readme = sandbox / "README.md"
    inject(readme, "independent personal", "ordinary")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "disclaimer" in result.stdout.lower()


def test_catches_partially_deleted_disclaimer(sandbox: Path):
    """Deleting one clause of the disclaimer must fail, not just deleting it all."""
    readme = sandbox / "README.md"
    # "utility-internal" sits on one line; the full phrase wraps.
    inject(readme, "utility-internal", "unusual")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "disclaimer phrase deleted" in result.stdout


def test_catches_deleted_synthetic_caveat(sandbox: Path):
    """The caveat that track 2's feeders are not real circuits."""
    readme = sandbox / "hosting-capacity-sim" / "README.md"
    # "calibrated" sits on one line; the full caveat wraps across two.
    inject(readme, "calibrated", "tuned")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "required text deleted" in result.stdout


def test_catches_deleted_data_attribution(sandbox: Path):
    readme = sandbox / "carbon-aware-der" / "README.md"
    inject(readme, "CarbonCast", "a public source")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "attribution" in result.stdout.lower()


def test_catches_overclaiming(sandbox: Path):
    readme = sandbox / "FINDINGS.md"
    readme.write_text(readme.read_text() + "\n\nThis analysis proves that the screen is wrong.\n")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "overclaiming" in result.stdout


def test_catches_overclaiming_wrapped_across_lines(sandbox: Path):
    """The exact bug that hid in a sibling repo: a phrase split by a newline.

    A line-by-line scan passes this. Only normalized-text comparison catches it.
    """
    readme = sandbox / "FINDINGS.md"
    readme.write_text(readme.read_text() + "\n\nThis result is\nguaranteed to hold.\n")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "guaranteed" in result.stdout


def test_catches_novelty_claim(sandbox: Path):
    readme = sandbox / "FINDINGS.md"
    readme.write_text(readme.read_text() + "\n\nWe discovered this effect.\n")
    result = run_guard(sandbox)
    assert result.returncode == 1


def test_mention_in_backticks_is_allowed(sandbox: Path):
    """The use/mention distinction, so the ban can be documented.

    Without this the guard cannot describe its own rules without failing, and a
    guard people must disable to document is a guard that gets disabled.
    """
    readme = sandbox / "FINDINGS.md"
    readme.write_text(readme.read_text() + "\n\nThe guard rejects `guaranteed` in prose.\n")
    assert run_guard(sandbox).returncode == 0


def test_catches_missing_file(sandbox: Path):
    (sandbox / "FINDINGS.md").unlink()
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "MISSING FILE" in result.stdout


# --- non-public data guard --------------------------------------------------

PRIVATE_GUARD = REPO / "tools" / "check_no_private_data.py"


def run_private_guard(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "tools/check_no_private_data.py"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def private_sandbox(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    (dest / "tools").mkdir(parents=True)
    shutil.copy(PRIVATE_GUARD, dest / "tools" / "check_no_private_data.py")
    shutil.copy(REPO / "README.md", dest / "README.md")
    (dest / "sometrack").mkdir()
    (dest / "sometrack" / "analysis.py").write_text("# a clean analysis module\n")
    return dest


def test_private_guard_passes_on_real_repo():
    result = run_private_guard(REPO)
    assert result.returncode == 0, result.stdout + result.stderr


def test_private_guard_passes_on_sandbox(private_sandbox: Path):
    assert run_private_guard(private_sandbox).returncode == 0


def test_catches_named_utility(private_sandbox: Path):
    """The failure mode this check exists for.

    In a sibling repo, writing this check found a real problem: a track named
    the author's employer five times as its worked example, inside a repo whose
    README disclaims employer affiliation.
    """
    target = private_sandbox / "sometrack" / "analysis.py"
    target.write_text('UTILITY = "PPL Electric"  # worked example\n')
    result = run_private_guard(private_sandbox)
    assert result.returncode == 1
    assert "names a specific utility" in result.stdout


def test_catches_internal_marker(private_sandbox: Path):
    target = private_sandbox / "sometrack" / "analysis.py"
    target.write_text('"""Company Confidential - do not share."""\n')
    result = run_private_guard(private_sandbox)
    assert result.returncode == 1
    assert "internal-document marker" in result.stdout


def test_catches_committed_credential(private_sandbox: Path):
    target = private_sandbox / "sometrack" / "analysis.py"
    target.write_text('TOKEN = "ghp_' + "a" * 36 + '"\n')
    result = run_private_guard(private_sandbox)
    assert result.returncode == 1
    assert "token" in result.stdout.lower()


def test_catches_private_key_block(private_sandbox: Path):
    (private_sandbox / "sometrack" / "key.txt").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n"
    )
    result = run_private_guard(private_sandbox)
    assert result.returncode == 1
    assert "private key" in result.stdout.lower()


def test_catches_deleted_track1_retraction(sandbox: Path):
    """The track 1 retraction must stay visible, like the other two."""
    findings = sandbox / "FINDINGS.md"
    inject(findings, "Track 1: the Kaplan-Meier median", "Track 1: a note")
    result = run_guard(sandbox)
    assert result.returncode == 1
    assert "retraction of the track 1" in result.stdout
