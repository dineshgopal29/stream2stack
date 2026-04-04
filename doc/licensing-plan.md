# Licensing Plan — Stream2Stack

**Version:** 1.1
**Date:** 2026-04-03
**Status:** Partially Implemented (Phase A complete)

---

## 1. Overview

Stream2Stack requires two distinct licensing strategies:

1. **SaaS licensing** — terms of service + subscription agreement; enforced via
   Stripe + quota gates; no license key required.
2. **On-Premises licensing** — cryptographic license key that controls feature
   flags, seat limits, and expiry; enforced by a license agent running alongside
   the application.

---

## 2. License Key Design

### 2.1 Key Structure

License keys are JWT-like payloads signed with our RSA-2048 private key.
The customer holds the signed token; we hold the signing key.

```
Format: S2S-<base64url(header)>.<base64url(payload)>.<base64url(signature)>

Header:
{
  "alg": "RS256",
  "typ": "S2S-LICENSE",
  "version": 1
}

Payload:
{
  "license_id":     "lic_abc123",
  "customer_id":    "cust_xyz789",
  "customer_name":  "Acme Corp",
  "plan":           "professional",    // 'standard' | 'professional' | 'enterprise'
  "seats":          10,                // max concurrent users; null = unlimited
  "issued_at":      1743724800,        // Unix epoch
  "expires_at":     1775260800,        // 1-year validity
  "features": {
    "custom_prompts":   true,
    "audit_logs":       true,
    "sso":              false,
    "white_label":      false,
    "air_gap":          false
  },
  "checksum":       "sha256:<hash of customer_id+plan+expires_at>"
}
```

### 2.2 License Validation (Python)

```python
# backend/services/license.py
import jwt
import os
from datetime import datetime, timezone
from functools import lru_cache

_PUBLIC_KEY = os.getenv("S2S_LICENSE_PUBLIC_KEY", "")  # PEM format, baked into binary

@lru_cache(maxsize=1)
def validate_license() -> dict:
    """Load, verify, and cache the license payload.

    Raises LicenseError if:
    - S2S_LICENSE_KEY env var is not set
    - Signature is invalid (tampered key)
    - License has expired
    - Seat count exceeded (checked separately at runtime)
    """
    raw_key = os.getenv("S2S_LICENSE_KEY", "")
    if not raw_key:
        raise LicenseError("S2S_LICENSE_KEY not set. Obtain a license at stream2stack.com")

    # Strip our prefix
    token = raw_key.removeprefix("S2S-")

    try:
        payload = jwt.decode(token, _PUBLIC_KEY, algorithms=["RS256"])
    except jwt.ExpiredSignatureError:
        raise LicenseError("License has expired. Renew at stream2stack.com/renew")
    except jwt.InvalidTokenError as e:
        raise LicenseError(f"Invalid license key: {e}")

    return payload


def is_feature_enabled(feature: str) -> bool:
    """Return True if the current license includes the named feature."""
    try:
        payload = validate_license()
        return payload.get("features", {}).get(feature, False)
    except LicenseError:
        return False


def get_seat_limit() -> int | None:
    """Return max seats, or None if unlimited."""
    try:
        return validate_license().get("seats")
    except LicenseError:
        return 1  # fail closed to 1 seat


class LicenseError(Exception):
    """Raised when the license is missing, expired, or invalid."""
```

### 2.3 Startup License Check

```python
# backend/main.py — lifespan startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    mode = os.getenv("S2S_DEPLOY_MODE", "saas")  # 'saas' | 'onprem'

    if mode == "onprem":
        try:
            payload = validate_license()
            logger.info(
                "License valid: plan=%s, customer=%s, expires=%s",
                payload["plan"],
                payload["customer_name"],
                datetime.fromtimestamp(payload["expires_at"]).date(),
            )
        except LicenseError as e:
            logger.critical("LICENSE INVALID — server will not start: %s", e)
            raise SystemExit(1)  # hard stop: no license, no service

    yield  # app runs
```

