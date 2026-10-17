"""Canonical filesystem locations for gatingfactor.

Every track reads and writes through these helpers so that raw pulls, processed
parquet, and generated figures land in predictable places regardless of which
subpackage produced them.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DATA = REPO_ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
OUTPUTS = REPO_ROOT / "outputs"


def ensure_dirs() -> None:
    """Create the standard data/output tree if it does not already exist."""
    for d in (DATA, RAW, PROCESSED, OUTPUTS):
        d.mkdir(parents=True, exist_ok=True)


def raw(track: str, filename: str) -> Path:
    """Path for a cached raw download, namespaced by track."""
    d = RAW / track
    d.mkdir(parents=True, exist_ok=True)
    return d / filename


def processed(track: str, filename: str) -> Path:
    """Path for a cleaned/normalized artifact, namespaced by track."""
    d = PROCESSED / track
    d.mkdir(parents=True, exist_ok=True)
    return d / filename


def output(track: str, filename: str) -> Path:
    """Path for a figure, report, or other user-facing deliverable."""
    d = OUTPUTS / track
    d.mkdir(parents=True, exist_ok=True)
    return d / filename


ensure_dirs()
