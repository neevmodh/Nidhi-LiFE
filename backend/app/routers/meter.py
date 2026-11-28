"""Smart meter: live usage, the meter-derived bill, the energy agent, and signed ingest from real meters.

A household without a real meter gets a simulated one (services/meter_sim.py), labelled as such in every
response (`simulated`). A real meter posts signed readings to POST /api/meter/readings.
"""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession
from app.i18n import RequestLocale, tr
from app.models import (
    ActionLog,
    ActionStatus,
    ActionType,
    Meter,
    MeterFlag,
    MeterReading,
    User,
)
from app.routers.actions import daily_challenge_for, log_out
from app.schemas import ActionLogOut, UtcDatetime
from app.services import agent as agent_svc
from app.services import factors, meter_ingest, meter_sim
from app.services import meter as svc
from app.services.bill_xray import xray
from app.services.gamification import points_for
from app.services.impact import action_impact
from app.timeutil import as_utc, ist_day_bounds_utc, today_ist

router = APIRouter(prefix="/api/meter", tags=["meter"])

KINDS = Literal["washing_machine", "geyser", "ev_charger"]


class MeterOut(BaseModel):
    serial: str
    source: str
    simulated: bool  # the app shows a "simulated meter" badge when true
    discom: str
    feeder: str
    pv_kwp: float
    sanctioned_load_kw: float


class Point(BaseModel):
    ts: UtcDatetime
    load_kw: float
    pv_kw: float


class Today(BaseModel):
    import_kwh: float
    export_kwh: float
    load_kwh: float
    solar_share_pct: int
    co2_kg: float


class LiveOut(BaseModel):
    meter: MeterOut
    ts: UtcDatetime | None
    load_kw: float
    pv_kw: float
    grid_kw: float  # positive drawing from the grid, negative sending to it
    today: Today
    series: list[Point]
    peak_hours: tuple[int, int]
    solar_hours: tuple[int, int]
    outages: list["OutageOut"]


class OutageOut(BaseModel):
    id: int
    feeder: str
    reason: str
    starts_at: UtcDatetime
    ends_at: UtcDatetime


def _meter(db, user: User) -> Meter:
    meter = svc.ensure_meter(db, user)
    if meter is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Complete onboarding first")
    svc.catch_up(db, meter, user)
    return meter


def _meter_out(m: Meter) -> MeterOut:
    return MeterOut(serial=m.serial, source=m.source, simulated=m.source == "simulated", discom=m.discom,
                    feeder=m.feeder, pv_kwp=m.pv_kwp, sanctioned_load_kw=m.sanctioned_load_kw)


def _points(rows: list[MeterReading]) -> list[Point]:
    return [Point(ts=r.ts, load_kw=r.load_kw, pv_kw=r.pv_kw) for r in rows]


@router.get("", response_model=MeterOut)
def my_meter(user: CurrentUser, db: DbSession):
    return _meter_out(_meter(db, user))


@router.get("/live", response_model=LiveOut)
def live(user: CurrentUser, db: DbSession):
    from app.models import Outage

    meter = _meter(db, user)
    now = datetime.now(UTC)
    last = svc.last_reading(db, meter)
    start, end = ist_day_bounds_utc(today_ist())
    imp, exp = svc.usage_between(db, meter, start, end)
    load = svc.load_between(db, meter, start, end)
    series = svc.readings_between(db, meter, now - timedelta(hours=24), now)
    outages = db.scalars(
        select(Outage).where(Outage.discom == meter.discom, Outage.feeder == meter.feeder, Outage.ends_at > now)
        .order_by(Outage.starts_at)
    ).all()
    return LiveOut(
        meter=_meter_out(meter),
        ts=last.ts if last else None,
        load_kw=last.load_kw if last else 0.0,
        pv_kw=last.pv_kw if last else 0.0,
        grid_kw=round((last.load_kw - last.pv_kw) if last else 0.0, 3),
        today=Today(import_kwh=imp, export_kwh=exp, load_kwh=load,
                    solar_share_pct=round(100 * svc.solar_share(load, imp)),
                    co2_kg=round(imp * factors.GRID_KG_CO2_PER_KWH, 1)),
        series=_points(series),
        peak_hours=factors.PEAK_HOURS,
        solar_hours=factors.SOLAR_HOURS,
        outages=[OutageOut(id=o.id, feeder=o.feeder, reason=o.reason, starts_at=o.starts_at, ends_at=o.ends_at)
                 for o in outages],
    )


