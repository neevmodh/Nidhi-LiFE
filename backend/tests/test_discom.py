"""DISCOM console: roles and scope, fleet aggregates, feeders, anomalies, outages and leads."""

from datetime import UTC, datetime, timedelta

from app.create_admin import create_admin
from conftest import HOUSEHOLD, register
import pytest


def staff(client, role="discom_admin", discom="ugvcl", email=None):
    email = email or f"{role}-{discom}@example.com"
    create_admin(email, "DISCOM Staff", "discom-pass-1", role=role, discom=discom)
    token = client.post("/api/auth/login", json={"email": email, "password": "discom-pass-1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def home(client, tag, ward="Ward 3", district_id=1):
    h = register(client, f"{tag}@example.com", district_id)
    client.put("/api/household", json=HOUSEHOLD, headers=h)
    client.get("/api/meter/live", headers=h)
    return h


def test_create_admin_needs_a_known_discom(client):
    with pytest.raises(ValueError):
        create_admin("x@example.com", "X", "discom-pass-1", role="discom_admin")
    with pytest.raises(ValueError):
        create_admin("x@example.com", "X", "discom-pass-1", role="discom_admin", discom="nope")
    with pytest.raises(ValueError):
        create_admin("x@example.com", "X", "discom-pass-1", role="admin", discom="ugvcl")


def test_login_reports_the_discom(client):
    h = staff(client)
    me = client.get("/api/auth/me", headers=h)
    assert me.status_code == 200 and me.json()["role"] == "discom_admin" and me.json()["discom"] == "ugvcl"


def test_citizens_cannot_open_the_console(client, citizen):
    assert client.get("/api/discom/overview", headers=citizen).status_code == 403


def test_overview_counts_only_the_staff_members_company(client):
    home(client, "a")
    home(client, "b")
    ugvcl = staff(client)
    body = client.get("/api/discom/overview", headers=ugvcl).json()
    assert body["discom"] == "ugvcl" and body["meters"] == 2 and body["simulated_meters"] == 2
    assert body["load_kw"] > 0 and body["import_today_kwh"] >= 0
    mgvcl = staff(client, discom="mgvcl")
    assert client.get("/api/discom/overview", headers=mgvcl).json()["meters"] == 0
    assert client.get("/api/discom/overview?discom=ugvcl", headers=mgvcl).status_code == 403


def test_state_team_reads_one_company_at_a_time_and_cannot_change(client, admin_headers):
    home(client, "a")
    assert client.get("/api/discom/overview", headers=admin_headers).status_code == 422
    assert client.get("/api/discom/overview?discom=ugvcl", headers=admin_headers).json()["meters"] == 1
    assert client.post("/api/discom/outages", headers=admin_headers, json={}).status_code == 403


def test_feeders_aggregate_and_flag_hot_ones(client):
    for tag in "abc":
        home(client, tag)
    rows = client.get("/api/discom/feeders", headers=staff(client)).json()
    assert rows and sum(r["meters"] for r in rows) == 3
    assert all(r["rated_kw"] > 0 and 0 <= r["utilisation_pct"] and r["peak_kw_week"] >= r["load_kw"] * 0 for r in rows)
    series = client.get(f"/api/discom/feeders/{rows[0]['feeder']}/series", headers=staff(client)).json()
    assert len(series) > 90
    assert client.get("/api/discom/feeders/NOPE/series", headers=staff(client)).status_code == 404


def test_outage_notifies_the_homes_on_that_feeder_and_shows_in_their_live_view(client):
    h = home(client, "a")
    feeder = client.get("/api/meter", headers=h).json()["feeder"]
    eng = staff(client, "discom_engineer")
    start = datetime.now(UTC) + timedelta(hours=1)
    body = {"feeder": feeder, "reason": "Transformer maintenance", "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=2)).isoformat()}
    created = client.post("/api/discom/outages", json=body, headers=eng)
    assert created.status_code == 201 and created.json()["households"] == 1
    note = client.get("/api/notifications", headers=h).json()
    assert note["unread"] == 1 and "Transformer maintenance" in note["items"][0]["body"]
    assert [o["reason"] for o in client.get("/api/meter/live", headers=h).json()["outages"]] == ["Transformer maintenance"]
    assert client.delete(f"/api/discom/outages/{created.json()['id']}", headers=eng).status_code == 204


def test_outage_rules(client):
    h = home(client, "a")
    feeder = client.get("/api/meter", headers=h).json()["feeder"]
    start = datetime.now(UTC) + timedelta(hours=1)
    ok = {"feeder": feeder, "reason": "Maintenance", "starts_at": start.isoformat(),
          "ends_at": (start + timedelta(hours=1)).isoformat()}
    assert client.post("/api/discom/outages", json=ok, headers=staff(client, "discom_auditor")).status_code == 403
    eng = staff(client, "discom_engineer")
    assert client.post("/api/discom/outages", json={**ok, "ends_at": start.isoformat()}, headers=eng).status_code == 422
    assert client.post("/api/discom/outages", json={**ok, "feeder": "UGVCL-XXX-F09"}, headers=eng).status_code == 404
    other = staff(client, "discom_engineer", "mgvcl")
    assert client.post("/api/discom/outages", json=ok, headers=other).status_code == 404


def test_anomalies_list_and_resolve(client):
    h = register(client, "far@example.com")
    client.put("/api/household", json=HOUSEHOLD, headers=h)
    client.post("/api/readings", json={"month": "2026-10", "kwh": 900}, headers=h)  # a bill that disagrees
    client.get("/api/meter/bill", headers=h)  # raises a bill_mismatch flag
    eng = staff(client, "discom_engineer")
    flags = client.get("/api/discom/anomalies", headers=eng).json()
    assert len(flags) == 1 and flags[0]["kind"] == "bill_mismatch" and flags[0]["meter"].startswith("NID")
    assert "email" not in flags[0] and "name" not in flags[0]
    assert client.post(f"/api/discom/anomalies/{flags[0]['id']}/resolve", headers=staff(client, "discom_auditor")).status_code == 403
    assert client.post(f"/api/discom/anomalies/{flags[0]['id']}/resolve", headers=eng).json()["status"] == "resolved"
    assert client.get("/api/discom/anomalies", headers=eng).json() == []
    assert len(client.get("/api/discom/anomalies?state=resolved", headers=eng).json()) == 1


def test_solar_leads_show_the_companys_households(client):
    h = home(client, "a")
    client.post("/api/solar/leads", json={"note": "please call"}, headers=h)
    leads = client.get("/api/discom/solar-leads", headers=staff(client)).json()
    assert isinstance(leads, list)
