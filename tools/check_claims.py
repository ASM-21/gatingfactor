#!/usr/bin/env python3
"""Pair every quoted figure in the prose with code that recomputes it.

Why this exists: a claim that lives only in README prose cannot fail. Nothing
breaks when it stops being true. In a sibling repo a headline claim was
falsified by later work and the stale sentence sat in the README untouched,
because no test covered English. This script makes prose a build artifact.

Three kinds of check, all fatal:

1. FIGURES. Each entry in CLAIMS names a README, the exact substring that must
   appear in it, and a function that recomputes that number from the committed
   results. If the recomputed value drifts outside tolerance, or the substring
   is no longer in the file, the build fails. Changing a number in the prose
   without rerunning the pipeline fails. Changing the pipeline without
   updating the prose also fails.

2. REQUIRED TEXT. Caveats and disclaimers that must not be deleted. Checked
   against whitespace-normalized text, because these are wrapped markdown
   blockquotes whose phrases span line breaks and "> " prefixes; a raw
   substring check silently never matches.

3. FORBIDDEN TEXT. Overclaiming language that the scope of this work does not
   support. Also checked against normalized text: an earlier version of this
   guard in a sibling repo scanned line by line, so any forbidden phrase that
   happened to wrap across a newline was never caught.

Run: python tools/check_claims.py
Exit 0 if every claim holds, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"


def normalize(text: str) -> str:
    """Collapse all whitespace and strip markdown blockquote prefixes.

    Both of this guard's historical bugs came from skipping this step: a
    wrapped blockquote phrase never matched a raw substring check, and a
    forbidden phrase that happened to wrap across a newline was never caught
    because the scan ran line by line.
    """
    text = re.sub(r"^\s*>\s?", " ", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans.

    Used only for the forbidden-phrase scan, to respect the use/mention
    distinction. This file and the README have to be able to *name* the banned
    phrases in order to document them, and a guard that cannot be documented
    without tripping itself is a guard people will disable. A phrase in
    backticks is being mentioned; a phrase in running prose is being asserted.
    Required-text and figure checks still run against the full text.
    """
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    return text


# --- recomputation from committed results -----------------------------------


def _parquet(track: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / track / f"{name}.parquet")


def _json(track: str, name: str) -> dict:
    return json.loads((OUTPUTS / track / f"{name}.json").read_text())


# track 1
def t1_max_survivorship_ratio() -> float:
    b = _parquet("interconnection-analytics", "survivorship_bias")
    r = b.dropna(subset=["km_median_years"])
    return float((r.km_median_years / r.naive_median_years).max())


def t1_2005_naive() -> float:
    b = _parquet("interconnection-analytics", "survivorship_bias")
    return float(b.loc[b.cohort_start == 2005, "naive_median_years"].iloc[0])


def t1_2005_km() -> float:
    b = _parquet("interconnection-analytics", "survivorship_bias")
    return float(b.loc[b.cohort_start == 2005, "km_median_years"].iloc[0])


def t1_undefined_cohorts() -> float:
    """Cohorts where the KM median does not exist because under half complete."""
    b = _parquet("interconnection-analytics", "survivorship_bias")
    return float(b.km_median_years.isna().sum())


def t1_pjm_withdrawal() -> float:
    g = _parquet("interconnection-analytics", "by_region")
    return float(100 * g.loc[g.region == "PJM", "withdrawal_rate"].iloc[0])


def t1_pjm_completion() -> float:
    g = _parquet("interconnection-analytics", "by_region")
    return float(100 * g.loc[g.region == "PJM", "completion_rate"].iloc[0])


def t1_ppl_projects() -> float:
    return float(_json("interconnection-analytics", "pjm_ppl_summary")["ppl_projects"])


def t1_ppl_withdrawal() -> float:
    return float(100 * _json("interconnection-analytics", "pjm_ppl_summary")["ppl_withdrawal_rate"])


def t1_ppl_completion() -> float:
    return float(100 * _json("interconnection-analytics", "pjm_ppl_summary")["ppl_completion_rate"])


def t1_n_requests() -> float:
    return float(len(_parquet("interconnection-analytics", "resolved")))


