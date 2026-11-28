"""Who can reach what: every meter and DISCOM endpoint against every kind of caller, plus bad input."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import HOUSEHOLD, register

from app.create_admin import create_admin

GET_DISCOM = ["/api/discom/overview", "/api/discom/series", "/api/discom/feeders", "/api/discom/anomalies",
              "/api/discom/outages", "/api/discom/solar-leads"]
GET_METER = ["/api/meter", "/api/meter/live", "/api/meter/day", "/api/meter/bill", "/api/meter/agent", "/api/meter/society"]


def login(client, email, password="staff-pass-1"):
    token = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def staff(client, role, discom=None, district=None, email=None):
    email = email or f"{role}-{discom or district}@example.com"
    create_admin(email, "Staff", "staff-pass-1", role=role, discom=discom, district=district)
    return login(client, email)


@pytest.mark.parametrize("path", GET_METER + GET_DISCOM)
def test_every_endpoint_needs_a_sign_in(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", GET_DISCOM)
def test_citizens_and_geda_district_staff_cannot_open_the_discom_console(client, citizen, path):
    assert client.get(path, headers=citizen).status_code == 403
    officer = staff(client, "officer", district="ahmedabad")
    reviewer = staff(client, "reviewer", email="rev@example.com")
    assert client.get(path, headers=officer).status_code == 403
    assert client.get(path, headers=reviewer).status_code == 403


@pytest.mark.parametrize("path", GET_DISCOM)
def test_the_three_discom_roles_can_read(client, path):
    for role in ("discom_admin", "discom_engineer", "discom_auditor"):
        assert client.get(path, headers=staff(client, role, "ugvcl")).status_code == 200, (role, path)


def test_only_admins_and_engineers_can_change_things(client):
    home = register(client, "h@example.com")
    client.put("/api/household", json=HOUSEHOLD, headers=home)
    feeder = client.get("/api/meter", headers=home).json()["feeder"]
    start = datetime.now(UTC) + timedelta(hours=1)
    body = {"feeder": feeder, "reason": "Maintenance", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    for role, ok in (("discom_auditor", False), ("discom_engineer", True), ("discom_admin", True)):
        h = staff(client, role, "ugvcl")
        resp = client.post("/api/discom/outages", json=body, headers=h)
        assert (resp.status_code == 201) is ok, (role, resp.status_code)
        if ok:
            assert client.delete(f"/api/discom/outages/{resp.json()['id']}", headers=h).status_code == 204
        else:
            assert client.delete("/api/discom/outages/1", headers=h).status_code == 403


def test_an_engineer_cannot_touch_another_companys_outage_or_flag(client):
    home = register(client, "h@example.com")
    client.put("/api/household", json=HOUSEHOLD, headers=home)
    feeder = client.get("/api/meter", headers=home).json()["feeder"]
    start = datetime.now(UTC) + timedelta(hours=1)
    mine = staff(client, "discom_engineer", "ugvcl")
    other = staff(client, "discom_engineer", "mgvcl")
    outage = client.post("/api/discom/outages", json={"feeder": feeder, "reason": "Maintenance", "starts_at": start.isoformat(),
                                                      "ends_at": (start + timedelta(hours=1)).isoformat()}, headers=mine).json()
    assert client.delete(f"/api/discom/outages/{outage['id']}", headers=other).status_code == 404
    assert client.get("/api/discom/outages", headers=other).json() == []
    assert client.post("/api/discom/anomalies/999/resolve", headers=other).status_code == 404


def test_the_company_parameter_is_validated(client, admin_headers):
    assert client.get("/api/discom/overview?discom=UGVCL", headers=admin_headers).status_code == 422  # not lower case
    assert client.get("/api/discom/overview?discom=ugvcl;drop", headers=admin_headers).status_code == 422
    assert client.get("/api/discom/overview?discom=nothere", headers=admin_headers).status_code == 404
    assert client.get("/api/discom/feeders/x/series?hours=0", headers=staff(client, "discom_admin", "ugvcl")).status_code == 422
    assert client.get("/api/discom/series?hours=999", headers=staff(client, "discom_admin", "ugvcl")).status_code == 422


def test_the_console_never_exposes_who_lives_where(client):
    home = register(client, "private.person@example.com")
    client.put("/api/household", json=HOUSEHOLD, headers=home)
    client.get("/api/meter/live", headers=home)
    client.post("/api/readings", json={"month": "2026-10", "kwh": 900}, headers=home)
    client.get("/api/meter/bill", headers=home)
    h = staff(client, "discom_admin", "ugvcl")
    text = "".join(client.get(p, headers=h).text for p in GET_DISCOM + ["/api/discom/feeders"])
    for secret in ("private.person", "Asha", "Ward 3", "example.com/"):
        assert secret not in text


# --- Bad input ---------------------------------------------------------------------


@pytest.mark.parametrize("patch", [
    {"import_kwh": -1}, {"export_kwh": -0.5}, {"load_kw": 1000}, {"pv_kw": -3},
    {"serial": "X" * 40}, {"ts": "T" * 60}, {"signature": "s" * 200},
])
def test_ingest_rejects_out_of_range_fields(client, patch):
    body = {"serial": "NID0000001", "ts": "2026-11-28T10:00:00Z", "import_kwh": 1, "export_kwh": 0, "load_kw": 0.5, "pv_kw": 0,
            "signature": "00", **patch}
    assert client.post("/api/meter/readings", json=body).status_code == 422


def test_ingest_needs_every_field(client):
    assert client.post("/api/meter/readings", json={"serial": "NID0000001"}).status_code == 422
    assert client.post("/api/meter/readings", content="not json", headers={"Content-Type": "application/json"}).status_code == 422


def test_outage_validation(client):
    home = register(client, "h@example.com")
    client.put("/api/household", json=HOUSEHOLD, headers=home)
    feeder = client.get("/api/meter", headers=home).json()["feeder"]
    eng = staff(client, "discom_engineer", "ugvcl")
    t = datetime.now(UTC) + timedelta(hours=1)
    good = {"feeder": feeder, "reason": "Maintenance", "starts_at": t.isoformat(), "ends_at": (t + timedelta(hours=1)).isoformat()}
    for bad in ({"reason": "x"}, {"reason": "y" * 201}, {"feeder": "ab"}, {"starts_at": "not a time"}, {"ends_at": good["starts_at"]}):
        assert client.post("/api/discom/outages", json={**good, **bad}, headers=eng).status_code == 422, bad
    assert client.post("/api/discom/outages", json=good, headers=eng).status_code == 201


def test_appliance_and_confirm_only_accept_known_values(client, citizen):
    assert client.post("/api/meter/appliance", json={"kind": "toaster"}, headers=citizen).status_code == 422
    assert client.post("/api/meter/agent/confirm", json={"code": "led_switch"}, headers=citizen).status_code == 422


def test_a_second_meter_link_and_a_second_confirm_per_day_are_refused(client, citizen):
    assert client.post("/api/meter/link", headers=citizen).status_code == 200
    assert client.post("/api/meter/link", headers=citizen).status_code == 409


def test_the_daily_cap_applies_to_meter_confirmed_actions(client, citizen):
    hour = (datetime.now(UTC) + timedelta(hours=5.5)).hour
    if 18 <= hour < 22:
        pytest.skip("the meter never confirms a load during the evening peak")
    client.post("/api/meter/appliance", json={"kind": "ev_charger"}, headers=citizen)
    codes = [client.post("/api/meter/agent/confirm", json={"code": "shift_heavy_load"}, headers=citizen).status_code for _ in range(4)]
    assert codes[0] == 201 and 429 in codes  # max_per_day is 2, then the cap
    assert all(c in (201, 429) for c in codes)
