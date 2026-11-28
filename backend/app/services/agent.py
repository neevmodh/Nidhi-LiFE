"""The energy agent: reads the household's live meter, plans, and says what to do next.

It works in steps, each a small tool that returns numbers computed here from the meter and the tariff
(never by a model): read the meter, profile the last week, price the tariff slab, reconcile the bill, rank
the actions. The ranking is deterministic, by rupees then CO2. An AI model may turn the final numbers
into a friendlier summary, but, as with the coach (services/coach.py), its text is only used when every
number in it is one of the numbers it was given. With no AI key the summary is the plain template.
"""

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.config import get_settings
from app.i18n import tr
from app.models import Meter, User
from app.services import factors, meter_sim
from app.services import meter as meter_svc
from app.services.coach import LANGUAGE, ask_llm, numbers_ok
from app.services.impact import action_impact
from app.services.plan import marginal_rate
from app.timeutil import IST, as_utc

log = logging.getLogger(__name__)

PEAK = factors.PEAK_HOURS
SOLAR = factors.SOLAR_HOURS
MISMATCH_PCT = 25  # a bill this far from the meter is worth a complaint
HEAVY_USES_PER_MONTH = 20
CONFIRM_KW = 0.6  # extra load above the usual that counts as "an appliance ran"


@dataclass
class Step:
    tool: str
    key: str
    params: dict


@dataclass
class Recommendation:
    key: str
    params: dict
    rs_month: float
    co2_kg_month: float
    action_code: str | None = None  # the Nidhi action it earns points as, if any
    meter_confirmable: bool = False  # the meter can confirm it was done


@dataclass
class Report:
    facts: dict
    steps: list[Step] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    mismatch: bool = False


def _ist_hour(ts: datetime) -> float:
    local = as_utc(ts).astimezone(IST)
    return local.hour + local.minute / 60


def week_profile(db: Session, meter: Meter, now: datetime) -> dict:
    """Average load and PV by IST hour over the last 7 days, and the shares the agent reasons about."""
    rows = meter_svc.readings_between(db, meter, now - timedelta(days=7), now)
    hours = meter_sim.INTERVAL_MIN / 60
    load_h: dict[int, list[float]] = {h: [] for h in range(24)}
    pv_h: dict[int, list[float]] = {h: [] for h in range(24)}
    peak_import = total_import = surplus = 0.0
    night: list[float] = []
    for r in rows:
        h = int(_ist_hour(r.ts - meter_sim.INTERVAL / 2))
        load_h[h].append(r.load_kw)
        pv_h[h].append(r.pv_kw)
        imported = max(r.load_kw - r.pv_kw, 0) * hours
        total_import += imported
        if PEAK[0] <= h < PEAK[1]:
            peak_import += imported
        surplus += max(r.pv_kw - r.load_kw, 0) * hours
        if 1 <= h < 5:
            night.append(r.load_kw)
    days = max(len(rows) * hours / 24, 1e-6)
    return {
        "load_by_hour": {h: round(statistics.fmean(v), 3) if v else 0.0 for h, v in load_h.items()},
        "pv_by_hour": {h: round(statistics.fmean(v), 3) if v else 0.0 for h, v in pv_h.items()},
        "peak_share_pct": round(100 * peak_import / total_import) if total_import else 0,
        "peak_kwh_month": round(peak_import / days * 30, 1),
        "surplus_kwh_day": round(surplus / days, 1),
        "night_base_w": round(1000 * statistics.median(night)) if night else 0,
    }


def marginal_rs(h, kwh: float) -> float:
    """What the next unit costs at this month's projected units."""
    return marginal_rate(SimpleNamespace(discom=h.discom, area=h.area, monthly_kwh=max(kwh, 1.0)))


