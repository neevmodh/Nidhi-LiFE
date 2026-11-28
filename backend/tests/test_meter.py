"""Smart meter: the simulator, lazy catch-up, live and bill endpoints, the agent, and signed ingest."""

from datetime import UTC, datetime, timedelta

from conftest import HOUSEHOLD, register
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Meter, MeterFlag, MeterReading
from app.services import meter_ingest, meter_sim

PROFILE = meter_sim.SimProfile("NID0000001", 23.03, 72.58, 300, 2, True, False, 3.0)


def test_simulator_is_deterministic_and_calibrated():
    t0 = datetime(2026, 4, 15, tzinfo=UTC)
    a = meter_sim.simulate_interval(PROFILE, t0 + meter_sim.INTERVAL)
    b = meter_sim.simulate_interval(PROFILE, t0 + meter_sim.INTERVAL)
    assert a == b
    no_pv = meter_sim.SimProfile("NID0000001", 23.03, 72.58, 300, 2, True, False, 0.0)
    load = sum(meter_sim.simulate_interval(no_pv, t0 + meter_sim.INTERVAL * (i + 1)).load_kw * 0.25 for i in range(96 * 30))
    assert 240 < load < 380  # a month of the 300 kWh household, give or take the season and jitter


def test_solar_only_in_daylight_and_never_negative():
    night = datetime(2026, 4, 15, 20, 0, tzinfo=UTC)  # 1:30 IST
    noon = datetime(2026, 4, 15, 6, 30, tzinfo=UTC)  # noon IST
    assert meter_sim.simulate_interval(PROFILE, night).pv_kw == 0
    sun = meter_sim.simulate_interval(PROFILE, noon)
    assert sun.pv_kw > 1 and sun.import_kwh >= 0 and sun.export_kwh >= 0


def test_appliance_event_adds_load():
    end = datetime(2026, 4, 15, 6, 30, tzinfo=UTC)
    base = meter_sim.simulate_interval(PROFILE, end)
    boosted = meter_sim.simulate_interval(PROFILE, end, [(end - timedelta(minutes=15), end, 1.5)])
    assert round(boosted.load_kw - base.load_kw, 3) == 1.5


def test_live_creates_a_labelled_simulated_meter_with_a_week_of_history(client, citizen):
    resp = client.get("/api/meter/live", headers=citizen)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meter"]["simulated"] is True and body["meter"]["source"] == "simulated"
    assert len(body["series"]) >= 90  # the last 24 hours of 15-minute readings
    with SessionLoc() as db:
        assert db.scalar(select(func.count(MeterReading.id))) >= 672


def test_registers_only_go_up_and_catch_up_is_idempotent(client, citizen):
    client.get("/api/meter/live", headers=citizen)
    client.get("/api/meter/live", headers=citizen)
    with SessionLoc() as db:
        rows = db.scalars(select(MeterReading).order_by(MeterReading.ts)).all()
        assert all(b.import_kwh >= a.import_kwh and b.export_kwh >= a.export_kwh for a, b in zip(rows, rows[1:]))
        assert len({r.ts for r in rows}) == len(rows)


def test_meter_needs_onboarding(client):
    headers = register(client)
    assert client.get("/api/meter/live", headers=headers).status_code == 409


def test_bill_comes_from_meter_units_and_splits_exactly(client, citizen):
    body = client.get("/api/meter/bill", headers=citizen).json()
    split = body["breakdown"]
    assert split["total_rs"] == body["projected_bill_rs"]
    assert round(split["energy_rs"] + split["fixed_rs"] + split["fppas_rs"] + split["duty_rs"], 2) == split["total_rs"]
    assert body["simulated"] is True