# track 2
def _hc_base() -> pd.DataFrame:
    h = _parquet("hosting-capacity-sim", "hosting_capacity_results")
    return h[(h.strategy == "distributed") & (~h.volt_var)]


def _ft_ratio(feeder: str) -> float:
    b = _hc_base()
    row = b[b.feeder == feeder].iloc[0]
    return float(row.hosting_capacity_mw / row.limit_penetration_15_mw)


def t2_rural_ratio() -> float:
    return _ft_ratio("rural")


def t2_urban_ratio() -> float:
    return _ft_ratio("urban")


def _vv_uplift(feeder: str) -> float:
    h = _parquet("hosting-capacity-sim", "hosting_capacity_results")
    sel = h[(h.feeder == feeder) & (h.strategy == "distributed")]
    off = float(sel[~sel.volt_var].hosting_capacity_mw.iloc[0])
    on = float(sel[sel.volt_var].hosting_capacity_mw.iloc[0])
    return on / off


def t2_suburban_vv() -> float:
    return _vv_uplift("suburban")


def t2_urban_vv() -> float:
    return _vv_uplift("urban")


def _sizing() -> pd.DataFrame:
    return _parquet("hosting-capacity-sim", "inverter_sizing")


def t2_max_uplift_at_exact_sizing() -> float:
    """At S/P = 1.00 volt-var must be exactly inert on every feeder."""
    z = _sizing()
    z = z[np.isclose(z.inverter_oversize, 1.0)]
    return float(z.uplift.abs().max())


def t2_min_uplift_at_exact_sizing() -> float:
    z = _sizing()
    z = z[np.isclose(z.inverter_oversize, 1.0)]
    return float(z.uplift.min())


def t2_suburban_uplift_at_1_02() -> float:
    z = _sizing()
    row = z[(z.feeder == "suburban") & np.isclose(z.inverter_oversize, 1.02)]
    return float(row.uplift.iloc[0])


def t2_category_b_min_oversize() -> float:
    z = _sizing()
    return float(z[z.is_category_b_min].inverter_oversize.iloc[0])


def t2_sizing_matches_results() -> float:
    """The sizing stage and results stage must agree at the Category B point.

    They ran with different tolerances once and reported 1.255x and 1.243x for
    the same configuration. Returns the worst disagreement, which must be ~0.
    """
    z = _sizing()
    z = z[z.is_category_b_min].set_index("feeder").uplift
    worst = 0.0
    for feeder in z.index:
        worst = max(worst, abs(z[feeder] - _vv_uplift(feeder)))
    return float(worst)


def t2_inverter_overshoot() -> float:
    """How far any inverter at any hosting capacity limit exceeds its kVA rating.

    Must be exactly zero. The retracted volt-var result had this at 0.024.
    """
    return float(max(0.0, _sizing().max_s_utilization.max() - 1.0))


def t2_rural_siting_spread() -> float:
    h = _parquet("hosting-capacity-sim", "hosting_capacity_results")
    s = h[(h.feeder == "rural") & (~h.volt_var)]
    return float(s.hosting_capacity_mw.max() / s.hosting_capacity_mw.min())


# track 3
def _rn() -> pd.DataFrame:
    return _parquet("tariff-explorer", "revenue_neutral")


def _rn_change(archetype: str, tariff: str) -> float:
    r = _rn()
    return float(r[(r.archetype == archetype) & (r.tariff == tariff)].change_pct.iloc[0])


def t3_solar_tou() -> float:
    return _rn_change("solar_home", "tou")


def t3_solar_demand() -> float:
    return _rn_change("solar_home", "demand")


def t3_solar_swing() -> float:
    return t3_solar_demand() - t3_solar_tou()


def t3_solar_energy_offset() -> float:
    a = _parquet("tariff-explorer", "archetype_summary")
    s = a[a.archetype == "solar_home"].iloc[0]
    return float(100 * (1 - s.net_annual_kwh / s.annual_kwh))


def t3_load_factor_corr() -> float:
    d = _rn()
    d = d[d.tariff == "demand"]
    return float(np.corrcoef(d.load_factor, d.change_pct)[0, 1])


def t3_ev_demand() -> float:
    return _rn_change("ev_home", "demand")


