"""Interactive tariff explorer.

    streamlit run app.py

Adjust rate parameters and watch bill impacts move across all five archetypes
at once. The revenue-neutrality toggle is the important control: with it off
you are mostly measuring which structure happens to have higher rates written
into it, and with it on you are measuring how the structure *allocates* cost,
which is the thing rate design actually argues about.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from texplorer import archetypes as ar, tariffs as tf  # noqa: E402

st.set_page_config(page_title="gatingfactor tariff explorer", layout="wide")
st.title("Tariff rate design explorer")
st.caption(
    "Synthetic archetype load shapes and representative rate levels. "
    "Useful for comparing structures against each other, not for quoting bills."
)


@st.cache_data
def _archetypes(year: int = 2021):
    return ar.build_archetypes(year)


archetypes = _archetypes()

with st.sidebar:
    st.header("Rate parameters")

    st.subheader("Common")
    fixed = st.number_input("Fixed monthly charge ($)", 0.0, 60.0, 12.0, 1.0)
    minimum = st.number_input("Minimum monthly bill ($)", 0.0, 100.0, 0.0, 5.0)
    nem = st.checkbox("Full-retail net metering", value=True)
    export_rate = None if nem else st.number_input(
        "Export credit ($/kWh)", 0.0, 0.30, 0.04, 0.01
    )

    st.subheader("Flat")
    flat_rate = st.slider("Flat rate ($/kWh)", 0.05, 0.35, 0.155, 0.005)

    st.subheader("Tiered (monthly blocks)")
    t1_kwh = st.slider("Tier 1 limit (kWh/mo)", 100, 1500, 500, 50)
    t2_kwh = st.slider("Tier 2 limit (kWh/mo)", int(t1_kwh) + 50, 3000, 1000, 50)
    t1 = st.slider("Tier 1 rate", 0.05, 0.30, 0.125, 0.005)
    t2 = st.slider("Tier 2 rate", 0.05, 0.35, 0.165, 0.005)
    t3 = st.slider("Tier 3 rate", 0.05, 0.45, 0.205, 0.005)

    st.subheader("Time of use")
    on_peak = st.slider("On-peak ($/kWh)", 0.05, 0.60, 0.240, 0.005)
    mid_peak = st.slider("Mid-peak ($/kWh)", 0.03, 0.40, 0.150, 0.005)
    off_peak = st.slider("Off-peak ($/kWh)", 0.01, 0.25, 0.090, 0.005)
    on_start, on_end = st.slider("On-peak window (hour)", 0, 23, (14, 19))

    st.subheader("Demand charge")
    demand_energy = st.slider("Energy rate ($/kWh)", 0.02, 0.25, 0.095, 0.005)
    demand_rate = st.slider("Demand charge ($/kW-month)", 0.0, 40.0, 12.0, 0.5)

    st.subheader("Analysis")
    revenue_neutral = st.checkbox("Hold revenue constant within class", value=True)

common = dict(
    fixed_monthly=fixed, minimum_monthly=minimum, export_rate=export_rate
)
on_hours = tuple(range(int(on_start), int(on_end) + 1))

tariff_list = (
    tf.FlatRate(rate=flat_rate, **common),
    tf.TieredRate(
        tiers=[(float(t1_kwh), t1), (float(t2_kwh), t2), (float("inf"), t3)], **common
    ),
    tf.TOURate(
        on_peak=on_peak, mid_peak=mid_peak, off_peak=off_peak,
        on_peak_hours=on_hours, **common,
    ),
    tf.DemandChargeRate(rate=demand_energy, demand_rate_per_kw=demand_rate,
                        **{k: v for k, v in common.items()}),
    tf.HybridTOUDemand(
        on_peak=on_peak * 0.75, mid_peak=mid_peak * 0.77, off_peak=off_peak * 0.78,
        on_peak_hours=on_hours, demand_rate_per_kw=demand_rate * 0.67, **common,
    ),
)

CLASSES = {
    "residential": ("all_electric", "ev_home", "solar_home"),
    "commercial": ("commercial_daytime", "commercial_flat"),
}

if revenue_neutral:
    frames = []
    for cls, keys in CLASSES.items():
        subset = {k: archetypes[k] for k in keys}
        frames.append(ar.revenue_neutral_comparison(subset, tariff_list))
    result = pd.concat(frames, ignore_index=True)
    value_col, fmt = "change_pct", "{:+.1f}%"
    caption = "Bill change vs flat rate, holding total revenue constant within class"
else:
    result = ar.bill_matrix(archetypes, tariff_list)
    value_col, fmt = "annual_bill", "${:,.0f}"
    caption = "Annual bill at the rates as entered"

st.subheader(caption)
pivot = result.pivot(index="archetype", columns="tariff", values=value_col)
lf = pd.Series({k: a.load_factor for k, a in archetypes.items()})
pivot.insert(0, "load_factor", lf)
st.dataframe(
    pivot.sort_values("load_factor").style.format({**{c: fmt for c in pivot.columns if c != "load_factor"},
                                                   "load_factor": "{:.2f}"}),
    width="stretch",
)

col1, col2 = st.columns(2)
with col1:
    st.subheader("Archetype detail")
    for a in archetypes.values():
        st.write(
            f"**{a.label}** — {a.annual_kwh:,.0f} kWh/yr, "
            f"net {a.net_annual_kwh:,.0f} kWh, peak {a.peak_kw:.1f} kW, "
            f"load factor {a.load_factor:.2f}"
        )
with col2:
    if revenue_neutral:
        st.subheader("Revenue-neutral scale factors")
        st.dataframe(
            result.groupby("tariff").scale.first().round(4),
            width="stretch",
        )

st.info(
    "Two effects dominate this table. A demand charge prices load factor, so peaky "
    "customers pay more regardless of how much energy they use. TOU prices timing, so "
    "a solar customer benefits sharply because generation lands in the on-peak window. "
    "A solar customer facing a demand charge gets neither benefit, since PV cuts energy "
    "but barely touches an evening peak that occurs after sunset."
)
