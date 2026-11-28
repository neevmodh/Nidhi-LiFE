"""DISCOM console: demand by feeder, anomalies, outages and rooftop-solar leads for a distribution company.

DISCOM staff see only their own company (`users.discom`); the GEDA state team and auditors can look at any
(`?discom=`), read-only. Simulated meters are advanced when read, so every list here first catches up the
meters in scope. Households are shown by meter serial and feeder, never by name.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.deps import DbSession, DiscomEngineer, DiscomUser, discom_scope
from app.models import (
    Household,
    Meter,
    MeterFlag,
    MeterReading,
    Outage,
    SolarLead,
    User,
)
from app.schemas import UtcDatetime
from app.services import factors, meter_sim
from app.services import meter as svc
from app.services.notify import notify
from app.timeutil import as_utc, ist_day_bounds_utc, today_ist

router = APIRouter(prefix="/api/discom", tags=["discom"])

MAX_METERS = 800  # the demo scale; a real deployment would aggregate in the database
FEEDER_DIVERSITY = 0.5  # a feeder is rated for about half the sum of its homes' sanctioned loads
HOT_UTILISATION_PCT = 80

DiscomQuery = Annotated[str | None, Query(alias="discom", pattern="^[a-z]{3,10}$")]


def _scope(user: User, requested: str | None) -> str:
    code = discom_scope(user, requested)
    if code is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pass ?discom= (the state team looks at one company at a time)")
    if code not in factors.DISCOMS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown distribution company")
    return code


def _fleet(db, discom: str) -> list[tuple[Meter, User]]:
    """The company's meters, each caught up to now."""
    rows = db.execute(
        select(Meter, User).join(User, User.id == Meter.user_id).where(Meter.discom == discom).limit(MAX_METERS)
    ).all()
    # One query for every meter's latest reading, so meters already up to date cost nothing more.
    simulated = [m.id for m, _ in rows if m.source == "simulated"]
    latest = dict(db.execute(
        select(MeterReading.meter_id, func.max(MeterReading.ts)).where(MeterReading.meter_id.in_(simulated))
        .group_by(MeterReading.meter_id)
    ).all()) if simulated else {}
    due = meter_sim.floor_interval(datetime.now(UTC))
    for meter, user in rows:
        last = latest.get(meter.id)
        if meter.source == "simulated" and (last is None or as_utc(last) < due):
            svc.catch_up(db, meter, user)
    return [(m, u) for m, u in rows]


def _window(db, meters: list[Meter], start: datetime, end: datetime) -> dict[int, list[MeterReading]]:
    if not meters:
        return {}
    rows = db.scalars(
        select(MeterReading).where(MeterReading.meter_id.in_([m.id for m in meters]), MeterReading.ts > start,
                                   MeterReading.ts <= end).order_by(MeterReading.ts)
    ).all()
    by_meter: dict[int, list[MeterReading]] = defaultdict(list)
    for r in rows:
        by_meter[r.meter_id].append(r)
    return by_meter


def _by_feeder(db, code: str, start: datetime, end: datetime) -> dict[str, dict[datetime, tuple[float, float]]]:
    """Per feeder, per 15-minute interval: (summed load kW, summed PV kW). Summed in the database, so a week
    of a whole company's readings never has to be loaded as objects."""
    rows = db.execute(
        select(Meter.feeder, MeterReading.ts, func.sum(MeterReading.load_kw), func.sum(MeterReading.pv_kw))
        .join(Meter, Meter.id == MeterReading.meter_id)
        .where(Meter.discom == code, MeterReading.ts > start, MeterReading.ts <= end)
        .group_by(Meter.feeder, MeterReading.ts)
        .order_by(MeterReading.ts)
    ).all()
    out: dict[str, dict[datetime, tuple[float, float]]] = defaultdict(dict)
    for feeder, ts, load, pv in rows:
        out[feeder][as_utc(ts)] = (float(load), float(pv))
    return out