# track 6
def _sig() -> dict:
    return _json("carbon-aware-der", "signal_comparison")


def t6_profile_corr() -> float:
    return float(_sig()["profile_correlation"])


def t6_strength_ratio() -> float:
    return float(_sig()["signal_strength_ratio"])


def t6_flip_days() -> float:
    return float(_sig()["helps_avg_but_hurts_marginal"])


def t6_total_days() -> float:
    return float(_sig()["days"])


def t6_pooled_mef() -> float:
    return float(_sig()["pooled_mef_kg_per_mwh"])


def t6_r2_controlled() -> float:
    return float(_sig()["pooled_r2"])


def t6_r2_uncontrolled() -> float:
    return float(_sig()["pooled_r2_uncontrolled"])


def _strategy_change(strategy: str, column: str) -> float:
    s = _parquet("carbon-aware-der", "signal_choice")
    t = s.groupby("strategy")[["cost", "avg_carbon_kg", "marginal_carbon_kg"]].sum()
    base = t.loc["unmanaged", column]
    return float(100 * (t.loc[strategy, column] - base) / base)


def t6_avg_on_avg() -> float:
    return _strategy_change("avg_signal", "avg_carbon_kg")


def t6_avg_on_marginal() -> float:
    return _strategy_change("avg_signal", "marginal_carbon_kg")


def t6_marginal_on_marginal() -> float:
    return _strategy_change("marginal_signal", "marginal_carbon_kg")


def t6_marginal_cost() -> float:
    return _strategy_change("marginal_signal", "cost")


def t6_abatement_per_tonne() -> float:
    s = _parquet("carbon-aware-der", "signal_choice")
    t = s.groupby("strategy")[["cost", "marginal_carbon_kg"]].sum()
    c, m = t.loc["cost"], t.loc["marginal_signal"]
    return float(1000 * (m.cost - c.cost) / (c.marginal_carbon_kg - m.marginal_carbon_kg))


# --- claim table ------------------------------------------------------------


@dataclass
class Claim:
    readme: str
    quoted: str
    compute: Callable[[], float]
    expected: float
    tol: float = 0.02
    note: str = ""


R_ROOT = "README.md"
R_T1 = "interconnection-analytics/README.md"
R_T2 = "hosting-capacity-sim/README.md"
R_T3 = "tariff-explorer/README.md"
R_T6 = "carbon-aware-der/README.md"
R_FIND = "FINDINGS.md"