---

## 3. License Enforcement Points

### 3.1 Feature Gates (On-Prem)

```python
# Example: custom prompts gate
@router.put("/prompts/system")
async def update_system_prompt(body: PromptUpdateRequest):
    if os.getenv("S2S_DEPLOY_MODE") == "onprem":
        if not is_feature_enabled("custom_prompts"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "license_feature_unavailable",
                    "feature": "custom_prompts",
                    "upgrade_url": "https://stream2stack.com/upgrade",
                }
            )
    # proceed...
```

### 3.2 Seat Enforcement (On-Prem)

```python
# backend/services/seat_manager.py
async def check_seat_available(user_id: str) -> None:
    """Block login if seat limit is reached."""
    limit = get_seat_limit()
    if limit is None:
        return  # unlimited

    active_count = await count_active_sessions()  # sessions in last 30 days
    if active_count >= limit and not await user_has_active_session(user_id):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "seat_limit_reached",
                "seats_used": active_count,
                "seats_licensed": limit,
            }
        )
```

### 3.3 Expiry Enforcement

- License check on every server startup — hard stop if expired
- 30-day warning logged daily when < 30 days remain
- Banner in UI when < 14 days remain
- License API endpoint: `GET /license/status` (on-prem only)

```json
{
  "plan": "professional",
  "customer": "Acme Corp",
  "seats_licensed": 10,
  "seats_active": 7,
  "expires_at": "2027-04-01",
  "days_remaining": 365,
  "features": {
    "custom_prompts": true,
    "audit_logs": true,
    "sso": false
  }
}
```

---

## 4. License Issuance Workflow

### 4.1 Online Purchase Flow (SaaS Purchase of On-Prem License)

```
Customer visits stream2stack.com/on-prem
          │
          ▼
    Selects plan + seats
    (Standard / Professional / Enterprise)
          │
          ▼
    Checkout via Stripe
    (one-time annual payment or monthly)
          │
          ▼
    Stripe webhook → our License Server:
      POST /license/issue
      {
        "customer_id": "cust_xyz",
        "plan": "professional",
        "seats": 10,
        "duration_days": 365
      }
          │
          ▼
    License Server:
      1. Generate JWT payload
      2. Sign with RSA-2048 private key
      3. Store in license_records table
      4. Email customer: "S2S-<token>" + install instructions
          │
          ▼
    Customer installs: sets S2S_LICENSE_KEY in .env
```

### 4.2 Enterprise / Offline License Flow

```
Customer contacts sales → agreed on plan + seats + duration
          │
          ▼
    Internal CLI tool (our ops team):
      $ s2s-license issue \
          --customer "Acme Corp" \
          --plan enterprise \
          --seats unlimited \
          --days 365 \
          --features sso,white_label,air_gap \
          --output acme-license.txt
          │
          ▼
    License file emailed to customer
    (also backed up in our CRM + license_records DB)
```

### 4.3 License Renewal

- 60 days before expiry: automated email with renewal link
- 30 days before: second email + in-app banner
- 7 days before: final warning email
- On expiry: server starts but returns 402 on all AI-generating endpoints
  (read-only mode — customers can still view existing newsletters)
- 14-day grace period after expiry before full lockout

---

## 5. License Record Storage (Our Side)