def test_a_bill_far_from_the_meter_raises_one_flag_and_a_complaint(client):
    headers = register(client, "far@example.com")
    assert client.put("/api/household", json=HOUSEHOLD, headers=headers).status_code == 200
    # A bill photo says 900 units a month; the meter says about 300.
    assert client.post("/api/readings", json={"month": "2026-10", "kwh": 900}, headers=headers).status_code in (200, 201)
    body = client.get("/api/meter/bill", headers=headers).json()
    assert body["mismatch"] and body["complaint"]["subject"]
    client.get("/api/meter/bill", headers=headers)
    with SessionLoc() as db:
        assert db.scalar(select(func.count(MeterFlag.id)).where(MeterFlag.kind == "bill_mismatch")) == 1


def test_agent_ranks_actions_and_only_uses_given_numbers(client, citizen):
    body = client.get("/api/meter/agent", headers=citizen).json()
    assert [s["tool"] for s in body["steps"]] == ["read_meter", "profile_week", "price_tariff", "reconcile_bill", "rank_actions"]
    recs = body["recommendations"]
    assert recs and recs == sorted(recs, key=lambda r: (-r["rs_month"], -r["co2_kg_month"]))
    assert body["written_by_ai"] is False and body["summary"]


def test_meter_confirms_a_shifted_load_and_awards_verified_points(client, citizen):
    refused = client.post("/api/meter/agent/confirm", json={"code": "shift_heavy_load"}, headers=citizen)
    assert refused.status_code == 409  # nothing on the meter yet
    assert client.post("/api/meter/appliance", json={"kind": "ev_charger"}, headers=citizen).status_code == 201
    # The EV ran for two hours up to now: confirmed if that was outside the evening peak, else still refused.
    resp = client.post("/api/meter/agent/confirm", json={"code": "shift_heavy_load"}, headers=citizen)
    hour = (datetime.now(UTC) + timedelta(hours=5.5)).hour
    if 18 <= hour < 22:
        assert resp.status_code == 409
    else:
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "verified" and resp.json()["points_awarded"] > 0
        assert resp.json()["has_proof"] is False


def test_appliance_events_are_refused_on_a_real_meter(client, citizen):
    client.post("/api/meter/link", headers=citizen)
    assert client.post("/api/meter/appliance", json={"kind": "geyser"}, headers=citizen).status_code == 409


# --- Signed ingest -------------------------------------------------------------------


class SessionLoc:
    def __enter__(self):
        self.db = SessionLocal()
        return self.db

    def __exit__(self, *exc):
        self.db.close()


def _linked(client, citizen):
    info = client.post("/api/meter/link", headers=citizen).json()
    return info["serial"], info["secret"]


def _signed(serial, secret, ts=None, imp=1000.0, exp=0.0, fmt="z"):
    ts = ts or datetime.now(UTC)
    sent = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if fmt == "z" else ts.isoformat()
    reading = {"serial": serial, "ts": sent, "import_kwh": imp, "export_kwh": exp, "load_kw": 0.5, "pv_kw": 0.0}
    return {**reading, "signature": meter_ingest.sign(reading, secret)}


def test_signed_reading_is_accepted_and_shows_as_a_real_meter(client, citizen):
    serial, secret = _linked(client, citizen)
    assert client.post("/api/meter/readings", json=_signed(serial, secret)).status_code == 201
    live = client.get("/api/meter/live", headers=citizen).json()
    assert live["meter"]["simulated"] is False and live["load_kw"] == 0.5


def test_forged_unknown_and_simulated_meters_are_refused(client, citizen):
    serial, secret = _linked(client, citizen)
    bad = _signed(serial, secret)
    bad["load_kw"] = 9.0  # changed after signing
    assert client.post("/api/meter/readings", json=bad).status_code == 401
    assert client.post("/api/meter/readings", json=_signed("NOPE", secret)).status_code == 401
    other = register(client, "other@example.com")
    client.put("/api/household", json=HOUSEHOLD, headers=other)
    client.get("/api/meter/live", headers=other)  # a simulated meter
    with SessionLoc() as db:
        sim = db.scalar(select(Meter).where(Meter.source == "simulated"))
        sim_serial, sim_secret = sim.serial, sim.secret
    assert client.post("/api/meter/readings", json=_signed(sim_serial, sim_secret)).status_code == 401