CLAIMS: list[Claim] = [
    # --- track 1 ---
    Claim(R_T1, "5.2x", t1_max_survivorship_ratio, 5.244, 0.05),
    Claim(R_T1, "2.87 yr", t1_2005_naive, 2.872, 0.01),
    Claim(R_T1, "15.06 yr", t1_2005_km, 15.061, 0.01),
    Claim(R_T1, "36,441", t1_n_requests, 36441, 0.0),
    Claim(R_T1, "68.0%", t1_pjm_withdrawal, 67.97, 0.05),
    Claim(R_T1, "23.8%", t1_pjm_completion, 23.79, 0.05),
    Claim(R_T1, "470 requests", t1_ppl_projects, 470, 0.0),
    Claim(R_T1, "67.7%", t1_ppl_withdrawal, 67.66, 0.05),
    Claim(R_T1, "15.5%", t1_ppl_completion, 15.53, 0.05),
    Claim(R_FIND, "5.2x", t1_max_survivorship_ratio, 5.244, 0.05),
    Claim(R_ROOT, "5.2x", t1_max_survivorship_ratio, 5.244, 0.05),
    # --- track 2 ---
    Claim(R_T2, "5.7x", t2_rural_ratio, 5.66, 0.05),
    Claim(R_T2, "17.1x", t2_urban_ratio, 17.11, 0.05),
    Claim(R_T2, "2.64x", t2_suburban_vv, 2.635, 0.01),
    Claim(R_T2, "0.99x", t2_urban_vv, 0.989, 0.01),
    Claim(R_T2, "exactly 1.00x", t2_max_uplift_at_exact_sizing, 1.0, 1e-9),
    Claim(R_T2, "exactly 1.00x", t2_min_uplift_at_exact_sizing, 1.0, 1e-9),
    Claim(R_T2, "2.30x", t2_suburban_uplift_at_1_02, 2.301, 0.01),
    Claim(R_T2, "1.1136", t2_category_b_min_oversize, 1.11359, 1e-4),
    Claim(R_T2, "2.64x", t2_sizing_matches_results, 0.0, 1e-6),
    Claim(R_T2, "no inverter ever exceeds its rating", t2_inverter_overshoot, 0.0, 1e-9),
    Claim(R_FIND, "2.64x", t2_suburban_vv, 2.635, 0.01),
    Claim(R_FIND, "0.99x", t2_urban_vv, 0.989, 0.01),
    Claim(R_FIND, "1.00x", t2_max_uplift_at_exact_sizing, 1.0, 1e-9),
    Claim(R_FIND, "2.30x", t2_suburban_uplift_at_1_02, 2.301, 0.01),
    Claim(R_ROOT, "2.64x", t2_suburban_vv, 2.635, 0.01),
    Claim(R_ROOT, "0.99x", t2_urban_vv, 0.989, 0.01),
    Claim(R_ROOT, "1.00x", t2_max_uplift_at_exact_sizing, 1.0, 1e-9),
    Claim(R_T2, "3.35x", t2_rural_siting_spread, 3.349, 0.01),
    Claim(R_FIND, "17.1x", t2_urban_ratio, 17.11, 0.05),
    Claim(R_ROOT, "17.1x", t2_urban_ratio, 17.11, 0.05),
    # --- track 3 ---
    Claim(R_T3, "-32.6%", t3_solar_tou, -32.60, 0.05),
    Claim(R_T3, "+36.2%", t3_solar_demand, 36.24, 0.05),
    Claim(R_T3, "69 percentage point", t3_solar_swing, 68.84, 1.0),
    Claim(R_T3, "83.3%", t3_solar_energy_offset, 83.33, 0.05),
    Claim(R_T3, "r = -0.59", t3_load_factor_corr, -0.594, 0.01),
    Claim(R_T3, "+28.8%", t3_ev_demand, 28.76, 0.05),
    Claim(R_FIND, "+36.2%", t3_solar_demand, 36.24, 0.05),
    Claim(R_ROOT, "-32.6%", t3_solar_tou, -32.60, 0.05),
    # --- track 6 ---
    Claim(R_T6, "r = -0.66", t6_profile_corr, -0.658, 0.01),
    Claim(R_T6, "4.1x", t6_strength_ratio, 4.114, 0.05),
    Claim(R_T6, "359 of 364", t6_flip_days, 359, 0.0),
    Claim(R_T6, "437.8", t6_pooled_mef, 437.84, 0.1),
    Claim(R_T6, "0.878 to 0.937", t6_r2_controlled, 0.9365, 0.001),
    Claim(R_T6, "0.878 to 0.937", t6_r2_uncontrolled, 0.8785, 0.001),
    Claim(R_T6, "-2.9%", t6_avg_on_avg, -2.94, 0.05),
    Claim(R_T6, "+10.5%", t6_avg_on_marginal, 10.54, 0.05),
    Claim(R_T6, "-6.7%", t6_marginal_on_marginal, -6.71, 0.05),
    Claim(R_T6, "4.8% less", t6_marginal_cost, -4.75, 0.05),
    Claim(R_T6, "$713/tonne", t6_abatement_per_tonne, 713, 2.0),
    Claim(R_FIND, "+10.5%", t6_avg_on_marginal, 10.54, 0.05),
    Claim(R_ROOT, "10.5%", t6_avg_on_marginal, 10.54, 0.05),
]


# --- required and forbidden prose -------------------------------------------

DISCLAIMER_PHRASES = [
    "independent personal project",
    "not affiliated with, reviewed by, or endorsed by any employer",
    "public data and synthetic models only",
    "No non-public, proprietary, customer, or utility-internal data",
    "not produced on employer time or systems",
]