def _aggregate(by_meter: dict[int, list[MeterReading]]) -> dict[datetime, tuple[float, float]]:
    """Per 15-minute interval: (summed load kW, summed PV kW) across meters."""
    total: dict[datetime, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for rows in by_meter.values():
        for r in rows:
            t = total[as_utc(r.ts)]
            t[0] += r.load_kw
            t[1] += r.pv_kw
    return {ts: (v[0], v[1]) for ts, v in sorted(total.items())}


class OverviewOut(BaseModel):
    discom: str
    name: str
    meters: int
    simulated_meters: int
    load_kw: float
    pv_kw: float
    grid_kw: float
    import_today_kwh: float
    export_today_kwh: float
    co2_today_kg: float
    peak_kw_today: float
    open_flags: int
    active_outages: int
    solar_leads: int


@router.get("/overview", response_model=OverviewOut)
def overview(user: DiscomUser, db: DbSession, discom: DiscomQuery = None):
    code = _scope(user, discom)
    fleet = _fleet(db, code)
    meters = [m for m, _ in fleet]
    start, end = ist_day_bounds_utc(today_ist())
    now = datetime.now(UTC)
    by_meter = _window(db, meters, start, min(now, end))
    series = _aggregate(by_meter)
    latest = list(series.values())[-1] if series else (0.0, 0.0)
    # Per-home netting is what the meters register, so units come from the registers, not the aggregate curve.
    totals = svc.usage_many(db, meters, start, min(now, end)).values()
    imp_reg = sum(i for i, _ in totals)
    exp_reg = sum(e for _, e in totals)
    open_flags = len(db.scalars(select(MeterFlag.id).join(Meter, Meter.id == MeterFlag.meter_id)
                                .where(Meter.discom == code, MeterFlag.status == "open")).all())
    outages = len(db.scalars(select(Outage.id).where(Outage.discom == code, Outage.ends_at > now)).all())
    leads = len(db.scalars(select(SolarLead.id).join(Household, Household.user_id == SolarLead.user_id)
                           .where(Household.discom == code, SolarLead.status != "dropped")).all())
    return OverviewOut(
        discom=code, name=factors.DISCOMS[code], meters=len(meters),
        simulated_meters=sum(1 for m in meters if m.source == "simulated"),
        load_kw=round(latest[0], 2), pv_kw=round(latest[1], 2), grid_kw=round(latest[0] - latest[1], 2),
        import_today_kwh=round(imp_reg, 1), export_today_kwh=round(exp_reg, 1),
        co2_today_kg=round(imp_reg * factors.GRID_KG_CO2_PER_KWH, 1),
        peak_kw_today=round(max((load for load, _ in series.values()), default=0.0), 2),
        open_flags=open_flags, active_outages=outages, solar_leads=leads,
    )


class SeriesPoint(BaseModel):
    ts: UtcDatetime
    load_kw: float
    pv_kw: float


@router.get("/series", response_model=list[SeriesPoint])
def company_series(user: DiscomUser, db: DbSession, discom: DiscomQuery = None, hours: int = Query(24, ge=1, le=168)):
    """Demand and rooftop solar across the whole company, every 15 minutes."""
    code = _scope(user, discom)
    meters = [m for m, _ in _fleet(db, code)]
    now = datetime.now(UTC)
    series = _aggregate(_window(db, meters, now - timedelta(hours=hours), now))
    return [SeriesPoint(ts=ts, load_kw=round(load, 2), pv_kw=round(pv, 2)) for ts, (load, pv) in series.items()]


class FeederOut(BaseModel):
    feeder: str
    meters: int
    rated_kw: float
    load_kw: float
    pv_kw: float
    utilisation_pct: int
    hot: bool
    peak_kw_week: float
    peak_over_p90_kw: float  # how far the worst quarter-hour sits above the 90th percentile: what shaving could trim
    peak_hour: int | None  # IST hour the week's peak falls in
    import_today_kwh: float


@router.get("/feeders", response_model=list[FeederOut])
def feeders(user: DiscomUser, db: DbSession, discom: DiscomQuery = None):
    code = _scope(user, discom)
    fleet = _fleet(db, code)
    by_feeder: dict[str, list[Meter]] = defaultdict(list)
    for meter, _ in fleet:
        by_feeder[meter.feeder].append(meter)
    now = datetime.now(UTC)
    day_start, day_end = ist_day_bounds_utc(today_ist())
    week_by_feeder = _by_feeder(db, code, now - timedelta(days=7), now)
    day_use = svc.usage_many(db, [m for m, _ in fleet], day_start, min(now, day_end))
    out = []
    for feeder, meters in sorted(by_feeder.items()):
        week = week_by_feeder.get(feeder, {})
        loads = sorted(load for load, _ in week.values())
        latest = list(week.values())[-1] if week else (0.0, 0.0)
        peak = loads[-1] if loads else 0.0
        p90 = loads[int(0.9 * (len(loads) - 1))] if loads else 0.0
        peak_ts = max(week, key=lambda t: week[t][0]) if week else None
        rated = round(sum(m.sanctioned_load_kw for m in meters) * FEEDER_DIVERSITY, 1)
        util = round(100 * latest[0] / rated) if rated else 0
        imp = sum(day_use[m.id][0] for m in meters)
        out.append(FeederOut(
            feeder=feeder, meters=len(meters), rated_kw=rated, load_kw=round(latest[0], 2), pv_kw=round(latest[1], 2),
            utilisation_pct=util, hot=util >= HOT_UTILISATION_PCT, peak_kw_week=round(peak, 2),
            peak_over_p90_kw=round(peak - p90, 2),
            peak_hour=(peak_ts + timedelta(hours=meter_sim.IST_OFFSET_H)).hour if peak_ts else None,
            import_today_kwh=round(imp, 1)))
    return out


@router.get("/feeders/{feeder}/series", response_model=list[SeriesPoint])
def feeder_series(feeder: str, user: DiscomUser, db: DbSession, discom: DiscomQuery = None, hours: int = Query(24, ge=1, le=168)):
    code = _scope(user, discom)
    meters = [m for m, _ in _fleet(db, code) if m.feeder == feeder]
    if not meters:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such feeder")
    now = datetime.now(UTC)
    series = _aggregate(_window(db, meters, now - timedelta(hours=hours), now))
    return [SeriesPoint(ts=ts, load_kw=round(load, 2), pv_kw=round(pv, 2)) for ts, (load, pv) in series.items()]


class FlagOut(BaseModel):
    id: int
    kind: str
    detail: str
    status: str
    feeder: str
    meter: str  # serial, never a name
    created_at: UtcDatetime
    resolved_at: UtcDatetime | None


@router.get("/anomalies", response_model=list[FlagOut])
def anomalies(user: DiscomUser, db: DbSession, discom: DiscomQuery = None, state: str = Query("open", pattern="^(open|resolved|all)$")):
    code = _scope(user, discom)
    query = (select(MeterFlag, Meter).join(Meter, Meter.id == MeterFlag.meter_id).where(Meter.discom == code)
             .order_by(MeterFlag.id.desc()).limit(200))
    if state != "all":
        query = query.where(MeterFlag.status == state)
    return [FlagOut(id=f.id, kind=f.kind, detail=f.detail, status=f.status, feeder=m.feeder, meter=m.serial,
                    created_at=f.created_at, resolved_at=f.resolved_at) for f, m in db.execute(query).all()]


@router.post("/anomalies/{flag_id}/resolve", response_model=FlagOut)
def resolve(flag_id: int, user: DiscomEngineer, db: DbSession):
    row = db.execute(select(MeterFlag, Meter).join(Meter, Meter.id == MeterFlag.meter_id).where(MeterFlag.id == flag_id)).first()
    if row is None or discom_scope(user, row[1].discom) != row[1].discom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such flag")
    flag, meter = row
    flag.status, flag.resolved_at = "resolved", datetime.now(UTC)
    db.commit()
    return FlagOut(id=flag.id, kind=flag.kind, detail=flag.detail, status=flag.status, feeder=meter.feeder,
                   meter=meter.serial, created_at=flag.created_at, resolved_at=flag.resolved_at)


class OutageIn(BaseModel):
    feeder: str = Field(min_length=3, max_length=40)
    reason: str = Field(min_length=3, max_length=200)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _ordered(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("An outage must end after it starts")
        return self


class OutageRow(BaseModel):
    id: int
    feeder: str
    reason: str
    starts_at: UtcDatetime
    ends_at: UtcDatetime
    households: int


def _outage_row(db, o: Outage) -> OutageRow:
    homes = len(db.scalars(select(Meter.id).where(Meter.discom == o.discom, Meter.feeder == o.feeder)).all())
    return OutageRow(id=o.id, feeder=o.feeder, reason=o.reason, starts_at=o.starts_at, ends_at=o.ends_at, households=homes)


@router.get("/outages", response_model=list[OutageRow])
def outages(user: DiscomUser, db: DbSession, discom: DiscomQuery = None):
    code = _scope(user, discom)
    rows = db.scalars(select(Outage).where(Outage.discom == code, Outage.ends_at > datetime.now(UTC))
                      .order_by(Outage.starts_at)).all()
    return [_outage_row(db, o) for o in rows]


@router.post("/outages", response_model=OutageRow, status_code=status.HTTP_201_CREATED)
def raise_outage(body: OutageIn, user: DiscomEngineer, db: DbSession):
    code = _scope(user, None)
    homes = db.scalars(select(Meter).where(Meter.discom == code, Meter.feeder == body.feeder)).all()
    if not homes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such feeder in your company")
    outage = Outage(discom=code, feeder=body.feeder, reason=body.reason.strip(), starts_at=body.starts_at,
                    ends_at=body.ends_at, created_by=user.id)
    db.add(outage)
    window = f"{(as_utc(body.starts_at) + timedelta(hours=5.5)):%d %b %H:%M} - {(as_utc(body.ends_at) + timedelta(hours=5.5)):%H:%M}"
    for meter in homes:
        notify(db, meter.user_id, "outage", "/live", reason=outage.reason, window=window)
    db.commit()
    db.refresh(outage)
    return _outage_row(db, outage)


@router.delete("/outages/{outage_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_outage(outage_id: int, user: DiscomEngineer, db: DbSession):
    outage = db.get(Outage, outage_id)
    if outage is None or outage.discom != user.discom and user.discom is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such outage")
    db.delete(outage)
    db.commit()


class LeadOut(BaseModel):
    id: int
    kwp: float
    monthly_kwh: float
    status: str
    feeder: str | None
    created_at: UtcDatetime


@router.get("/solar-leads", response_model=list[LeadOut])
def solar_leads(user: DiscomUser, db: DbSession, discom: DiscomQuery = None):
    """Households in this company's area asking for a rooftop survey: net-metering connections to expect."""
    code = _scope(user, discom)
    rows = db.execute(
        select(SolarLead, Meter.feeder).join(Household, Household.user_id == SolarLead.user_id)
        .outerjoin(Meter, Meter.user_id == SolarLead.user_id)
        .where(Household.discom == code, SolarLead.status != "dropped").order_by(SolarLead.id.desc()).limit(200)
    ).all()
    return [LeadOut(id=lead.id, kwp=lead.kwp, monthly_kwh=lead.monthly_kwh, status=lead.status, feeder=feeder,
                    created_at=lead.created_at) for lead, feeder in rows]