@router.get("/day", response_model=list[Point])
def day(user: CurrentUser, db: DbSession, on: Annotated[date | None, Query(alias="date")] = None):
    meter = _meter(db, user)
    start, end = ist_day_bounds_utc(on or today_ist())
    return _points(svc.readings_between(db, meter, start, end))


class BillOut(BaseModel):
    month: str
    simulated: bool
    import_kwh: float
    export_kwh: float
    load_kwh: float
    projected_import_kwh: float
    projected_export_kwh: float
    projected_load_kwh: float
    projected_bill_rs: float
    net_metering_credit_rs: float
    projected_net_rs: float
    co2_kg: float
    days_elapsed: float
    days_in_month: int
    breakdown: dict  # services.bill_xray.Xray for the projected units
    stated_kwh: float
    diff_pct: int
    mismatch: bool
    complaint: dict | None


@router.get("/bill", response_model=BillOut)
def bill(user: CurrentUser, db: DbSession, locale: RequestLocale):
    meter = _meter(db, user)
    h = user.household
    month = svc.month_summary(db, meter, h)
    split = xray(h, month["projected_import_kwh"], h.members)
    stated = svc.billed_kwh(db, user)
    diff = round(100 * (month["projected_load_kwh"] - stated) / stated) if stated else 0
    mismatch = abs(diff) >= agent_svc.MISMATCH_PCT
    complaint = None
    if mismatch:
        _raise_flag(db, meter, "bill_mismatch", tr(locale, "meter.flag.bill_mismatch", diff=abs(diff)))
        params = {"serial": meter.serial, "meter": month["projected_load_kwh"], "stated": stated, "diff": abs(diff)}
        complaint = {"subject": tr(locale, "agent.complaint.subject"), "body": tr(locale, "agent.complaint.body", **params)}
    return BillOut(simulated=meter.source == "simulated", breakdown=asdict(split), stated_kwh=stated, diff_pct=diff,
                   mismatch=mismatch, complaint=complaint, **month)


def _raise_flag(db, meter: Meter, kind: str, detail: str) -> None:
    open_flag = db.scalar(select(MeterFlag.id).where(MeterFlag.meter_id == meter.id, MeterFlag.kind == kind,
                                                     MeterFlag.status == "open"))
    if open_flag is None:
        db.add(MeterFlag(meter_id=meter.id, kind=kind, detail=detail[:300]))
        db.commit()


# --- Society energy ----------------------------------------------------------------

class SocietyEnergyOut(BaseModel):
    visible: bool  # false until enough homes have meters that no single home can be read from the totals
    min_group_size: int
    homes: int
    homes_with_solar: int = 0
    load_kw: float = 0.0
    pv_kw: float = 0.0
    spare_solar_kw: float = 0.0  # panels' surplus over the society's own load right now
    import_today_kwh: float = 0.0
    export_today_kwh: float = 0.0
    solar_share_pct: int = 0
    co2_today_kg: float = 0.0
    series: list[Point] = []


