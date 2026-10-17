"""Ingest and normalization for interconnection queue data.

Two sources, one canonical schema.

**LBNL "Queued Up"** is the historical record: every interconnection request
across the major US balancing areas through end of 2024, with status, dates,
and resource type. Sheet ``03. Complete Queue Data`` holds the project-level
table; the header sits on the second row because the first is a navigation
link back to the workbook contents.

**PJM queue snapshot** is a point-in-time export of PJM's active queue with
study-milestone columns that LBNL does not carry.

Two data quirks that will silently corrupt an analysis if missed:

1. **Dates arrive as Excel serial numbers**, not datetimes. They need
   ``origin="1899-12-30"``. Read naively they come through as float64 and every
   duration calculation yields NaN, which looks like missing data rather than a
   parsing bug.

2. **Date coverage is wildly uneven.** ``q_date`` is 98% populated but
   ``on_date`` is 8% and ``ia_date`` is 7%. That is not a defect in the data,
   it reflects that most projects never reach those milestones. Any statistic
   conditioned on ``on_date`` is therefore conditioned on success, which is the
   central methodological hazard in this dataset and is handled explicitly in
   ``analysis.py``.

Canonical schema produced by ``load_lbnl``:

    project_id, status, region, utility, state, county, poi_name,
    resource_type, capacity_mw, service_type, cluster,
    queue_date, proposed_cod_date, actual_cod_date, withdrawal_date,
    ia_date, queue_year
"""

from __future__ import annotations

import pandas as pd

from shared import paths

LBNL_FILE = "LBNL_Ix_Queue_Data_File_thru2024_v2.xlsx"
LBNL_SHEET = "03. Complete Queue Data"
LBNL_HEADER_ROW = 1

PJM_SNAPSHOT = "pjm_queue_snapshot_2026-05-05.parquet"

EXCEL_EPOCH = "1899-12-30"
DATE_COLUMNS = ("q_date", "prop_date", "on_date", "wd_date", "ia_date")

# LBNL's raw column names to the repo's canonical names.
COLUMN_MAP = {
    "q_id": "project_id",
    "q_status": "status",
    "region": "region",
    "utility": "utility",
    "state": "state",
    "county": "county",
    "poi_name": "poi_name",
    "type_clean": "resource_type",
    "mw1": "capacity_mw",
    "service": "service_type",
    "cluster": "cluster",
    "q_date": "queue_date",
    "prop_date": "proposed_cod_date",
    "on_date": "actual_cod_date",
    "wd_date": "withdrawal_date",
    "ia_date": "ia_date",
}

# Status vocabulary. LBNL uses these five; "unknown" is a handful of rows.
ACTIVE = "active"
WITHDRAWN = "withdrawn"
OPERATIONAL = "operational"
SUSPENDED = "suspended"

# Resource types collapsed for reporting. Solar+Battery is kept distinct from
# Solar because hybrid projects behave differently in the queue.
RESOURCE_GROUPS = {
    "Solar": "Solar",
    "Solar+Battery": "Solar+Storage",
    "Battery": "Storage",
    "Wind": "Wind",
    "Offshore Wind": "Offshore Wind",
    "Gas": "Gas",
    "Coal": "Coal",
    "Nuclear": "Nuclear",
    "Hydro": "Hydro",
}


class SourceMissing(FileNotFoundError):
    """Raised with a pointer to where the file comes from."""


def _excel_dates(df: pd.DataFrame, columns=DATE_COLUMNS) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col], unit="D", origin=EXCEL_EPOCH, errors="coerce"
            )
    return df


def load_lbnl(path=None) -> pd.DataFrame:
    """Load and normalize the LBNL Queued Up project-level table."""
    src = paths.raw("lbnl", LBNL_FILE) if path is None else path
    if not src.exists():
        raise SourceMissing(
            f"{src} missing. Berkeley Lab publishes Queued Up at "
            "https://emp.lbl.gov/queues (annual release, Excel)."
        )
    raw = pd.read_excel(src, sheet_name=LBNL_SHEET, header=LBNL_HEADER_ROW)
    raw = _excel_dates(raw)

    df = raw[list(COLUMN_MAP)].rename(columns=COLUMN_MAP).copy()
    df["capacity_mw"] = pd.to_numeric(df.capacity_mw, errors="coerce")
    # project_id is mixed int/str across regions; force a single type so the
    # frame round-trips through parquet.
    df["project_id"] = df.project_id.astype(str)
    for col in ("status", "region", "utility", "state", "county", "poi_name",
                "resource_type", "service_type", "cluster"):
        df[col] = df[col].astype("string")
    # A handful of rows carry negative capacity. These are capacity *decrease*
    # requests, a legitimate queue product where an interconnection customer
    # gives back rights. They are flagged rather than dropped, because letting
    # them net silently into a "total MW requested" sum understates the total.
    df["is_capacity_decrease"] = df.capacity_mw < 0
    df["queue_year"] = df.queue_date.dt.year
    df["resource_group"] = df.resource_type.map(RESOURCE_GROUPS).fillna("Other")
    df["status"] = df.status.str.lower().str.strip()
    return df.reset_index(drop=True)


def load_pjm_snapshot(path=None) -> pd.DataFrame:
    """Load a PJM queue snapshot, normalized to the same canonical names."""
    src = paths.raw("pjm", PJM_SNAPSHOT) if path is None else path
    if not src.exists():
        raise SourceMissing(
            f"{src} missing. PJM publishes its serial service request queue at "
            "https://www.pjm.com/planning/service-requests/services-request-status"
        )
    raw = pd.read_parquet(src)
    rename = {
        "Project ID": "project_id",
        "Status": "status_raw",
        "State": "state",
        "County": "county",
        "Transmission Owner": "utility",
        "Fuel": "resource_type",
        "MW Energy": "capacity_mw",
        "Project Type": "service_type",
    }
    cols = {k: v for k, v in rename.items() if k in raw.columns}
    df = raw[list(cols)].rename(columns=cols).copy()
    df["capacity_mw"] = pd.to_numeric(df.capacity_mw, errors="coerce")
    df["region"] = "PJM"
    return df.reset_index(drop=True)


def coverage_report(df: pd.DataFrame) -> pd.DataFrame:
    """Per-column non-null coverage.

    Worth printing before any analysis. The uneven date coverage in this
    dataset is the main thing that makes naive statistics wrong.
    """
    rows = [
        {
            "column": col,
            "non_null": int(df[col].notna().sum()),
            "coverage_pct": round(100 * df[col].notna().mean(), 1),
        }
        for col in df.columns
    ]
    return pd.DataFrame(rows).sort_values("coverage_pct")
