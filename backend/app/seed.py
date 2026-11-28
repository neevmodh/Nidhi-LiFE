"""Reference data: Gujarat's districts and the green action catalogue.

Upserted on every start. The only made-up data is the clearly labelled demo set (the three public demo
logins and the simulated UGVCL homes behind the demo DISCOM console), and it can be switched off with
DEMO_ACCOUNTS=false; everything else comes from a real person using the app.
Create the first GEDA administrator with `python -m app.create_admin`.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.i18n import tr
from app.migrate import upgrade_to_head
from app.models import (
    ActionType,
    District,
    EnergyReading,
    Household,
    MeterFlag,
    Outage,
    Role,
    SolarLead,
    User,
)
from app.security import hash_password
from app.services import factors
from app.services import meter as meters
from app.services.footprint import FootprintInput, monthly_footprint
from app.services.impact import action_impact
from app.timeutil import today_ist

# All 33 districts of Gujarat. lat/lon is an interior point of each district boundary
# (geoBoundaries IND ADM2, 2021). The last value is the DISCOM suggested at onboarding:
# the state company for the region, or Torrent Power for the Ahmedabad, Gandhinagar
# and Surat cities it serves. Households can change it (rural parts of those districts
# are served by UGVCL or DGVCL).
DISTRICTS = [
    ("Ahmedabad", 22.7246, 72.3143, "torrent"),
    ("Surat", 21.1889, 72.9513, "torrent"),
    ("Amreli", 21.4257, 71.2758, "pgvcl"),
    ("Anand", 22.4885, 72.7612, "mgvcl"),
    ("Aravalli", 23.488, 73.4015, "ugvcl"),
    ("Banaskantha", 24.2709, 72.17, "ugvcl"),
    ("Bharuch", 21.8147, 72.9516, "dgvcl"),
    ("Bhavnagar", 21.5694, 71.9111, "pgvcl"),
    ("Botad", 22.0451, 71.6749, "pgvcl"),
    ("Chhota Udaipur", 22.22, 73.7873, "mgvcl"),
    ("Dahod", 22.9186, 74.1341, "mgvcl"),
    ("Dang", 20.7808, 73.7125, "dgvcl"),
    ("Devbhumi Dwarka", 22.1367, 69.4298, "pgvcl"),
    ("Gandhinagar", 23.2803, 72.6667, "torrent"),
    ("Gir Somnath", 20.9864, 70.6906, "pgvcl"),
    ("Jamnagar", 22.3172, 70.1062, "pgvcl"),
    ("Junagadh", 21.3407, 70.4192, "pgvcl"),
    ("Kheda", 22.8561, 72.9981, "mgvcl"),
    ("Kutch", 23.7099, 69.8224, "pgvcl"),
    ("Mahisagar", 23.1875, 73.6591, "mgvcl"),
    ("Mehsana", 23.567, 72.3598, "ugvcl"),
    ("Morbi", 22.7939, 70.888, "pgvcl"),
    ("Narmada", 21.7303, 73.6294, "dgvcl"),
    ("Navsari", 20.8269, 73.0351, "dgvcl"),
    ("Panchmahal", 22.6976, 73.6065, "mgvcl"),
    ("Patan", 23.7714, 71.7869, "ugvcl"),
    ("Porbandar", 21.6047, 69.8531, "pgvcl"),
    ("Rajkot", 22.066, 71.0259, "pgvcl"),
    ("Sabarkantha", 23.8702, 73.0157, "ugvcl"),
    ("Surendranagar", 22.8294, 71.6101, "pgvcl"),
    ("Tapi", 21.1876, 73.5557, "dgvcl"),
    ("Vadodara", 22.3166, 73.3042, "mgvcl"),
    ("Valsad", 20.4419, 73.1668, "dgvcl"),
]

# Titles and descriptions live in locales/en.json
# (translated to Gujarati and Hindi alongside the rest of the app).
ACTIONS = [
    # code, category, theme (Mission LiFE), points, max_per_day
    ("ac_24", "energy", "energy", 15, 1),
    ("shift_heavy_load", "energy", "energy", 10, 2),
    ("geyser_off", "energy", "energy", 10, 1),
    ("standby_off", "energy", "energy", 5, 1),
    ("led_switch", "energy", "energy", 30, 1),
    ("solar_survey", "solar", "energy", 40, 1),
    ("pressure_cooker", "cooking", "energy", 10, 1),
    ("public_transport", "mobility", "energy", 20, 2),
    ("carpool", "mobility", "energy", 20, 2),
    ("cycle_walk", "mobility", "health", 20, 2),
    ("stairs", "health", "health", 5, 2),
    ("plant_tree", "nature", "health", 50, 1),
    ("save_water", "water", "water", 5, 1),
    ("cloth_bag", "waste", "plastic", 5, 1),
    ("reusable_bottle", "waste", "plastic", 5, 1),
    ("no_food_waste", "food", "food", 5, 1),
    ("millet_meal", "food", "food", 10, 1),
    ("segregate_waste", "waste", "waste", 5, 1),
    ("compost", "waste", "waste", 15, 1),
    ("ewaste_recycle", "ewaste", "ewaste", 40, 1),
    ("repair_not_replace", "ewaste", "ewaste", 30, 1),
]


@dataclass(frozen=True)
class _TypicalHousehold:
    """Reference household for the catalogue's "typical" figures; each user sees their own."""

    ac_count: int = 1
    has_geyser: bool = True
    has_washing_machine: bool = True
    has_ev: bool = False
    commute_mode: str = "two_wheeler"
    commute_km_per_day: float = 10
    lpg_cylinders_per_month: float = 1