@router.get("/society", response_model=SocietyEnergyOut)
def society_energy(user: CurrentUser, db: DbSession):
    """The society's meters added together. Totals only: no home is ever singled out, and nothing is shown
    until MIN_GROUP_SIZE homes have meters."""
    from app.models import SocietyMember
    from app.routers.societies import MIN_GROUP_SIZE

    member = user.society_member
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You haven't joined a society")
    rows = db.execute(
        select(Meter, User).join(User, User.id == Meter.user_id)
        .join(SocietyMember, SocietyMember.user_id == Meter.user_id)
        .where(SocietyMember.society_id == member.society_id)
    ).all()
    if len(rows) < MIN_GROUP_SIZE:
        return SocietyEnergyOut(visible=False, min_group_size=MIN_GROUP_SIZE, homes=len(rows))
    for meter, owner in rows:
        svc.catch_up(db, meter, owner)
    meters = [m for m, _ in rows]
    now = datetime.now(UTC)
    start, end = ist_day_bounds_utc(today_ist())
    totals: dict[datetime, list[float]] = {}
    for m in meters:
        for r in svc.readings_between(db, m, now - timedelta(hours=24), now):
            t = totals.setdefault(as_utc(r.ts), [0.0, 0.0])
            t[0] += r.load_kw
            t[1] += r.pv_kw
    ordered = sorted(totals.items())
    latest = ordered[-1][1] if ordered else [0.0, 0.0]
    imp = exp = load = 0.0
    for m in meters:
        i, e = svc.usage_between(db, m, start, min(now, end))
        imp, exp = imp + i, exp + e
        load += svc.load_between(db, m, start, min(now, end))
    return SocietyEnergyOut(
        visible=True, min_group_size=MIN_GROUP_SIZE, homes=len(meters),
        homes_with_solar=sum(1 for m in meters if m.pv_kwp > 0),
        load_kw=round(latest[0], 2), pv_kw=round(latest[1], 2), spare_solar_kw=round(max(latest[1] - latest[0], 0), 2),
        import_today_kwh=round(imp, 1), export_today_kwh=round(exp, 1),
        solar_share_pct=round(100 * svc.solar_share(load, imp)), co2_today_kg=round(imp * factors.GRID_KG_CO2_PER_KWH, 1),
        series=[Point(ts=ts, load_kw=round(v[0], 2), pv_kw=round(v[1], 2)) for ts, v in ordered],
    )


# --- The agent ---------------------------------------------------------------------

class StepOut(BaseModel):
    tool: str
    text: str


class RecOut(BaseModel):
    key: str
    title: str
    body: str
    rs_month: float
    co2_kg_month: float
    action_code: str | None
    meter_confirmable: bool


class AgentOut(BaseModel):
    summary: str
    written_by_ai: bool
    facts: dict[str, float | int]  # the only numbers the summary may use
    steps: list[StepOut]
    recommendations: list[RecOut]


@router.get("/agent", response_model=AgentOut)
async def agent(user: CurrentUser, db: DbSession, locale: RequestLocale):
    meter = _meter(db, user)
    report = agent_svc.analyze(db, user, meter, datetime.now(UTC), locale)
    text, by_ai = await agent_svc.summary(report, locale)
    return AgentOut(
        summary=text,
        written_by_ai=by_ai,
        facts=report.facts,
        steps=[StepOut(tool=s.tool, text=tr(locale, s.key, **s.params)) for s in report.steps],
        recommendations=[
            RecOut(key=r.key, title=tr(locale, f"{r.key}.title", **r.params), body=tr(locale, f"{r.key}.body", **r.params),
                   rs_month=r.rs_month, co2_kg_month=r.co2_kg_month, action_code=r.action_code,
                   meter_confirmable=r.meter_confirmable)
            for r in report.recommendations
        ],
    )


class ApplianceIn(BaseModel):
    kind: KINDS


@router.post("/appliance", status_code=status.HTTP_201_CREATED)
def run_appliance(body: ApplianceIn, user: CurrentUser, db: DbSession):
    """Simulated meters only: tell the meter you just ran an appliance, so it shows up in the readings."""
    meter = _meter(db, user)
    if meter.source != "simulated":
        raise HTTPException(status.HTTP_409_CONFLICT, "A real meter measures what happened; it can't be told")
    event = svc.run_appliance(db, meter, user, body.kind)
    return {"kind": event.kind, "kw": event.delta_kw, "minutes": meter_sim.APPLIANCES[event.kind][1]}


class ConfirmIn(BaseModel):
    code: Literal["shift_heavy_load"]


