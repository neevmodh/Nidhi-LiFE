"""A physically modelled smart meter, for households that have no real one yet.

Ported from EcoPower 3.0's AMI simulator (packages/shared/src/ami): a household load built from a
base load, a time-of-day shape, an air-conditioner that follows the heat, and a geyser; plus rooftop
PV from solar geometry, clear-sky irradiance, cloud and cell-temperature derate. Everything is a pure,
deterministic function of the meter's serial and the timestamp, so the API can advance a meter lazily
(on read) with no background worker, and any process computes the same numbers.

The household's own onboarding answers shape the curve (AC count, geyser, EV, solar), and the whole
curve is scaled so a typical month matches its stated monthly units. Readings from this module are
always stored with source "simulated" and the app labels them so.
"""

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

INTERVAL_MIN = 15
INTERVAL = timedelta(minutes=INTERVAL_MIN)
IST_OFFSET_H = 5.5


@dataclass(frozen=True)
class SimProfile:
    serial: str
    lat: float
    lon: float
    monthly_kwh: float
    ac_count: int
    has_geyser: bool
    has_ev: bool
    pv_kwp: float


def _rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


@lru_cache(maxsize=20000)
def _unit(*parts: object) -> float:
    """A repeatable number in [0, 1) for these parts. Cached: the same day's weather or a home's profile is asked for
    thousands of times while a meter catches up."""
    return _rng(*parts).random()


def floor_interval(ts: datetime) -> datetime:
    ts = ts.astimezone(UTC).replace(second=0, microsecond=0)
    return ts - timedelta(minutes=ts.minute % INTERVAL_MIN)


# --- Weather: seasonal, deterministic, offline ------------------------------------

def ambient_temp_c(ts: datetime, serial: str = "") -> float:
    """Gujarat air temperature: hottest in May, coolest in January, peak mid-afternoon."""
    local = ts + timedelta(hours=IST_OFFSET_H)
    doy = local.timetuple().tm_yday
    seasonal = 27.5 + 7.5 * math.sin(2 * math.pi * (doy - 50) / 365)
    hour = local.hour + local.minute / 60
    diurnal = 6.0 * math.sin(2 * math.pi * (hour - 9) / 24)
    day_shift = (_unit("t", serial[:6], local.date().isoformat()) - 0.5) * 3
    return seasonal + diurnal + day_shift


def cloud_cover(ts: datetime, serial: str = "") -> float:
    """0 clear to 1 overcast: monsoon months are cloudy, the rest mostly clear."""
    local = ts + timedelta(hours=IST_OFFSET_H)
    base = 0.62 if 6 <= local.month <= 9 else 0.12
    day = _unit("c", serial[:6], local.date().isoformat()) - 0.5
    return min(1.0, max(0.0, base + day * 0.35))


# --- Solar ------------------------------------------------------------------------

def solar_elevation_deg(ts: datetime, lat: float, lon: float) -> float:
    doy = ts.timetuple().tm_yday
    declination = 23.45 * math.sin(math.radians((360 / 365) * (284 + doy)))
    hour_utc = ts.hour + ts.minute / 60
    hour_angle = 15 * (hour_utc + lon / 15 - 12)
    sin_el = math.sin(math.radians(lat)) * math.sin(math.radians(declination)) + math.cos(
        math.radians(lat)
    ) * math.cos(math.radians(declination)) * math.cos(math.radians(hour_angle))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def pv_kw(kwp: float, ts: datetime, lat: float, lon: float, cloud: float, temp_c: float) -> float:
    if kwp <= 0:
        return 0.0
    elevation = solar_elevation_deg(ts, lat, lon)
    if elevation <= 0:
        return 0.0
    cos_zenith = math.cos(math.radians(90 - elevation))
    ghi = 1098 * cos_zenith * math.exp(-0.059 / max(cos_zenith, 0.01))
    cloud_factor = 1 - cloud * 0.75
    derate = 1 - 0.004 * ((temp_c + 20) - 25)
    return max(0.0, kwp * (ghi / 1000) * cloud_factor * derate)


# --- Household load ---------------------------------------------------------------