def seed_reference(db: Session) -> None:
    existing = {d.name: d for d in db.scalars(select(District))}
    for name, lat, lon, _ in DISTRICTS:
        district = existing.get(name) or District(name=name)
        district.lat, district.lon = lat, lon
        db.add(district)

    existing_actions = {a.code: a for a in db.scalars(select(ActionType))}
    for code, category, theme, points, max_per_day in ACTIONS:
        title = tr("en", f"action.{code}.title")
        desc = tr("en", f"action.{code}.description", peak=factors.peak_label())
        typical = action_impact(code, _TypicalHousehold())
        action = existing_actions.get(code) or ActionType(code=code)
        action.title, action.description, action.category, action.theme = title, desc, category, theme
        action.points, action.co2_saved_kg, action.kwh_saved, action.max_per_day = (
            points, typical.co2_kg, typical.kwh, max_per_day
        )
        db.add(action)
    db.commit()


def suggested_discom(district_name: str | None) -> str:
    return next((d for name, _, _, d in DISTRICTS if name == district_name), factors.DEFAULT_DISCOM)


DEMO_HOUSEHOLD_EMAIL = "demo-household@example.com"
DEMO_DISCOM_EMAIL = "demo-discom@example.com"
DEMO_GEDA_EMAIL = "demo-geda@example.com"


def ensure_demo_accounts(db: Session) -> list[str]:
    """Create or refresh the three public demo logins and return their emails.

    A household (a normal citizen, with rooftop solar, so Live energy has something to show), a DISCOM
    auditor for UGVCL and a GEDA auditor. Both staff roles are read-only. The passwords are reset to
    the configured one every time, so the published login keeps working.
    """
    settings = get_settings()
    if not settings.demo_accounts:
        return []
    ahmedabad = db.scalar(select(District).where(District.name == "Ahmedabad")) or db.scalar(select(District).order_by(District.id))
    pw = hash_password(settings.demo_password)
    wanted = [
        (DEMO_HOUSEHOLD_EMAIL, "Demo Household", Role.citizen, None),
        (DEMO_DISCOM_EMAIL, "Demo DISCOM (read-only)", Role.discom_auditor, "ugvcl"),
        (DEMO_GEDA_EMAIL, "Demo GEDA (read-only)", Role.auditor, None),
    ]
    for email, name, role, discom in wanted:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, password_hash=pw, role=role, district_id=ahmedabad.id if ahmedabad else None,
                        ward="Ward 3" if role == Role.citizen else None)
            db.add(user)
            db.flush()
        user.password_hash, user.role, user.discom = pw, role, discom
        if role == Role.citizen and user.household is None:
            footprint = monthly_footprint(FootprintInput(monthly_kwh=320, members=4, lpg_cylinders_per_month=1, commute_mode="car", commute_km_per_day=8))
            db.add(Household(user_id=user.id, members=4, home_type="independent", monthly_kwh=320, lpg_cylinders_per_month=1, commute_mode="car",
                             commute_km_per_day=8, ac_count=2, has_geyser=True, has_washing_machine=True, has_ev=False, has_solar=True,
                             roof_area_sqm=35, discom="ugvcl", area="urban", baseline_kg_co2_month=footprint.total_kg))
            db.add(EnergyReading(user_id=user.id, month=today_ist().replace(day=1), kwh=320, source="onboarding"))
    db.commit()
    return [e for e, *_ in wanted]


# The demo DISCOM console needs a company to look at. These are simulated homes, labelled as such
# everywhere: emails on example.com, names "Demo home NN", meters marked simulated, and nobody can sign in
# as them (their password is random and never stored). They exist only while demo accounts are on.
DEMO_FLEET_DISCOM = "ugvcl"
DEMO_FLEET_SIZE = 24
DEMO_FLEET_EMAIL = "demo-home-{:02d}@example.com"
_FLEET_DISTRICTS = ["Mehsana", "Patan", "Sabarkantha"]
_FLAGS = [
    ("night_spike", "Load of 3.1 kW between 01:00 and 04:00 on three nights; this home normally sits under 0.4 kW", "open"),
    ("bill_mismatch", "Last bill says 410 units; the meter registered 286 units over the same period", "open"),
    ("register_rollback", "Import register read 1843.2 kWh, then 1839.7 kWh fifteen minutes later", "open"),
    ("night_spike", "Steady 2.4 kW overnight for a week, after months under 0.5 kW", "open"),
    ("bill_mismatch", "Bill of 120 units against 238 units on the meter: possible bypass or misread", "open"),
    ("register_rollback", "Register stepped back 2.1 kWh after a power cut; meter clock reset", "resolved"),
    ("bill_mismatch", "Bill and meter differed by 64 units; the reading date was wrong and the bill was revised", "resolved"),
]
_LEADS = [(3.0, "new"), (4.0, "contacted"), (2.0, "survey_done"), (5.0, "quoted"), (3.0, "installed"), (2.5, "new")]


