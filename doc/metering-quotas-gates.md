# Metering, Quotas & Gates — Design Document

**Version:** 1.0
**Date:** 2026-04-01
**Status:** Implemented (Phases A–C complete; Phase D pending)

---

## 1. Purpose

To price Stream2Stack correctly — and protect it from abuse — we must measure
every resource consumed, enforce hard and soft limits per plan tier, and expose
that data to both operators and customers. This document defines the full
metering schema, quota tiers, and gate enforcement strategy.

---

## 2. What We Meter

Every operation that costs money or capacity must produce a metering event.

### 2.1 LLM / AI Operations

| Operation | Model | Unit | Approx Cost (2026) |
|-----------|-------|------|---------------------|
| Concept extraction | Claude Sonnet 4.6 | input + output tokens | $3/$15 per M tokens |
| Blog post generation | Claude Sonnet 4.6 | input + output tokens | $3/$15 per M tokens |
| Newsletter assembly | Claude Sonnet 4.6 | input + output tokens | $3/$15 per M tokens |
| Text embedding | text-embedding-3-small | input tokens | $0.02 per M tokens |

**Example cost per newsletter (5 videos):**
```
Concept extraction × 5:    ~1,000 input + 300 output tokens each
Blog generation × 5:       ~4,000 input + 2,500 output tokens each
Newsletter assembly × 1:   ~10,000 input + 1,500 output tokens

Total input  ≈ 35,500 tokens × $0.003/K  = ~$0.107
Total output ≈ 14,000 tokens × $0.015/K  = ~$0.210
Total AI cost per newsletter             ≈ $0.32
```

### 2.2 External API Operations

| Operation | Provider | Unit | Cost |
|-----------|----------|------|------|
| Video metadata fetch | YouTube Data API | quota units (10,000/day free) | Free within quota |
| Web page scrape | Firecrawl | credits per URL | ~$0.002/page |
| Email send | Resend | emails sent | ~$0.001/email |
| Vector storage | Supabase pgvector | GB-months | ~$0.125/GB |

### 2.3 Platform Operations

| Operation | Unit | Notes |
|-----------|------|-------|
| Newsletter generation | count/month | Core billing unit for SaaS |
| Video ingestion | count/month | Secondary billing lever |
| Email delivery | count/month | Tied to newsletter send |
| Active users | seat count | For team/enterprise plans |
| Storage (newsletters, transcripts) | GB/month | Secondary |

---

## 3. Metering Data Model

### 3.1 New Database Tables

```sql
-- Every AI call produces a usage_event row
CREATE TABLE usage_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL,
    org_id          TEXT,                    -- for team/enterprise
    event_type      TEXT NOT NULL,           -- 'llm_call' | 'embedding' | 'scrape' | 'email' | 'ingest'
    operation       TEXT NOT NULL,           -- 'concept_extraction' | 'blog_generation' | 'newsletter_assembly' | ...
    model           TEXT,                    -- 'claude-sonnet-4-6' | 'text-embedding-3-small' | ...
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER GENERATED ALWAYS AS (COALESCE(input_tokens,0) + COALESCE(output_tokens,0)) STORED,
    cost_usd        NUMERIC(10, 6),          -- computed at write time using current rates
    resource_id     UUID,                    -- linked newsletter_id, video_id, etc.
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_usage_events_user_period ON usage_events (user_id, created_at DESC);
CREATE INDEX idx_usage_events_org_period  ON usage_events (org_id, created_at DESC);

-- Quota state per user per billing period
CREATE TABLE quota_ledger (
    user_id             TEXT NOT NULL,
    period_start        DATE NOT NULL,          -- truncated to billing cycle start
    newsletters_used    INTEGER NOT NULL DEFAULT 0,
    videos_ingested     INTEGER NOT NULL DEFAULT 0,
    emails_sent         INTEGER NOT NULL DEFAULT 0,
    scrapes_used        INTEGER NOT NULL DEFAULT 0,
    llm_tokens_used     BIGINT NOT NULL DEFAULT 0,
    cost_usd_accrued    NUMERIC(12, 6) NOT NULL DEFAULT 0,
    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, period_start)
);

-- Quota limits per plan
CREATE TABLE plan_quotas (
    plan_id                 TEXT PRIMARY KEY,   -- 'free' | 'pro' | 'team' | 'enterprise'
    newsletters_per_month   INTEGER,            -- NULL = unlimited
    videos_per_month        INTEGER,
    emails_per_month        INTEGER,
    scrapes_per_month       INTEGER,
    llm_tokens_per_month    BIGINT,
    max_seats               INTEGER,
    overage_allowed         BOOLEAN DEFAULT FALSE,
    overage_cost_per_token  NUMERIC(10, 8)
);

INSERT INTO plan_quotas VALUES
  ('free',       3,    20,    0,   20,   500_000,  1,    FALSE, NULL),
  ('pro',        20,   200,   20,  200,  5_000_000,1,    FALSE, NULL),
  ('team',       100,  1000,  100, 500,  25_000_000,25,  TRUE,  0.000015),
  ('enterprise', NULL, NULL,  NULL,NULL, NULL,      NULL, TRUE,  0.000012);
```