def _shape_kw(hour: float, weekend: bool) -> float:
    if 6 <= hour < 9:
        return 0.35
    if 9 <= hour < 18:
        return 0.3 if weekend else 0.12
    if 18 <= hour < 23:
        return 0.7
    return 0.05


def _raw_load_kw(p: SimProfile, ts: datetime, temp_c: float) -> float:
    base = 0.08 + _unit("profile", p.serial, "base") * 0.12
    evening = 0.7 + _unit("profile", p.serial, "evening") * 0.6
    local = ts + timedelta(hours=IST_OFFSET_H)
    hour = local.hour + local.minute / 60
    summer = 3 <= local.month <= 6
    heat = max(0.0, temp_c - 28) / 12
    night_boost = 1.0 if summer and (hour >= 21 or hour < 6) else 0.4
    ac = 1.2 * p.ac_count * heat * night_boost
    geyser = 1.5 if p.has_geyser and 6 <= hour < 8 else 0.0
    ev = 2.5 if p.has_ev and (hour >= 23 or hour < 3) else 0.0
    return base + _shape_kw(hour, local.weekday() >= 5) * evening + ac + geyser + ev


def _scale(p: SimProfile, month: int) -> float:
    """Factor that makes a typical weekday of `month` add up to monthly_kwh / 30.

    Calibrated per month so a simulated home matches what its household said it uses in every
    season; without this the air conditioner would make winter look empty. A real meter has no
    such calibration: it reports whatever the home really drew.
    """
    ref = datetime(2026, month, 15, tzinfo=UTC)
    total = 0.0
    for i in range(96):
        ts = ref + INTERVAL * i
        total += _raw_load_kw(p, ts, ambient_temp_c(ts, p.serial)) * (INTERVAL_MIN / 60)
    return (p.monthly_kwh / 30) / total if total > 0 else 1.0


_scale_cache: dict[tuple, float] = {}


def load_kw(p: SimProfile, ts: datetime) -> float:
    month = (ts + timedelta(hours=IST_OFFSET_H)).month
    key = (p.serial, p.monthly_kwh, p.ac_count, p.has_geyser, p.has_ev, month)
    if key not in _scale_cache:
        _scale_cache[key] = _scale(p, month)
    jitter = 0.9 + 0.2 * _unit("j", p.serial, ts.isoformat())
    return _raw_load_kw(p, ts, ambient_temp_c(ts, p.serial)) * _scale_cache[key] * jitter


@dataclass(frozen=True)
class Interval:
    ts: datetime  # interval end
    load_kw: float
    pv_kw: float
    import_kwh: float  # energy drawn from the grid in this interval
    export_kwh: float  # surplus sent to the grid in this interval


# What each "I just ran it" button adds to the meter: (kW drawn, minutes it ran).
APPLIANCES: dict[str, tuple[float, int]] = {
    "washing_machine": (1.0, 60),
    "geyser": (1.5, 45),
    "ev_charger": (3.3, 120),
}


def event_kw(events: list[tuple[datetime, datetime, float]], start: datetime, end: datetime) -> float:
    """Average extra kW over [start, end] from events given as (starts_at, ends_at, delta_kw)."""
    span = (end - start).total_seconds()
    extra = 0.0
    for e_start, e_end, delta in events:
        overlap = (min(end, e_end) - max(start, e_start)).total_seconds()
        if overlap > 0:
            extra += delta * overlap / span
    return extra


def simulate_interval(
    p: SimProfile, end: datetime, events: list[tuple[datetime, datetime, float]] | None = None
) -> Interval:
    mid = end - INTERVAL / 2
    temp = ambient_temp_c(mid, p.serial)
    load = load_kw(p, mid) + event_kw(events or [], end - INTERVAL, end)
    pv = pv_kw(p.pv_kwp, mid, p.lat, p.lon, cloud_cover(mid, p.serial), temp)
    net = load - pv
    hours = INTERVAL_MIN / 60
    return Interval(end, round(load, 4), round(pv, 4), round(max(net, 0) * hours, 5), round(max(-net, 0) * hours, 5))
