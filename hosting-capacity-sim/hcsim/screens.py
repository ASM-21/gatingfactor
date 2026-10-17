"""Interconnection screens, and how they map to real utility practice.

Five screens are evaluated. The first three are physics, evaluated from the
solved power flow. The last two are the paper screens that a Fast Track or
Supplemental Review application actually gets measured against, evaluated from
nameplate ratios without needing a solution at all.

    voltage        Max steady-state bus voltage within ANSI C84.1 Range A
                   (1.05 pu). This is the binding constraint on long lightly
                   loaded feeders.

    thermal        No line loaded above 100% of conductor ampacity.

    reverse_power  No net export through the substation transformer back to
                   transmission. Many utilities treat station-level reverse
                   flow as an automatic study trigger because it affects
                   relay coordination and LTC control.

    penetration_15 Aggregate DER nameplate <= 15% of line section peak load.
                   This is the classic FERC SGIP Fast Track screen (the "15%
                   of peak load" screen). Failing it does not forbid the
                   project, it kicks it out of Fast Track and into
                   Supplemental Review.

    min_daytime    Aggregate DER nameplate <= 100% of minimum daytime load.
                   This is the Supplemental Review penetration test. It is the
                   more physically meaningful of the two paper screens, since
                   minimum daytime load is what actually determines whether the
                   circuit backfeeds.

Screens are reported independently rather than collapsed to a single pass/fail,
because which screen binds is the interesting engineering result. A feeder that
fails only ``penetration_15`` is a very different conversation than one that
fails ``thermal``.
"""

from __future__ import annotations

from dataclasses import dataclass

ANSI_RANGE_A_MAX = 1.05
ANSI_RANGE_A_MIN = 0.95
THERMAL_LIMIT_PCT = 100.0
FAST_TRACK_PENETRATION = 0.15


@dataclass
class ScreenResult:
    """Outcome of every screen at one DER penetration level."""

    der_mw: float
    max_vm_pu: float
    min_vm_pu: float
    max_line_loading_pct: float
    substation_p_mw: float
    peak_load_mw: float
    min_daytime_load_mw: float

    @property
    def voltage_ok(self) -> bool:
        return self.max_vm_pu <= ANSI_RANGE_A_MAX and self.min_vm_pu >= ANSI_RANGE_A_MIN

    @property
    def thermal_ok(self) -> bool:
        return self.max_line_loading_pct <= THERMAL_LIMIT_PCT

    @property
    def reverse_power_ok(self) -> bool:
        # pandapower ext_grid p_mw is positive when the grid supplies the feeder.
        return self.substation_p_mw >= 0.0

    @property
    def penetration_15_ok(self) -> bool:
        return self.der_mw <= FAST_TRACK_PENETRATION * self.peak_load_mw

    @property
    def min_daytime_ok(self) -> bool:
        return self.der_mw <= self.min_daytime_load_mw

    def as_dict(self) -> dict[str, bool]:
        return {
            "voltage": self.voltage_ok,
            "thermal": self.thermal_ok,
            "reverse_power": self.reverse_power_ok,
            "penetration_15": self.penetration_15_ok,
            "min_daytime": self.min_daytime_ok,
        }

    @property
    def all_ok(self) -> bool:
        return all(self.as_dict().values())

    @property
    def binding(self) -> list[str]:
        """Screens currently violated, in the order they are reported."""
        return [name for name, ok in self.as_dict().items() if not ok]


# Screen taxonomy. This split matters and is easy to get wrong.
#
# PHYSICAL_SCREENS are true equipment limits: exceed them and something is out
# of spec regardless of anyone's tariff. "Hosting capacity" as the term is used
# on published utility hosting capacity maps means the voltage- and
# thermal-limited value, and that is what this repo reports as the headline
# number.
#
# OPERATIONAL_SCREENS flag conditions that trigger further study but are not
# themselves equipment violations. Substation reverse power is the important
# one, and it is deliberately NOT bundled into the headline number: on a radial
# feeder net export begins at almost exactly the point where DER exceeds feeder
# load, so folding it in would force every feeder's hosting capacity to equal
# its minimum daytime load and would hide the voltage and thermal behavior this
# model exists to study.
#
# PAPER_SCREENS are administrative thresholds. Failing one routes an
# application from Fast Track into Supplemental Review; it does not make the
# interconnection infeasible.
PHYSICAL_SCREENS = ("voltage", "thermal")
OPERATIONAL_SCREENS = ("reverse_power",)
PAPER_SCREENS = ("penetration_15", "min_daytime")
ALL_SCREENS = PHYSICAL_SCREENS + OPERATIONAL_SCREENS + PAPER_SCREENS


def evaluate(net, der_mw: float, peak_load_mw: float, min_daytime_load_mw: float) -> ScreenResult:
    """Read a solved pandapower net and score it against every screen."""
    return ScreenResult(
        der_mw=der_mw,
        max_vm_pu=float(net.res_bus["vm_pu"].max()),
        min_vm_pu=float(net.res_bus["vm_pu"].min()),
        max_line_loading_pct=float(net.res_line["loading_percent"].max()),
        substation_p_mw=float(net.res_ext_grid["p_mw"].iloc[0]),
        peak_load_mw=peak_load_mw,
        min_daytime_load_mw=min_daytime_load_mw,
    )


def passes(result: ScreenResult, screens: tuple[str, ...] = PHYSICAL_SCREENS) -> bool:
    """True if the named subset of screens all pass."""
    scored = result.as_dict()
    return all(scored[name] for name in screens)