def test_replayed_and_future_readings_are_refused(client, citizen):
    serial, secret = _linked(client, citizen)
    old = _signed(serial, secret, datetime.now(UTC) - timedelta(hours=2))
    assert client.post("/api/meter/readings", json=old).status_code == 422
    future = _signed(serial, secret, datetime.now(UTC) + timedelta(hours=1))
    assert client.post("/api/meter/readings", json=future).status_code == 422


def test_a_register_going_backwards_is_not_applied_and_is_flagged(client, citizen):
    serial, secret = _linked(client, citizen)
    t = datetime.now(UTC) - timedelta(minutes=10)
    assert client.post("/api/meter/readings", json=_signed(serial, secret, t, imp=1000.0)).status_code == 201
    back = client.post("/api/meter/readings", json=_signed(serial, secret, t + timedelta(minutes=5), imp=990.0))
    assert back.status_code == 409
    with SessionLoc() as db:
        assert db.scalar(select(func.count(MeterFlag.id)).where(MeterFlag.kind == "register_rollback")) == 1
        assert db.scalar(select(func.count(MeterReading.id))) == 1


def test_duplicate_timestamp_is_refused(client, citizen):
    serial, secret = _linked(client, citizen)
    t = datetime.now(UTC) - timedelta(minutes=1)
    assert client.post("/api/meter/readings", json=_signed(serial, secret, t)).status_code == 201
    assert client.post("/api/meter/readings", json=_signed(serial, secret, t, imp=1001.0)).status_code == 409


# --- Society energy ------------------------------------------------------------------


def _society(client, size):
    from app.routers.societies import MIN_GROUP_SIZE  # noqa: F401

    people = []
    for i in range(size):
        h = register(client, f"s{i}@example.com")
        client.put("/api/household", json=HOUSEHOLD, headers=h)
        people.append(h)
    s = client.post("/api/societies", json={"name": "Green Heights", "kind": "society"}, headers=people[0]).json()
    for h in people[1:]:
        client.post("/api/societies/join", json={"code": s["join_code"]}, headers=h)
    return people


def test_society_energy_hidden_until_enough_homes_have_meters(client):
    from app.routers.societies import MIN_GROUP_SIZE

    people = _society(client, MIN_GROUP_SIZE)
    for h in people[: MIN_GROUP_SIZE - 1]:
        client.get("/api/meter/live", headers=h)
    hidden = client.get("/api/meter/society", headers=people[0]).json()
    assert hidden["visible"] is False and hidden["homes"] == MIN_GROUP_SIZE - 1 and hidden["series"] == []
    client.get("/api/meter/live", headers=people[-1])
    shown = client.get("/api/meter/society", headers=people[0]).json()
    assert shown["visible"] is True and shown["homes"] == MIN_GROUP_SIZE and shown["load_kw"] > 0
    assert len(shown["series"]) > 90


def test_society_energy_needs_a_society(client, citizen):
    assert client.get("/api/meter/society", headers=citizen).status_code == 404


def test_timestamps_carry_a_timezone_so_every_client_reads_the_same_instant(client, citizen):
    live = client.get("/api/meter/live", headers=citizen).json()
    for ts in (live["ts"], live["series"][0]["ts"]):
        assert ts.endswith("Z") or ts.endswith("+00:00"), ts


def test_projection_uses_the_span_the_readings_cover(client, citizen):
    """A meter with a week of readings must project a full month from that week, not from the whole month so far."""
    bill = client.get("/api/meter/bill", headers=citizen).json()
    # The household said 300 kWh a month; the simulator is calibrated to it, give or take the season.
    assert 0.6 * 300 < bill["projected_load_kwh"] < 1.5 * 300
    assert bill["mismatch"] is False


