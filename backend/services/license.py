"""
License service — validates on-premises JWT license keys.

Design:
  - SaaS mode (S2S_DEPLOY_MODE != 'onprem'): license checks are skipped entirely.
    Feature availability is controlled by quota_gate.py plan tiers instead.
  - On-prem mode (S2S_DEPLOY_MODE=onprem): the server reads S2S_LICENSE_KEY on
    startup, verifies the RS256 JWT against S2S_LICENSE_PUBLIC_KEY, and hard-stops
    if the key is missing, tampered, or expired.

License key format:
    S2S-<base64url(header)>.<base64url(payload)>.<base64url(signature)>

The S2S- prefix is stripped before JWT decode so standard PyJWT handles the rest.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class LicenseError(Exception):
    """Raised when the license is missing, expired, or invalid."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_deploy_mode_onprem() -> bool:
    """Return True when running in on-premises deployment mode."""
    return os.getenv("S2S_DEPLOY_MODE", "saas").lower() == "onprem"


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def validate_license() -> dict:
    """Load, verify, and cache the license payload.

    Must only be called in on-prem mode. Raises LicenseError on any failure.

    Returns:
        Decoded JWT payload dict.

    Raises:
        LicenseError: license key missing, invalid signature, or expired.
    """
    import jwt  # PyJWT — lazy import keeps startup fast in SaaS mode

    raw_key = os.getenv("S2S_LICENSE_KEY", "").strip()
    if not raw_key:
        raise LicenseError(
            "S2S_LICENSE_KEY is not set. "
            "Obtain a license at https://stream2stack.com/on-prem"
        )

    public_key_pem = os.getenv("S2S_LICENSE_PUBLIC_KEY", "").strip()
    if not public_key_pem:
        raise LicenseError(
            "S2S_LICENSE_PUBLIC_KEY is not set. "
            "This should be the RSA-2048 public key (PEM) provided with your license."
        )

    # Strip our S2S- vendor prefix before standard JWT decode
    token = raw_key.removeprefix("S2S-")

    try:
        payload = jwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        raise LicenseError(
            "License has expired. Renew at https://stream2stack.com/renew"
        )
    except jwt.InvalidTokenError as exc:
        raise LicenseError(f"Invalid license key: {exc}")

    return payload


# ---------------------------------------------------------------------------
# Feature & seat accessors
# ---------------------------------------------------------------------------


def is_feature_enabled(feature: str) -> bool:
    """Return True if the current on-prem license includes the named feature.

    Always returns False in SaaS mode (feature gates use quota_gate.py there).
    """
    if not is_deploy_mode_onprem():
        return False
    try:
        payload = validate_license()
        return bool(payload.get("features", {}).get(feature, False))
    except LicenseError:
        return False


def get_seat_limit() -> int | None:
    """Return the licensed seat limit, or None for unlimited.

    Fails closed to 1 seat on any error (license missing / invalid).
    """
    try:
        seats = validate_license().get("seats")
        return None if seats is None else int(seats)
    except LicenseError:
        return 1


# ---------------------------------------------------------------------------
# Status summary (used by GET /license/status)
# ---------------------------------------------------------------------------


def get_license_status() -> dict:
    """Return a structured status dict for the license status endpoint.

    Raises:
        LicenseError: if the license is invalid (caller should surface as 402).
    """
    payload = validate_license()

    expires_ts: int = payload.get("expires_at", 0)
    expires_dt = datetime.fromtimestamp(expires_ts, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    days_remaining = max(0, (expires_dt.date() - now.date()).days)

    return {
        "plan":            payload.get("plan"),
        "customer":        payload.get("customer_name"),
        "license_id":      payload.get("license_id"),
        "seats_licensed":  payload.get("seats"),       # None = unlimited
        "seats_active":    0,                           # seat counting is Phase B
        "expires_at":      expires_dt.date().isoformat(),
        "days_remaining":  days_remaining,
        "features":        payload.get("features", {}),
    }
