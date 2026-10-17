"""Cached download and processed-artifact I/O shared across tracks.

Two rules the whole repo relies on:

1. A raw pull is written once and never mutated. Re-running a pipeline with a
   warm cache must not touch the network.
2. Anything derived goes to parquet under ``data/processed/<track>/`` so the
   analysis layer never re-parses source CSV/Excel.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

from . import paths

USER_AGENT = "gatingfactor/0.1 (personal research; contact via repo)"


class SourceUnavailable(RuntimeError):
    """Raised when a public data source cannot be reached.

    Tracks catch this to fall back to a cached or bundled copy rather than
    dying, and they must say in their output which path was taken.
    """


def download(url: str, dest: Path, timeout: int = 120, force: bool = False) -> Path:
    """Fetch ``url`` to ``dest`` unless already cached.

    Raises SourceUnavailable rather than a bare URLError so callers can
    distinguish "network is blocked" from a genuine bug.
    """
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise SourceUnavailable(f"could not fetch {url}: {exc}") from exc

    if not payload:
        raise SourceUnavailable(f"empty response from {url}")

    dest.write_bytes(payload)
    return dest


def sha256(path: Path) -> str:
    """Content hash of a raw pull, for provenance lines in reports."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_processed(df: pd.DataFrame, track: str, name: str) -> Path:
    """Persist a derived frame to parquet and return where it landed."""
    if not name.endswith(".parquet"):
        name = f"{name}.parquet"
    dest = paths.processed(track, name)
    df.to_parquet(dest, index=False)
    return dest


def read_processed(track: str, name: str) -> pd.DataFrame:
    if not name.endswith(".parquet"):
        name = f"{name}.parquet"
    src = paths.processed(track, name)
    if not src.exists():
        raise FileNotFoundError(f"{src} not built yet; run that track's pipeline first")
    return pd.read_parquet(src)
