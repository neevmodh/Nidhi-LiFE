"""Accepting readings from a real meter: signature, replay window, and register monotonicity.

Ported from EcoPower 3.0's ingest worker (workers/ingest/{hmac,monotonicity}.ts). A device signs the
canonical JSON of its reading with its per-meter secret (HMAC-SHA256, hex). A reading is refused when the
signature is wrong, when it is too old (replay), or when it is from the future. A cumulative register
that goes backwards is not applied; it is returned as a rollback so the caller can raise an anomaly flag
for the DISCOM instead of silently corrupting the bill.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

REPLAY_WINDOW = timedelta(minutes=30)
FUTURE_SKEW = timedelta(minutes=5)

SIGNED_FIELDS = ("serial", "ts", "import_kwh", "export_kwh", "load_kw", "pv_kw")


def canonical(reading: dict) -> bytes:
    """The bytes a device signs: the signed fields only, sorted keys, no whitespace."""
    return json.dumps({k: reading[k] for k in SIGNED_FIELDS}, sort_keys=True, separators=(",", ":")).encode()


def sign(reading: dict, secret: str) -> str:
    return hmac.new(secret.encode(), canonical(reading), hashlib.sha256).hexdigest()


def verify(reading: dict, signature: str, secret: str) -> bool:
    return hmac.compare_digest(sign(reading, secret), signature)


def derive_secret(serial: str, jwt_secret: str) -> str:
    """Per-meter secret for a meter the platform itself provisions."""
    return hmac.new(jwt_secret.encode(), f"meter:{serial}".encode(), hashlib.sha256).hexdigest()


def within_replay_window(ts: datetime, now: datetime | None = None) -> bool:
    return (now or datetime.now(UTC)) - ts <= REPLAY_WINDOW


def from_the_future(ts: datetime, now: datetime | None = None) -> bool:
    return ts - (now or datetime.now(UTC)) > FUTURE_SKEW


@dataclass(frozen=True)
class Register:
    kind: str  # first | delta | rollback
    delta: float = 0.0


def evaluate_register(prior: float | None, new: float) -> Register:
    if prior is None:
        return Register("first")
    if new < prior:
        return Register("rollback", new - prior)
    return Register("delta", new - prior)