```sql
CREATE TABLE license_records (
    license_id      TEXT PRIMARY KEY,       -- 'lic_abc123'
    customer_id     TEXT NOT NULL,
    customer_name   TEXT NOT NULL,
    customer_email  TEXT NOT NULL,
    plan            TEXT NOT NULL,
    seats           INTEGER,                -- NULL = unlimited
    features        JSONB NOT NULL,
    issued_at       TIMESTAMPTZ NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    renewed_from    TEXT REFERENCES license_records(license_id),
    revoked_at      TIMESTAMPTZ,            -- NULL = active
    revocation_reason TEXT,
    stripe_payment_id TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

---

## 6. Anti-Tamper & Security

| Threat | Mitigation |
|--------|-----------|
| Key sharing between customers | License payload includes `customer_id`; telemetry agent reports hostname; seat limit |
| Clock rollback attack | License server validates `issued_at` is not in future; telemetry counters monotonic |
| JWT forging | RSA-2048 public key embedded in binary — private key never leaves our license server |
| Key extraction from binary | Obfuscation (PyArmor / compiled Cython); not primary defense — rely on business controls |
| Running without network | Offline certs valid for 90 days; renewal requires online check or manual CSV process |

---

## 7. SaaS License Terms (ToS Summary)

For SaaS customers, licensing is handled via Terms of Service accepted at signup.
No cryptographic key required. Key provisions:

- **Fair use**: automated scraping, reselling API access, or embedding output in
  competing products is prohibited
- **Data ownership**: customers own their content; we own usage metadata
- **Cancellation**: 30-day notice; all data exportable within 60 days post-cancel
- **SLA**: 99.5% uptime for Pro+; 99.9% for Enterprise; credits for breaches
- **GDPR**: DPA available on request; data stored in EU or US (customer selects)

---

## 8. Open Source / Community Edition Consideration

A **Community Edition (CE)** can accelerate adoption:

```
Community Edition (free, open-source Apache 2.0):
  - Single user
  - Ollama only (no paid API key required)
  - No email delivery
  - No web crawling
  - Self-hosted only
  - GitHub stars → top-of-funnel for commercial licenses

Commercial Editions (proprietary):
  - Standard / Professional / Enterprise (on-prem)
  - SaaS plans (hosted)

Dual-license model:
  - CE code is open; commercial additions are closed
  - Clear feature matrix published at stream2stack.com/pricing
```

---

## 9. Implementation Phases

### Phase A — Foundation ✅ Complete
- [ ] RSA-2048 key pair generation + secure storage (AWS KMS or Vault)
- [ ] License JWT schema finalized
- [ ] License issuance CLI tool (internal ops)
- [x] `license.py` service (validate, feature check, seat check) — `backend/services/license.py`
- [x] `S2S_DEPLOY_MODE` env var; startup license check in `main.py`
- [x] `GET /license/status` endpoint (on-prem only) — `backend/api/routes/license.py`

> **Note:** Key generation and issuance CLI are ops-side tooling, not deployed with the app.
> The service-side enforcement (validation, feature checks, startup gate) is fully implemented.

### Phase B — Gate Wiring (Week 3)
- [ ] Feature gates on: custom_prompts, audit_logs, sso, white_label
- [ ] Seat enforcement middleware (`seat_manager.py`)
- [ ] Expiry warnings: log daily at 30 days, UI banner at 14 days
- [ ] Read-only mode on expiry (block generate/send, allow read)

### Phase C — License Server (Week 4–5)
- [ ] License server FastAPI service (separate deploy)
- [ ] `license_records` table
- [ ] Issue endpoint: `POST /license/issue`
- [ ] Revoke endpoint: `POST /license/revoke`
- [ ] Renewal flow + automated email sequence (60/30/7 day)
- [ ] Customer portal: license download, renewal, seat history

### Phase D — Stripe + Packaging (Week 6–7)
- [ ] Stripe Products: Standard/Professional/Enterprise (annual + monthly)
- [ ] Checkout flow on stream2stack.com → license auto-issued on payment
- [ ] Docker image publishing to Docker Hub (or GHCR with private repo for paid)
- [ ] Helm chart publishing to chart repo
- [ ] Air-gapped tarball build pipeline

### Phase E — Community Edition (Future)
- [ ] CE feature flag set defined
- [ ] Apache 2.0 LICENSE file in repo
- [ ] CE Docker image (no license check)
- [ ] README CE vs Commercial comparison table