def test_signature_is_over_text_so_any_language_can_produce_it(client, citizen):
    """A device in another language signs "|"-joined text; Z or +00:00 timestamps and 1000 or 1000.0 all work."""
    import hashlib
    import hmac

    serial, secret = _linked(client, citizen)
    now = datetime.now(UTC) - timedelta(minutes=2)
    for i, (ts, imp) in enumerate([(now.strftime("%Y-%m-%dT%H:%M:%SZ"), "1000"), ((now + timedelta(minutes=1)).isoformat(), "1000.250")]):
        text = f"{serial}|{ts}|{float(imp):.3f}|0.000|0.5000|0.0000"
        sig = hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()
        body = {"serial": serial, "ts": ts, "import_kwh": float(imp), "export_kwh": 0, "load_kw": 0.5, "pv_kw": 0, "signature": sig}
        assert client.post("/api/meter/readings", json=body).status_code == 201, i


def test_a_signed_reading_with_an_unparseable_time_is_refused(client, citizen):
    serial, secret = _linked(client, citizen)
    bad = {"serial": serial, "ts": "yesterday", "import_kwh": 1, "export_kwh": 0, "load_kw": 0, "pv_kw": 0}
    resp = client.post("/api/meter/readings", json={**bad, "signature": meter_ingest.sign(bad, secret)})
    assert resp.status_code == 422


# --- Account export and deletion -----------------------------------------------------


def test_deleting_an_account_removes_its_meter_and_everything_on_it(client, citizen):
    from app.models import Meter, MeterEvent

    client.get("/api/meter/live", headers=citizen)
    client.post("/api/meter/appliance", json={"kind": "geyser"}, headers=citizen)
    client.post("/api/readings", json={"month": "2026-10", "kwh": 900}, headers=citizen)
    client.get("/api/meter/bill", headers=citizen)  # raises a flag
    with SessionLoc() as db:
        assert db.scalar(select(func.count(MeterReading.id))) > 0
        assert db.scalar(select(func.count(MeterFlag.id))) == 1
        assert db.scalar(select(func.count(MeterEvent.id))) == 1
    assert client.request("DELETE", "/api/account", json={"password": "secret123"}, headers=citizen).status_code == 204
    with SessionLoc() as db:
        for model in (Meter, MeterReading, MeterFlag, MeterEvent):
            assert db.scalar(select(func.count(model.id))) == 0, model.__name__


def test_the_export_includes_the_meter_and_its_readings(client, citizen):
    import json

    client.get("/api/meter/live", headers=citizen)
    data = json.loads(client.get("/api/account/export", headers=citizen).text)
    meter = data["smart_meter"]
    assert meter["simulated"] is True and meter["serial"].startswith("NID") and len(meter["readings"]) >= 672
    assert meter["reading_columns"] == ["time", "import_kwh", "export_kwh", "load_kw", "solar_kw"]


def test_the_export_has_no_meter_when_there_is_none(client, citizen):
    import json

    assert json.loads(client.get("/api/account/export", headers=citizen).text)["smart_meter"] is None


def test_fleet_usage_equals_per_meter_usage(client):
    """usage_many (two queries for the whole fleet) must agree with usage_between (one meter) for every meter."""
    from app.models import User
    from app.services import meter as svc
    from app.timeutil import ist_day_bounds_utc, today_ist

    for i in range(3):
        h = register(client, f"fleet{i}@example.com")
        client.put("/api/household", json={**HOUSEHOLD, "monthly_kwh": 200 + 100 * i}, headers=h)
        client.get("/api/meter/live", headers=h)
    client.post("/api/meter/link", headers=register(client, "dev@example.com"))  # no household: ignored below
    start, end = ist_day_bounds_utc(today_ist())
    with SessionLoc() as db:
        meters = list(db.scalars(select(Meter)))
        many = svc.usage_many(db, meters, start, min(datetime.now(UTC), end))
        for m in meters:
            assert many[m.id] == svc.usage_between(db, m, start, min(datetime.now(UTC), end)), m.serial
        _ = User  # the users exist; nothing else to check
    assert svc.usage_many(SessionLocal(), [], start, end) == {}
