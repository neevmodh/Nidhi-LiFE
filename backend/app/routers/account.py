"""Your data, your call: download everything Nidhi holds about you, or erase it.

Deletion is permanent and complete: your account, household, bills, actions, push
devices and every proof photo you uploaded.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select, update

from app.deps import CurrentUser, DbSession
from app.models import (
    ActionLog,
    ActionType,
    Campaign,
    Duel,
    EnergyReading,
    Household,
    Meter,
    MeterEvent,
    MeterFlag,
    MeterReading,
    Notification,
    PushSubscription,
    Role,
    SocietyAnnouncement,
    SolarLead,
    User,
)
from app.ratelimit import client_ip, login_limiter
from app.routers.societies import remove_member
from app.security import verify_password
from app.storage import get_storage

router = APIRouter(prefix="/api/account", tags=["account"])
log = logging.getLogger(__name__)


class DeleteIn(BaseModel):
    password: str


def _meter_export(db, user) -> dict | None:
    """The household's meter and every reading stored for it (each reading is [time, import kWh, export kWh,
    load kW, solar kW]), plus anything flagged on it."""
    meter = db.scalar(select(Meter).where(Meter.user_id == user.id))
    if meter is None:
        return None
    rows = db.scalars(select(MeterReading).where(MeterReading.meter_id == meter.id).order_by(MeterReading.ts)).all()
    flags = db.scalars(select(MeterFlag).where(MeterFlag.meter_id == meter.id).order_by(MeterFlag.id)).all()
    return {
        "serial": meter.serial,
        "source": meter.source,
        "simulated": meter.source == "simulated",
        "feeder": meter.feeder,
        "solar_kwp": meter.pv_kwp,
        "reading_columns": ["time", "import_kwh", "export_kwh", "load_kw", "solar_kw"],
        "readings": [[r.ts.isoformat(), r.import_kwh, r.export_kwh, r.load_kw, r.pv_kw] for r in rows],
        "flags": [{"kind": f.kind, "detail": f.detail, "status": f.status, "raised": f.created_at.isoformat()} for f in flags],
    }


@router.get("/export")
def export_data(user: CurrentUser, db: DbSession):
    """Everything stored about the signed-in citizen, as a JSON file. Never includes the password hash."""
    h = user.household
    readings = db.scalars(select(EnergyReading).where(EnergyReading.user_id == user.id).order_by(EnergyReading.month)).all()
    actions = db.execute(
        select(ActionLog, ActionType.code)
        .join(ActionType, ActionType.id == ActionLog.action_type_id)
        .where(ActionLog.user_id == user.id)
        .order_by(ActionLog.created_at)
    ).all()
    devices = db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1))
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "about": "Everything Nidhi stores about you. Your password is stored only as a salted hash and is not included.",
        "account": {
            "name": user.name,
            "email": user.email,
            "district": user.district.name if user.district else None,
            "ward": user.ward,
            "joined": user.created_at.isoformat(),
        },
        "household": None
        if h is None
        else {
            c.name: getattr(h, c.name)
            for c in Household.__table__.columns
            if c.name not in ("user_id", "updated_at")
        },
        "bill_readings": [{"month": r.month.isoformat(), "kwh": r.kwh, "source": r.source} for r in readings],
        "actions": [
            {
                "when": a.created_at.isoformat(),
                "action": code,
                "status": a.status.value,
                "points": a.points_awarded,
                "co2_saved_kg": a.co2_saved_kg,
                "kwh_saved": a.kwh_saved,
                "note": a.note,
                "has_photo_proof": a.proof_path is not None,
                "ai_screening": a.ai_verdict,
            }
            for a, code in actions
        ],
        "solar_survey_requests": [
            {"when": lead.created_at.isoformat(), "kwp": lead.kwp, "roof_area_sqm": lead.roof_area_sqm,
             "status": lead.status, "note": lead.note}
            for lead in db.scalars(select(SolarLead).where(SolarLead.user_id == user.id)).all()
        ],
        "alerts_enabled_on_a_device": devices is not None,
        "smart_meter": _meter_export(db, user),
    }
    body = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"nidhi-my-data-{datetime.now(timezone.utc):%Y%m%d}.json"
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(body: DeleteIn, user: CurrentUser, db: DbSession, request: Request):
    """Permanently erase the account and everything attached to it. Needs the password."""
    if user.role != Role.citizen:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "GEDA staff accounts are removed by the state team, not here")
    login_limiter.check(f"{client_ip(request)}:delete:{user.id}")  # a stolen session can't guess the password
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That password isn't right")

    photos = db.scalars(
        select(ActionLog.proof_path).where(ActionLog.user_id == user.id, ActionLog.proof_path.is_not(None))
    ).all()
    storage = get_storage()
    failed = 0
    for name in photos:
        try:
            await storage.delete(name)
        except Exception:  # noqa: BLE001  (best effort per photo; the database rows are removed regardless)
            failed += 1
    if failed:
        log.warning("Account %s deleted but %s proof photo(s) could not be removed from storage", user.id, failed)

    if user.society_member:
        remove_member(db, user.society_member)
    db.execute(delete(SocietyAnnouncement).where(SocietyAnnouncement.author_id == user.id))
    # Duels and campaigns this person started carry on for everyone else; they just lose the author.
    for model in (Duel, Campaign):
        db.execute(update(model).where(model.created_by == user.id).values(created_by=None))
    # The smart meter goes with the account: its readings, simulated events and flags first (they point at it).
    meter_ids = select(Meter.id).where(Meter.user_id == user.id)
    for model in (MeterReading, MeterEvent, MeterFlag):
        db.execute(delete(model).where(model.meter_id.in_(meter_ids)))
    db.execute(delete(Meter).where(Meter.user_id == user.id))
    for model in (Notification, PushSubscription, SolarLead, ActionLog, EnergyReading, Household):
        db.execute(delete(model).where(model.user_id == user.id))
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