### 3.2 Usage Event Schema (Python)

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

@dataclass
class UsageEvent:
    user_id: str
    event_type: str          # 'llm_call' | 'embedding' | 'scrape' | 'email' | 'ingest'
    operation: str           # 'blog_generation' | 'concept_extraction' | ...
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    resource_id: Optional[str] = None
    org_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
```

---

## 4. Token Cost Capture — Implementation

### 4.1 Intercept Every Claude Call

Modify `blog_generator.py → _chat()` to capture Anthropic response usage:

```python
def _chat(client, model: str, backend: str, system: str, user: str,
          max_tokens: int, user_id: str = None, operation: str = None) -> tuple[str, UsageEvent | None]:
    """Returns (content, usage_event). Caller persists the event."""
    if backend == "anthropic":
        message = client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        content = message.content[0].text.strip()

        # Anthropic SDK always returns usage
        event = UsageEvent(
            user_id=user_id or "unknown",
            event_type="llm_call",
            operation=operation or "unknown",
            model=model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cost_usd=_compute_cost(model, message.usage.input_tokens, message.usage.output_tokens),
        )
        return content, event
    ...
```

### 4.2 Cost Rate Table

```python
# backend/services/cost_rates.py
_RATES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input_per_m":  3.00,   # USD per million input tokens
        "output_per_m": 15.00,
    },
    "claude-haiku-4-5-20251001": {
        "input_per_m":  0.80,
        "output_per_m": 4.00,
    },
    "text-embedding-3-small": {
        "input_per_m":  0.02,
        "output_per_m": 0.00,
    },
}

def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _RATES.get(model, {"input_per_m": 0, "output_per_m": 0})
    return (
        input_tokens  / 1_000_000 * rates["input_per_m"] +
        output_tokens / 1_000_000 * rates["output_per_m"]
    )
```

### 4.3 Async Event Sink

Events are written asynchronously so they never block the hot path:

```python
# backend/services/metering.py
import asyncio
from collections import deque

_queue: deque[UsageEvent] = deque()

async def record(event: UsageEvent) -> None:
    """Non-blocking enqueue. Background task drains to DB."""
    _queue.append(event)

async def _drain_loop():
    """Background coroutine — started at app startup."""
    while True:
        batch = []
        while _queue and len(batch) < 100:
            batch.append(_queue.popleft())
        if batch:
            await _flush_to_db(batch)
        await asyncio.sleep(5)  # flush every 5 seconds

async def _flush_to_db(events: list[UsageEvent]):
    supabase = get_supabase_client()
    rows = [asdict(e) for e in events]
    supabase.table("usage_events").insert(rows).execute()
    # Also update quota_ledger via upsert
    await _update_quota_ledger(events)
```

---

## 5. Quota Tiers

### 5.1 Plan Definitions

| Limit | Free | Pro ($29/mo) | Team ($99/mo) | Enterprise (custom) |
|-------|------|--------------|---------------|---------------------|
| Newsletters / month | 3 | 20 | 100 | Unlimited |
| Videos ingested / month | 20 | 200 | 1,000 | Unlimited |
| Emails sent / month | 0 | 20 | 100 | Unlimited |
| Web scrapes / month | 20 | 200 | 500 | Unlimited |
| LLM tokens / month | 500K | 5M | 25M | Unlimited |
| Seats | 1 | 1 | 25 | Custom |
| Overage | No | No | Yes (+$0.015/1K tokens) | Yes (negotiated) |
| Support | Community | Email | Priority | Dedicated |
| API access | No | Yes | Yes | Yes |

### 5.2 Quota Check Flow

```
Request arrives at API
        │
        ▼
┌───────────────────────┐
│  Load quota_ledger    │  ← Redis cache (5-min TTL) or direct DB
│  for current period   │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐    quota_remaining > 0?
│  Gate: check limit    │ ──────────────────────────► YES → proceed
└───────────────────────┘
        │ NO
        ▼
┌───────────────────────┐    overage_allowed?
│  Check overage policy │ ──────────────────────────► YES → add overage charge, proceed
└───────────────────────┘
        │ NO
        ▼
   HTTP 402 / 429
   QuotaExceededError
   (with upgrade CTA)
```

---

## 6. Gates — Enforcement Points

### 6.1 Gate Types

| Gate Type | Trigger | Action |
|-----------|---------|--------|
| **Hard gate** | Quota at 100% | Block request, return 402 with `quota_exceeded` error |
| **Soft gate** | Quota at 80% | Allow request, attach `X-Quota-Warning` header |
| **Rate gate** | >N req/min per user | Return 429 `rate_limit_exceeded` |
| **Overage gate** | Quota at 100% + overage_allowed | Allow, record overage charge |
| **Feature gate** | Feature not on plan | Return 403 `feature_not_available` |

### 6.2 Gate Enforcement in FastAPI

```python
# backend/middleware/quota_gate.py
from fastapi import Request, HTTPException, status

