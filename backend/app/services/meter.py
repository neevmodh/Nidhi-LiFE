"""Smart-meter data for a household: provisioning, lazy catch-up, usage and the meter-derived bill.

A simulated meter is advanced when it is read (services/meter_sim.py is deterministic), so there is no
background worker and two API processes can never disagree. Device meters only get readings through the
signed endpoint (services/meter_ingest.py).
"""

import logging
import zlib
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    District,
    EnergyReading,
    Household,
    Meter,
    MeterEvent,
    MeterReading,
    User,
)
from app.services import factors, meter_sim
from app.services.footprint import electricity_bill_rs
from app.services.meter_ingest import derive_secret
from app.timeutil import as_utc, ist_day_bounds_utc, today_ist

log = logging.getLogger(__name__)

BACKFILL = timedelta(days=7)  # a new simulated meter starts with a week of history
MAX_CATCH_UP = timedelta(days=40)  # never generate more than this in one call
DEFAULT_PV_KWP = 3.0


def feeder_for(discom: str, district: District | None, ward: str | None) -> str:
    """The 11 kV feeder a house hangs off, from its district and ward (stable, a few feeders per district)."""
    code = (district.name[:3] if district else "GUJ").upper()
    n = zlib.crc32((ward or "-").lower().encode()) % 4 + 1
    return f"{discom.upper()}-{code}-F{n:02d}"


def serial_for(user_id: int) -> str:
    return f"NID{user_id:07d}"


def pv_kwp_for(household: Household) -> float:
    if not household.has_solar:
        return 0.0
    if household.roof_area_sqm:
        return round(min(max(household.roof_area_sqm / factors.SQM_PER_KWP, 1.0), 5.0), 1)
    return DEFAULT_PV_KWP


def profile_for(meter: Meter, household: Household, district: District | None) -> meter_sim.SimProfile:
    return meter_sim.SimProfile(
        serial=meter.serial,
        lat=district.lat if district else 23.03,
        lon=district.lon if district else 72.58,
        monthly_kwh=household.monthly_kwh,
        ac_count=household.ac_count,
        has_geyser=household.has_geyser,
        has_ev=household.has_ev,
        pv_kwp=meter.pv_kwp,
    )


def get_meter(db: Session, user: User) -> Meter | None:
    return db.scalar(select(Meter).where(Meter.user_id == user.id))


def ensure_meter(db: Session, user: User) -> Meter | None:
    """The household's meter, creating a simulated one on first use. None until onboarding is done."""
    meter = get_meter(db, user)
    if meter or user.household is None:
        return meter
    h = user.household
    district = db.get(District, user.district_id) if user.district_id else None
    serial = serial_for(user.id)
    meter = Meter(
        user_id=user.id,
        serial=serial,
        source="simulated",
        discom=h.discom,
        feeder=feeder_for(h.discom, district, user.ward),
        district_id=user.district_id,
        sanctioned_load_kw=4.0 + 1.5 * h.ac_count,
        pv_kwp=pv_kwp_for(h),
        secret=derive_secret(serial, get_settings().jwt_secret),
    )
    db.add(meter)
    try:
        db.commit()
    except IntegrityError:  # two requests raced to create it
        db.rollback()
        return get_meter(db, user)
    return meter


def last_reading(db: Session, meter: Meter) -> MeterReading | None:
    return db.scalar(
        select(MeterReading).where(MeterReading.meter_id == meter.id).order_by(MeterReading.ts.desc()).limit(1)
    )


def catch_up(db: Session, meter: Meter, user: User, now: datetime | None = None) -> int:
    """Advance a simulated meter to `now`. Returns how many intervals were added."""
    if meter.source != "simulated" or user.household is None:
        return 0
    now = meter_sim.floor_interval(now or datetime.now(UTC))
    last = last_reading(db, meter)
    if last is None:
        start = now - BACKFILL
        imp = 1000.0 + (zlib.crc32(meter.serial.encode()) % 5000) / 10  # a real meter does not start at zero
        exp = 0.0
    else:
        start = as_utc(last.ts)
        imp, exp = last.import_kwh, last.export_kwh
    start = max(start, now - MAX_CATCH_UP)
    district = db.get(District, meter.district_id) if meter.district_id else None
    profile = profile_for(meter, user.household, district)
    events = [
        (as_utc(e.starts_at), as_utc(e.ends_at), e.delta_kw)
        for e in db.scalars(select(MeterEvent).where(MeterEvent.meter_id == meter.id, MeterEvent.ends_at > start))
    ]
    rows = []
    ts = start + meter_sim.INTERVAL
    while ts <= now:
        step = meter_sim.simulate_interval(profile, ts, events)
        imp += step.import_kwh
        exp += step.export_kwh
        rows.append(
            MeterReading(
                meter_id=meter.id,
                ts=ts,
                import_kwh=round(imp, 4),
                export_kwh=round(exp, 4),
                load_kw=step.load_kw,
                pv_kw=step.pv_kw,
            )
        )
        ts += meter_sim.INTERVAL
    if not rows:
        return 0
    db.add_all(rows)
    try:
        db.commit()
    except IntegrityError:  # another process advanced the meter first; its rows are identical
        db.rollback()
        return 0
    return len(rows)


