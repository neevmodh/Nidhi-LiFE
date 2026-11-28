"""The public demo logins: they exist, work, are idempotent, can be turned off, and can change nothing."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Household, Role, User
from app.seed import (
    DEMO_DISCOM_EMAIL,
    DEMO_GEDA_EMAIL,
    DEMO_HOUSEHOLD_EMAIL,
    ensure_demo_accounts,
)


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": get_settings().demo_password})
    assert r.status_code == 200, (email, r.text)
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def seed():
    with SessionLocal() as db:
        return ensure_demo_accounts(db)


def test_all_three_demo_accounts_sign_in_with_the_published_password(client):
    assert seed() == [DEMO_HOUSEHOLD_EMAIL, DEMO_DISCOM_EMAIL, DEMO_GEDA_EMAIL]
    _, household = login(client, DEMO_HOUSEHOLD_EMAIL)
    _, discom = login(client, DEMO_DISCOM_EMAIL)
    _, geda = login(client, DEMO_GEDA_EMAIL)
    assert household["role"] == "citizen" and household["onboarded"] is True
    assert discom["role"] == "discom_auditor" and discom["discom"] == "ugvcl"
    assert geda["role"] == "auditor"


def test_seeding_twice_changes_nothing_and_repairs_a_changed_password(client):
    seed()
    with SessionLocal() as db:
        db.execute(User.__table__.update().where(User.email == DEMO_DISCOM_EMAIL).values(password_hash="x"))
        db.commit()
    seed()
    login(client, DEMO_DISCOM_EMAIL)
    with SessionLocal() as db:
        assert db.scalar(select(func.count(User.id)).where(User.email.like("demo-%@example.com"))) == 3
        assert db.scalar(select(func.count(Household.user_id))) == 1


def test_the_demo_household_has_a_working_meter_and_agent(client):
    seed()
    headers, _ = login(client, DEMO_HOUSEHOLD_EMAIL)
    live = client.get("/api/meter/live", headers=headers).json()
    assert live["meter"]["simulated"] is True and live["meter"]["pv_kwp"] > 0 and len(live["series"]) > 90
    assert client.get("/api/meter/agent", headers=headers).json()["recommendations"]


def test_the_demo_staff_can_look_but_cannot_change_anything(client):
    seed()
    home, _ = login(client, DEMO_HOUSEHOLD_EMAIL)
    client.get("/api/meter/live", headers=home)
    feeder = client.get("/api/meter", headers=home).json()["feeder"]
    discom, _ = login(client, DEMO_DISCOM_EMAIL)
    geda, _ = login(client, DEMO_GEDA_EMAIL)
    assert client.get("/api/discom/overview", headers=discom).json()["meters"] == 1
    assert client.get("/api/admin/overview", headers=geda).status_code == 200
    start = datetime.now(UTC) + timedelta(hours=1)
    outage = {"feeder": feeder, "reason": "Test", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    assert client.post("/api/discom/outages", json=outage, headers=discom).status_code == 403  # a public password cannot notify households
    assert client.post("/api/discom/anomalies/1/resolve", headers=discom).status_code == 403
    assert client.post("/api/admin/reviews/1", json={"approve": True}, headers=geda).status_code == 403
    assert client.get("/api/discom/overview", headers=geda).status_code == 422  # the state team picks a company; it still cannot write
    with SessionLocal() as db:
        assert db.scalar(select(User.role).where(User.email == DEMO_DISCOM_EMAIL)) == Role.discom_auditor


def test_demo_accounts_can_be_turned_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_accounts", False)
    assert seed() == []
    assert client.post("/api/auth/login", json={"email": DEMO_DISCOM_EMAIL, "password": get_settings().demo_password}).status_code == 401


def test_the_demo_fleet_fills_the_discom_console_and_is_idempotent(client):
    from app.seed import DEMO_FLEET_SIZE, ensure_demo_fleet

    seed()
    with SessionLocal() as db:
        assert ensure_demo_fleet(db) == DEMO_FLEET_SIZE
        assert ensure_demo_fleet(db) == DEMO_FLEET_SIZE  # a second start adds nothing
    discom, _ = login(client, DEMO_DISCOM_EMAIL)
    overview = client.get("/api/discom/overview", headers=discom).json()
    assert overview["meters"] == DEMO_FLEET_SIZE and overview["simulated_meters"] == DEMO_FLEET_SIZE
    assert overview["open_flags"] == 5 and overview["active_outages"] == 3 and overview["solar_leads"] == 6
    feeders = client.get("/api/discom/feeders", headers=discom).json()
    assert len(feeders) >= 3 and all(f["meters"] >= 1 for f in feeders)
    assert len(client.get("/api/discom/series", headers=discom).json()) > 90
    assert len(client.get("/api/discom/anomalies?state=all", headers=discom).json()) == 7
    assert len(client.get("/api/discom/outages", headers=discom).json()) == 3
    assert len(client.get("/api/discom/solar-leads", headers=discom).json()) == 6
    with SessionLocal() as db:
        assert db.scalar(select(func.count(User.id)).where(User.email.like("demo-home-%@example.com"))) == DEMO_FLEET_SIZE