def analyze(db: Session, user: User, meter: Meter, now: datetime, locale: str = "en") -> Report:
    h = user.household
    steps: list[Step] = []

    last = meter_svc.last_reading(db, meter)
    now_load = last.load_kw if last else 0.0
    now_pv = last.pv_kw if last else 0.0
    steps.append(Step("read_meter", "agent.step.read_meter", {"load": round(now_load, 2), "pv": round(now_pv, 2)}))

    week = week_profile(db, meter, now)
    steps.append(
        Step("profile_week", "agent.step.profile_week",
             {"peak": week["peak_share_pct"], "surplus": week["surplus_kwh_day"], "night": week["night_base_w"]})
    )

    month = meter_svc.month_summary(db, meter, h)
    rate = marginal_rs(h, month["projected_import_kwh"])
    steps.append(Step("price_tariff", "agent.step.price_tariff",
                      {"kwh": month["projected_import_kwh"], "rate": rate, "bill": round(month["projected_bill_rs"])}))

    stated = meter_svc.billed_kwh(db, user)
    diff_pct = round(100 * (month["projected_load_kwh"] - stated) / stated) if stated else 0
    mismatch = abs(diff_pct) >= MISMATCH_PCT
    steps.append(Step("reconcile_bill", "agent.step.reconcile", {"meter": month["projected_load_kwh"], "stated": stated, "diff": abs(diff_pct)}))

    recs: list[Recommendation] = []
    export_rate = factors.NET_METERING_EXPORT_RS_PER_KWH
    shift = action_impact("shift_heavy_load", h)
    if shift.applicable:
        moved = min(factors.HEAVY_LOAD_KWH[n] for n in factors.HEAVY_LOAD_KWH if _has_heavy(h, n)) * HEAVY_USES_PER_MONTH
        moved = min(moved, week["surplus_kwh_day"] * 30) if meter.pv_kwp > 0 else moved
        rs = round(max(rate - export_rate, 0) * moved) if meter.pv_kwp > 0 else 0
        co2 = round(moved * (factors.GRID_OPERATING_MARGIN_KG_CO2_PER_KWH - factors.GRID_KG_CO2_PER_KWH), 1)
        key = "agent.rec.shift_solar" if meter.pv_kwp > 0 else "agent.rec.shift_offpeak"
        recs.append(Recommendation(key, {"kwh": round(moved), "rs": rs, "co2": co2, "from_h": SOLAR[0], "to_h": SOLAR[1],
                                         "peak_from": PEAK[0], "peak_to": PEAK[1]},
                                   rs, co2, "shift_heavy_load", True))
    if week["peak_share_pct"] >= 40:
        cut = round(0.2 * week["peak_kwh_month"], 1)
        co2 = round(cut * (factors.GRID_OPERATING_MARGIN_KG_CO2_PER_KWH - factors.GRID_KG_CO2_PER_KWH), 1)
        recs.append(Recommendation("agent.rec.cut_peak", {"share": week["peak_share_pct"], "kwh": cut, "co2": co2,
                                                           "peak_from": PEAK[0], "peak_to": PEAK[1]}, 0.0, co2))
    if week["night_base_w"] >= 150:
        standby = action_impact("standby_off", h)
        kwh = round(standby.kwh * 30, 1)
        recs.append(Recommendation("agent.rec.night_base", {"watts": week["night_base_w"], "kwh": kwh, "rs": round(kwh * rate)},
                                   round(kwh * rate), round(standby.co2_kg * 30, 1), "standby_off"))
    ac = action_impact("ac_24", h)
    if ac.applicable:
        kwh = round(ac.kwh * 30, 1)
        recs.append(Recommendation("agent.rec.ac_setpoint", {"kwh": kwh, "rs": round(kwh * rate), "co2": round(ac.co2_kg * 30, 1)},
                                   round(kwh * rate), round(ac.co2_kg * 30, 1), "ac_24"))
    recs.sort(key=lambda r: (-r.rs_month, -r.co2_kg_month))
    recs = recs[:4]
    steps.append(Step("rank_actions", "agent.step.rank", {"n": len(recs)}))

    top = recs[0] if recs else None
    facts = {
        "load_kw": round(now_load, 2),
        "pv_kw": round(now_pv, 2),
        "projected_kwh": month["projected_import_kwh"],
        "projected_bill_rs": round(month["projected_bill_rs"]),
        "rate_rs": rate,
        "peak_share_pct": week["peak_share_pct"],
        "surplus_kwh_day": week["surplus_kwh_day"],
        "saving_rs": top.rs_month if top else 0,
        "saving_co2_kg": top.co2_kg_month if top else 0,
    }
    return Report(facts, steps, recs, mismatch)


def _has_heavy(h, name: str) -> bool:
    return {"washing machine": h.has_washing_machine, "geyser": h.has_geyser, "EV charging": h.has_ev}[name]


def template_summary(report: Report, locale: str) -> str:
    if report.recommendations:
        return tr(locale, "agent.summary", **report.facts)
    return tr(locale, "agent.summary_none", **report.facts)


async def summary(report: Report, locale: str) -> tuple[str, bool]:
    """(text, written_by_ai)."""
    settings = get_settings()
    if not (settings.groq_api_key and settings.enable_external_apis) or not report.recommendations:
        return template_summary(report, locale), False
    prompt = (
        f"Write a warm, two-sentence note in {LANGUAGE.get(locale, 'English')} to a household in Gujarat about what "
        "their smart meter shows and the single best next step. Use ONLY these facts and no other numbers, no "
        "percentages unless given; write numbers with ASCII digits exactly as given:\n"
        + json.dumps(report.facts, ensure_ascii=False)
    )
    try:
        text = await ask_llm(prompt)
    except Exception as exc:  # noqa: BLE001  any provider failure falls back to the template
        log.warning("Agent summary model unavailable: %s", exc)
        return template_summary(report, locale), False
    if text and numbers_ok(text, report.facts):
        return text, True
    log.info("Agent summary rejected: a number not in its input")
    return template_summary(report, locale), False


# --- Meter confirmation -----------------------------------------------------------

def confirm_shift(db: Session, meter: Meter, now: datetime) -> float:
    """kWh of load the meter shows outside the evening peak in the last 3 hours that was well above
    that time of day's usual level (the median of the previous 7 days). 0 when it sees nothing."""
    recent = meter_svc.readings_between(db, meter, now - timedelta(hours=3), now)
    history = meter_svc.readings_between(db, meter, now - timedelta(days=8), now - timedelta(hours=3))
    usual: dict[tuple[int, int], list[float]] = {}
    for r in history:
        t = as_utc(r.ts).astimezone(IST)
        usual.setdefault((t.hour, t.minute // 15), []).append(r.load_kw)
    extra = 0.0
    for r in recent:
        t = as_utc(r.ts).astimezone(IST)
        if PEAK[0] <= t.hour < PEAK[1]:
            continue
        base = statistics.median(usual.get((t.hour, t.minute // 15), [r.load_kw]))
        if r.load_kw - base >= CONFIRM_KW:
            extra += (r.load_kw - base) * meter_sim.INTERVAL_MIN / 60
    return round(extra, 2)