@router.post("/agent/confirm", response_model=ActionLogOut, status_code=status.HTTP_201_CREATED)
def confirm(body: ConfirmIn, user: CurrentUser, db: DbSession, locale: RequestLocale):
    """Log a green action as verified because the meter itself shows it, with no photo needed."""
    meter = _meter(db, user)
    action = db.scalar(select(ActionType).where(ActionType.code == body.code))
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown action")
    impact = action_impact(action.code, user.household)
    if not impact.applicable:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, impact.reason(locale))
    moved = agent_svc.confirm_shift(db, meter, datetime.now(UTC))
    if moved <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The meter doesn't show a heavy load outside the evening peak yet")

    today = today_ist()
    start, end = ist_day_bounds_utc(today)
    logged = db.scalar(select(func.count(ActionLog.id)).where(
        ActionLog.user_id == user.id, ActionLog.action_type_id == action.id, ActionLog.status != ActionStatus.rejected,
        ActionLog.created_at >= start, ActionLog.created_at < end))
    if logged >= action.max_per_day:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"You can log '{action.title}' at most {action.max_per_day}x per day")
    challenge = daily_challenge_for(db, user.id, today, user.household, locale)
    is_challenge = challenge.action.code == action.code and not challenge.completed
    log = ActionLog(
        user_id=user.id, action_type_id=action.id, status=ActionStatus.verified,
        points_awarded=points_for(action.points, ActionStatus.verified, is_challenge),
        co2_saved_kg=impact.co2_kg, kwh_saved=impact.kwh, is_daily_challenge=is_challenge,
        note=f"Confirmed by meter {meter.serial}: {moved} kWh of heavy load outside the evening peak",
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log_out(log, locale)


# --- Real meters -------------------------------------------------------------------

class ReadingIn(BaseModel):
    serial: str = Field(max_length=32)
    ts: str = Field(max_length=40)  # signed exactly as sent, so it stays text until the signature is checked
    import_kwh: float = Field(ge=0)
    export_kwh: float = Field(ge=0)
    load_kw: float = Field(ge=0, le=100)
    pv_kw: float = Field(ge=0, le=100)
    signature: str = Field(max_length=128)


@router.post("/link")
def link_device(user: CurrentUser, db: DbSession):
    """Switch this household from the simulated meter to a real device. Returns the serial and the
    secret the device signs its readings with, once; the simulated history is dropped so the two never mix."""
    meter = _meter(db, user)
    if meter.source == "device":
        raise HTTPException(status.HTTP_409_CONFLICT, "A device is already linked")
    db.execute(delete(MeterReading).where(MeterReading.meter_id == meter.id))
    from app.models import MeterEvent

    db.execute(delete(MeterEvent).where(MeterEvent.meter_id == meter.id))
    meter.source = "device"
    db.commit()
    return {"serial": meter.serial, "secret": meter.secret,
            "signed_fields": list(meter_ingest.SIGNED_FIELDS), "endpoint": "/api/meter/readings",
            "signature": "HMAC-SHA256 hex over serial|ts|import_kwh|export_kwh|load_kw|pv_kw, ts as sent, "
                         "registers with 3 decimals and powers with 4"}


@router.post("/readings", status_code=status.HTTP_201_CREATED)
def ingest(body: ReadingIn, db: DbSession):
    """A device's signed reading. Authenticated by its HMAC signature, not by a user login."""
    meter = db.scalar(select(Meter).where(Meter.serial == body.serial))
    reading = body.model_dump(exclude={"signature"})
    if meter is None or meter.source != "device" or not meter_ingest.verify(reading, body.signature, meter.secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad serial or signature")
    try:
        ts = datetime.fromisoformat(body.ts)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "ts must be an ISO 8601 time") from None
    ts = as_utc(ts if ts.tzinfo else ts.replace(tzinfo=UTC))
    now = datetime.now(UTC)
    if meter_ingest.from_the_future(ts, now):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Reading is from the future")
    if not meter_ingest.within_replay_window(ts, now):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Reading is too old")
    last = svc.last_reading(db, meter)
    if last is not None:
        verdict = meter_ingest.evaluate_register(last.import_kwh, body.import_kwh)
        if verdict.kind == "rollback":
            _raise_flag(db, meter, "register_rollback", tr("en", "meter.flag.register_rollback"))
            raise HTTPException(status.HTTP_409_CONFLICT, "Register went backwards; flagged for the utility")
    db.add(MeterReading(meter_id=meter.id, ts=ts, import_kwh=body.import_kwh, export_kwh=body.export_kwh,
                        load_kw=body.load_kw, pv_kw=body.pv_kw))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate reading for this time") from None
    return {"ok": True}


LiveOut.model_rebuild()