def ensure_demo_fleet(db: Session) -> int:
    """Create (once) simulated UGVCL homes with meters, a few anomalies, solar leads and upcoming outages.
    Returns how many demo homes there are. Safe to run on every start."""
    if not get_settings().demo_accounts:
        return 0
    districts = {d.name: d for d in db.scalars(select(District).where(District.name.in_(_FLEET_DISTRICTS)))}
    homes: list[User] = []
    for i in range(1, DEMO_FLEET_SIZE + 1):
        email = DEMO_FLEET_EMAIL.format(i)
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            district = districts.get(_FLEET_DISTRICTS[i % len(_FLEET_DISTRICTS)])
            members, ac = 2 + i % 4, i % 3
            kwh = 140 + (i * 37) % 260 + 60 * ac
            solar = i % 3 == 0
            user = User(email=email, name=f"Demo home {i:02d}", password_hash=hash_password(secrets.token_urlsafe(24)),
                        role=Role.citizen, district_id=district.id if district else None, ward=f"Ward {1 + (i // 3) % 3}")
            db.add(user)
            db.flush()
            footprint = monthly_footprint(FootprintInput(monthly_kwh=kwh, members=members, lpg_cylinders_per_month=1,
                                                         commute_mode="two_wheeler", commute_km_per_day=8))
            db.add(Household(user_id=user.id, members=members, home_type="independent" if i % 2 else "apartment",
                             monthly_kwh=kwh, lpg_cylinders_per_month=1, commute_mode="two_wheeler", commute_km_per_day=8,
                             ac_count=ac, has_geyser=i % 2 == 0, has_washing_machine=True, has_ev=i % 8 == 0,
                             has_solar=solar, roof_area_sqm=30 if solar else 0, discom=DEMO_FLEET_DISCOM,
                             area="rural" if i % 4 == 0 else "urban", baseline_kg_co2_month=footprint.total_kg))
            db.commit()
            db.refresh(user)
        homes.append(user)
    fleet = []
    for user in homes:
        meter = meters.ensure_meter(db, user)
        if meter is not None:
            meters.catch_up(db, meter, user)
            fleet.append((meter, user))

    meter_ids = [m.id for m, _ in fleet]
    now = datetime.now(UTC)
    if fleet and not db.scalar(select(MeterFlag.id).where(MeterFlag.meter_id.in_(meter_ids)).limit(1)):
        for n, (kind, detail, state) in enumerate(_FLAGS):
            meter = fleet[(n * 5 + 2) % len(fleet)][0]
            db.add(MeterFlag(meter_id=meter.id, kind=kind, detail=detail, status=state,
                             created_at=now - timedelta(hours=3 + 9 * n),
                             resolved_at=now - timedelta(hours=2 + 9 * n) if state == "resolved" else None))
    user_ids = [u.id for _, u in fleet]
    if fleet and not db.scalar(select(SolarLead.id).where(SolarLead.user_id.in_(user_ids)).limit(1)):
        for n, (kwp, state) in enumerate(_LEADS):
            user = fleet[(n * 4 + 1) % len(fleet)][1]
            h = user.household
            db.add(SolarLead(user_id=user.id, district_id=user.district_id, kwp=kwp, roof_area_sqm=kwp * factors.SQM_PER_KWP,
                             monthly_kwh=h.monthly_kwh, note="Demo request", status=state,
                             created_at=now - timedelta(days=1 + 2 * n)))
    # Outages are only listed until they end, so keep two upcoming ones on demo feeders.
    feeders = sorted({m.feeder for m, _ in fleet})
    upcoming = db.scalar(select(Outage.id).where(Outage.discom == DEMO_FLEET_DISCOM, Outage.ends_at > now,
                                                 Outage.feeder.in_(feeders)).limit(1))
    if feeders and upcoming is None:
        today = now.replace(minute=0, second=0, microsecond=0)
        for days, hour_utc, hours, reason, feeder in [
            (1, 4, 3, "Planned maintenance: replacing a 100 kVA distribution transformer", feeders[0]),
            (3, 5, 2, "Tree trimming along the 11 kV line before the winter fog season", feeders[len(feeders) // 2]),
            (6, 3, 4, "Feeder bifurcation work to relieve evening overload", feeders[-1]),
        ]:
            start = today.replace(hour=hour_utc) + timedelta(days=days)
            db.add(Outage(discom=DEMO_FLEET_DISCOM, feeder=feeder, reason=reason, starts_at=start,
                          ends_at=start + timedelta(hours=hours)))
    db.commit()
    return len(fleet)


def main() -> None:
    upgrade_to_head()
    with SessionLocal() as db:
        seed_reference(db)
        ensure_demo_accounts(db)
        ensure_demo_fleet(db)


if __name__ == "__main__":
    main()