class QuotaGate:
    def __init__(self, resource: str, increment: int = 1):
        self.resource = resource  # 'newsletters' | 'videos' | 'emails' | ...
        self.increment = increment

    async def check_and_reserve(self, user_id: str, plan_id: str) -> None:
        """Raises HTTP 402 if quota is exhausted with no overage."""
        ledger = await get_quota_ledger(user_id)
        limits = await get_plan_limits(plan_id)

        used = getattr(ledger, f"{self.resource}_used", 0)
        limit = getattr(limits, f"{self.resource}_per_month", None)

        if limit is None:
            return  # unlimited

        remaining = limit - used
        pct = used / limit

        if pct >= 0.8:
            # Attach warning to request state for header injection
            pass  # set request.state.quota_warning = True

        if remaining <= 0:
            if limits.overage_allowed:
                await record_overage(user_id, self.resource, self.increment)
                return
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "quota_exceeded",
                    "resource": self.resource,
                    "used": used,
                    "limit": limit,
                    "upgrade_url": "https://stream2stack.com/pricing",
                }
            )

# Usage in route:
@router.post("/generate")
async def generate_newsletter(body: NewsletterGenerateRequest):
    gate = QuotaGate("newsletters")
    await gate.check_and_reserve(body.user_id, body.plan_id)
    # ... rest of handler
```

### 6.3 Feature Gates

```python
# backend/services/feature_flags.py
PLAN_FEATURES = {
    "free":       {"email_send", "api_access": False, "custom_prompts": False},
    "pro":        {"email_send": True, "api_access": True, "custom_prompts": False},
    "team":       {"email_send": True, "api_access": True, "custom_prompts": True},
    "enterprise": {"email_send": True, "api_access": True, "custom_prompts": True},
}

def require_feature(feature: str, plan_id: str):
    if not PLAN_FEATURES.get(plan_id, {}).get(feature, False):
        raise HTTPException(
            status_code=403,
            detail={"code": "feature_not_available", "feature": feature, "plan": plan_id}
        )
```

---

## 7. Usage Dashboard API

Endpoints to expose metering data to customers and operators:

```
GET /usage/summary?user_id=&period=2026-04        # current quota snapshot
GET /usage/events?user_id=&from=&to=&type=        # raw event log
GET /usage/cost?user_id=&period=2026-04           # cost breakdown by operation
GET /admin/usage?org_id=&period=                  # operator view (all users)
```

### 7.1 Summary Response Schema

```json
{
  "period": "2026-04",
  "plan": "pro",
  "quotas": {
    "newsletters":  { "used": 14, "limit": 20, "pct": 70 },
    "videos":       { "used": 87, "limit": 200, "pct": 43 },
    "emails":       { "used": 14, "limit": 20, "pct": 70 },
    "llm_tokens":   { "used": 2100000, "limit": 5000000, "pct": 42 }
  },
  "cost_usd": {
    "llm_total":    4.72,
    "embeddings":   0.04,
    "scrapes":      0.18,
    "emails":       0.01,
    "grand_total":  4.95
  }
}
```

---

## 8. Implementation Phases

### Phase A — Token Capture ✅ Complete
- [x] Add `usage_events` and `quota_ledger` tables — `supabase/migrations/002_metering_schema.sql` + `docker/init-db.sql`
- [x] Add `plan_quotas` table + seed data (free/pro/team/enterprise)
- [x] Create `cost_rates.py` with pricing constants — `backend/services/cost_rates.py`
- [x] Modify `_chat()` in `blog_generator.py` to return usage + write event
- [x] Modify `embeddings.py` to write usage event
- [x] Async drain loop in `metering.py` — `backend/services/metering.py`
- [x] `GET /usage/summary` endpoint — `backend/api/routes/usage.py`

### Phase B — Quota Gates ✅ Complete
- [x] `QuotaGate` middleware class — `backend/services/quota_gate.py`
- [x] Gate on `POST /newsletters/generate`
- [x] Gate on `POST /videos/ingest`
- [x] Gate on `POST /newsletters/{id}/send`
- [x] `X-Quota-Warning` header injection at 80%
- [x] Feature gates for `email_send`, `api_access`

### Phase C — Usage Dashboard ✅ Complete
- [x] `GET /usage/events` with pagination
- [x] `GET /usage/cost` with breakdown
- [ ] Frontend: Usage tab in Settings page
- [ ] Email: Monthly usage digest

### Phase D — Billing Integration (Pending)
- [ ] Stripe integration for plan upgrades
- [ ] Stripe metered billing for overage (Team plan)
- [ ] Webhook: `customer.subscription.updated` → update `user_settings.plan_id`
- [ ] Invoice line items from `usage_events`