REQUIRED_TEXT: list[tuple[str, str, str]] = [
    # (file, required phrase, why it must not be deleted)
    (R_ROOT, "independent personal project", "employer-independence disclaimer"),
    (R_T3, "Synthetic", "track 3 load shapes are synthetic, not measured"),
    (R_T3, "not filed tariffs", "track 3 rate levels are representative, not filed"),
    (R_T2, "not calibrated to any real circuit", "track 2 feeders are synthetic"),
    (R_T2, "never enforced that constraint", "track 2 volt-var correction must stay visible"),
    (R_T2, "Category B minimum", "volt-var figures are meaningless without their sizing"),
    (R_FIND, "Track 2: volt-var gives 2.41x", "retraction of the track 2 volt-var figure"),
    (R_FIND, "Track 6: the average carbon signal", "retraction of the track 6 signal claim"),
    (R_T6, "regression estimate", "track 6 marginal factors are estimated, not measured"),
    (R_T1, "conditioned on success", "the survivorship mechanism must stay stated"),
    (R_T1, "Berkeley Lab", "LBNL data attribution"),
    (R_T6, "CarbonCast", "CarbonCast data attribution"),
]

# Scope language this work does not support. "proves" / "always" are the
# failure mode a bounded result invites; novelty claims are the failure mode a
# literature search would puncture.
FORBIDDEN_TEXT: list[tuple[str, str]] = [
    ("proves that", "no result here is a proof; they are bounded empirical findings"),
    ("in every grid", "track 6 covers PJM only; the 13-region test lives in another repo"),
    ("for the first time", "novelty claim; prior art exists for all four tracks"),
    ("we discovered", "novelty claim"),
    ("novel finding", "novelty claim"),
    ("guaranteed", "no guarantee is established by any track"),
    ("always conservative", "track 2 covers three archetypes, not a population"),
]


# --- runner -----------------------------------------------------------------


def run() -> int:
    failures: list[str] = []
    checked = 0

    cache: dict[str, str] = {}

    def text_of(rel: str) -> str:
        if rel not in cache:
            path = ROOT / rel
            if not path.exists():
                raise FileNotFoundError(rel)
            cache[rel] = path.read_text()
        return cache[rel]

    # 1. figures
    for claim in CLAIMS:
        checked += 1
        try:
            prose = normalize(text_of(claim.readme))
        except FileNotFoundError:
            failures.append(f"MISSING FILE {claim.readme}")
            continue

        if normalize(claim.quoted) not in prose:
            failures.append(
                f"{claim.readme}: quoted figure {claim.quoted!r} no longer appears in the prose"
            )
            continue

        try:
            actual = claim.compute()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{claim.readme}: could not recompute {claim.quoted!r}: {exc}")
            continue

        if abs(actual - claim.expected) > claim.tol:
            failures.append(
                f"{claim.readme}: {claim.quoted!r} drifted. "
                f"prose pins {claim.expected}, results now give {actual:.4f} "
                f"(tolerance {claim.tol})"
            )

    # 2. required text
    for rel, phrase, why in REQUIRED_TEXT:
        checked += 1
        try:
            prose = normalize(text_of(rel))
        except FileNotFoundError:
            failures.append(f"MISSING FILE {rel}")
            continue
        if normalize(phrase).lower() not in prose.lower():
            failures.append(f"{rel}: required text deleted ({why}): {phrase!r}")

    # The disclaimer is checked phrase by phrase so a partial deletion is caught.
    for phrase in DISCLAIMER_PHRASES:
        checked += 1
        prose = normalize(text_of(R_ROOT))
        if normalize(phrase).lower() not in prose.lower():
            failures.append(f"{R_ROOT}: disclaimer phrase deleted: {phrase!r}")

    # 3. forbidden text, across every markdown file in the repo
    for md in sorted(ROOT.rglob("*.md")):
        if any(part in {".git", "node_modules", ".venv"} for part in md.parts):
            continue
        prose = normalize(strip_code(md.read_text())).lower()
        rel = md.relative_to(ROOT).as_posix()
        for phrase, why in FORBIDDEN_TEXT:
            checked += 1
            if phrase.lower() in prose:
                failures.append(f"{rel}: overclaiming phrase {phrase!r} ({why})")

    if failures:
        print(f"FAILED: {len(failures)} problem(s) across {checked} checks\n")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"OK: {checked} checks passed ({len(CLAIMS)} figures recomputed from results)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