def readings_between(db: Session, meter: Meter, start: datetime, end: datetime) -> list[MeterReading]:
    return list(
        db.scalars(
            select(MeterReading)
            .where(MeterReading.meter_id == meter.id, MeterReading.ts > start, MeterReading.ts <= end)
            .order_by(MeterReading.ts)
        )
    )


def usage_between(db: Session, meter: Meter, start: datetime, end: datetime) -> tuple[float, float]:
    """(kWh imported, kWh exported) between two instants, from the cumulative registers."""
    rows = readings_between(db, meter, start, end)
    if not rows:
        return 0.0, 0.0
    before = db.scalar(
        select(MeterReading)
        .where(MeterReading.meter_id == meter.id, MeterReading.ts <= start)
        .order_by(MeterReading.ts.desc())
        .limit(1)
    )
    base_imp = before.import_kwh if before else rows[0].import_kwh
    base_exp = before.export_kwh if before else rows[0].export_kwh
    return round(rows[-1].import_kwh - base_imp, 3), round(rows[-1].export_kwh - base_exp, 3)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    return ist_day_bounds_utc(day)


def month_bounds(day: date) -> tuple[datetime, datetime]:
    first = day.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    start, _ = ist_day_bounds_utc(first)
    end, _ = ist_day_bounds_utc(nxt)
    return start, end


def load_between(db: Session, meter: Meter, start: datetime, end: datetime) -> float:
    """kWh the home consumed (its own panels included) between two instants."""
    return round(sum(r.load_kw for r in readings_between(db, meter, start, end)) * meter_sim.INTERVAL_MIN / 60, 3)


def solar_share(load_kwh: float, import_kwh: float) -> float:
    """Share of the home's consumption met by its own panels (self-consumption)."""
    if load_kwh <= 0:
        return 0.0
    return max(0.0, min(1.0, 1 - import_kwh / load_kwh))


def month_summary(db: Session, meter: Meter, household: Household, today: date | None = None) -> dict:
    """Month-to-date units, projection to month end and the bill the meter implies, with net-metering credit."""
    today = today or today_ist()
    start, end = month_bounds(today)
    now = datetime.now(UTC)
    upto = min(now, end)
    imp, exp = usage_between(db, meter, start, upto)
    rows = readings_between(db, meter, start, upto)
    load = round(sum(r.load_kw for r in rows) * meter_sim.INTERVAL_MIN / 60, 3)
    days_in_month = monthrange(today.year, today.month)[1]
    # Project from the span the readings actually cover, not the whole month so far: a meter linked
    # a week ago has a week of data, and dividing it by the month would under-count by three quarters.
    covered_from = max(start, as_utc(rows[0].ts) - meter_sim.INTERVAL) if rows else start
    elapsed = max((upto - covered_from).total_seconds() / 86400, 1 / 24)
    projected_import = round(imp / elapsed * days_in_month, 1)
    projected_export = round(exp / elapsed * days_in_month, 1)
    projected_load = round(load / elapsed * days_in_month, 1)
    bill = electricity_bill_rs(projected_import, household.discom, household.area)
    credit = round(projected_export * factors.NET_METERING_EXPORT_RS_PER_KWH, 2)
    return {
        "month": today.strftime("%Y-%m"),
        "import_kwh": imp,
        "export_kwh": exp,
        "load_kwh": load,
        "projected_load_kwh": projected_load,
        "days_elapsed": round(elapsed, 1),
        "days_in_month": days_in_month,
        "projected_import_kwh": projected_import,
        "projected_export_kwh": projected_export,
        "projected_bill_rs": bill,
        "net_metering_credit_rs": credit,
        "projected_net_rs": round(max(bill - credit, 0.0), 2),
        "co2_kg": round(imp * factors.GRID_KG_CO2_PER_KWH, 1),
    }


def run_appliance(db: Session, meter: Meter, user: User, kind: str, now: datetime | None = None) -> MeterEvent:
    """Tell a simulated meter the household just ran an appliance: the last stretch of readings is recomputed
    with that load included. Real meters can't be told what to measure."""
    if meter.source != "simulated":
        raise ValueError("only a simulated meter can be told what ran")
    kw, minutes = meter_sim.APPLIANCES[kind]
    now = meter_sim.floor_interval(now or datetime.now(UTC))
    catch_up(db, meter, user, now)
    start = now - timedelta(minutes=minutes)
    event = MeterEvent(meter_id=meter.id, kind=kind, starts_at=start, ends_at=now, delta_kw=kw)
    db.add(event)
    db.execute(delete(MeterReading).where(MeterReading.meter_id == meter.id, MeterReading.ts > start))
    db.commit()
    catch_up(db, meter, user, now)
    return event


def billed_kwh(db: Session, user: User) -> float:
    """The units the household's bills say it uses: its latest month's reading (a scanned or typed bill),
    or what it told Nidhi at sign-up when it has not added a bill. This is what the meter is checked against."""
    # The reading onboarding records for the current month is just what the household said, so it is skipped.
    latest = db.scalar(
        select(EnergyReading)
        .where(EnergyReading.user_id == user.id, EnergyReading.source != "onboarding")
        .order_by(EnergyReading.month.desc())
        .limit(1)
    )
    return latest.kwh if latest else user.household.monthly_kwh
