# SaaS vs On-Premises Deployment Plan

**Version:** 1.0
**Date:** 2026-04-01
**Status:** Planning

---

## 1. Overview

Stream2Stack must support two commercial delivery modes with fundamentally
different operational models:

| Dimension | **SaaS** | **On-Premises** |
|-----------|----------|-----------------|
| Infrastructure | We host | Customer hosts |
| API keys | We own | Customer provides |
| Upgrades | Continuous (zero friction) | Customer-controlled |
| Data residency | Our cloud (Supabase/AWS) | Customer's environment |
| Pricing model | Subscription + usage | License fee + support |
| Metering authority | Us (hard truth) | Customer (self-reported or agent) |
| Support burden | Lower | Higher |

---

## 2. SaaS Deployment Plan

### 2.1 Architecture

```
                    ┌──────────────────────────────────────────┐
                    │           stream2stack.com               │
                    │                                          │
  User Browser ────►│  Next.js (Vercel / Cloudflare Pages)    │
                    │                                          │
                    │  FastAPI (Railway / Fly.io / ECS)        │
                    │    ├─ Anthropic API (Claude)             │
                    │    ├─ OpenAI API (embeddings)            │
                    │    ├─ Firecrawl API                      │
                    │    ├─ YouTube Data API                   │
                    │    └─ Resend (email)                     │
                    │                                          │
                    │  Supabase (managed Postgres + pgvector)  │
                    │  Stripe (billing + metered usage)        │
                    └──────────────────────────────────────────┘
```

### 2.2 SaaS-Specific Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| Auth | Supabase Auth (JWT) | Already partially wired in Phase 3 |
| Billing | Stripe Subscriptions + Metered Billing | Plan upgrades, overage invoicing |
| Email | Resend | Newsletter delivery + product emails |
| Queuing | Supabase Edge Functions or BullMQ | Async newsletter jobs |
| Observability | Sentry + Datadog / Grafana | Errors + APM |
| CDN | Cloudflare | Frontend assets + DDoS protection |
| Secret management | Railway/Fly secrets or AWS SSM | API keys centrally managed |

### 2.3 SaaS Tenant Isolation

All data is user-scoped. Multi-tenancy is **row-level** (not schema-per-tenant):
- Every table has `user_id` or `org_id` column
- Supabase RLS policies enforce user can only read their own rows
- `org_id` for Team/Enterprise enables shared quota ledger across seats

```sql
-- RLS example on newsletters table
ALTER TABLE newsletters ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_owns_newsletters"
  ON newsletters
  FOR ALL
  USING (auth.uid()::text = user_id);

-- Team: org members can see all org newsletters
CREATE POLICY "org_members_see_newsletters"
  ON newsletters
  FOR SELECT
  USING (
    org_id IS NOT NULL AND
    org_id IN (
      SELECT org_id FROM org_members WHERE user_id = auth.uid()::text
    )
  );
```

### 2.4 SaaS Quota Enforcement

Handled server-side by us — customers cannot bypass quotas:
- Quotas stored in `quota_ledger` table (authoritative)
- Plan tier stored in `user_settings.plan_id`
- Stripe webhooks update plan on subscription changes
- Rate limiting via Nginx/Cloudflare at the edge (100 req/min per IP)
- Hard quota gates in FastAPI middleware (HTTP 402)

### 2.5 SaaS Pricing Levers

```
Revenue = MRR (subscriptions) + Overage (usage above plan limit)

MRR drivers:
  - Free → Pro conversion (content gates: newsletter limit, email sending)
  - Pro → Team conversion (seat limit, custom prompts feature)
  - Team → Enterprise (SLA, data residency, SSO)

Overage drivers:
  - Team plan: LLM token overage at $0.015/1K tokens
  - Enterprise: negotiated rate
```

### 2.6 SaaS Deployment Checklist

- [ ] Supabase Auth: replace `DEMO_USER_ID` with real JWT claim (Phase 3)
- [ ] `user_settings` table: add `plan_id`, `stripe_customer_id`, `org_id` columns
- [ ] Stripe: product + price objects for Free/Pro/Team/Enterprise
- [ ] Stripe webhooks: `checkout.session.completed`, `customer.subscription.updated/deleted`
- [ ] Metering: `usage_events` drain → Stripe metered billing items (Team overage)
- [ ] Quota gates: FastAPI middleware on all mutating endpoints
- [ ] RLS: policies on all tables
- [ ] GDPR: `DELETE /users/{id}` cascades all user data
- [ ] Observability: Sentry DSN, structured logging → Datadog
- [ ] Status page: statuspage.io or betteruptime.com

---

## 3. On-Premises Deployment Plan

### 3.1 On-Prem Architecture

```
Customer's Environment
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│   Docker Compose / Kubernetes                                      │
│     ├─ stream2stack-backend  (FastAPI container)                   │
│     ├─ stream2stack-frontend (Next.js container)                   │
│     └─ postgres + pgvector  (or customer's existing Postgres)      │
│                                                                    │
│   Customer provides their own external API keys:                   │
│     ├─ ANTHROPIC_API_KEY   (or local Ollama — fully air-gapped)    │
│     ├─ OPENAI_API_KEY      (or Ollama nomic-embed-text)            │
│     ├─ FIRECRAWL_API_KEY   (or skip web crawling)                  │
│     ├─ YOUTUBE_API_KEY                                             │
│     └─ RESEND_API_KEY      (or SMTP relay)                         │
│                                                                    │
│   License Agent (sidecar):                                         │
│     └─ Checks license validity + reports usage to our license      │
│        server (or works fully offline with a time-limited cert)    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
            │  usage heartbeat (optional, if customer permits)
            ▼
    stream2stack License Server (our infrastructure)
```

### 3.2 On-Prem Distribution Formats

| Format | Who | When |
|--------|-----|------|
| **Docker Compose bundle** | SMB customers, quick deploy | Standard on-prem |
| **Helm chart** | Enterprise Kubernetes shops | Large enterprise |
| **Air-gapped tarball** | Security-sensitive (gov, finance) | No internet required |
| **Marketplace listing** | AWS/Azure/GCP marketplace | Self-serve enterprise |

### 3.3 On-Prem Configuration Model

Customers configure via environment variables in their own `.env`:

```bash
# Customer supplies ALL external keys — we touch none of their data
ANTHROPIC_API_KEY=sk-ant-...         # or leave blank + set OLLAMA_BASE_URL
OPENAI_API_KEY=sk-...                # or leave blank + set OLLAMA_EMBED_MODEL
OLLAMA_BASE_URL=http://ollama:11434  # fully air-gapped option

# License
S2S_LICENSE_KEY=S2S-XXXX-XXXX-XXXX-XXXX
S2S_LICENSE_MODE=online              # 'online' | 'offline'
S2S_LICENSE_OFFLINE_CERT=./license.crt  # for air-gapped deployments

# Optional: report usage to our telemetry endpoint (customer opt-in)
S2S_TELEMETRY_ENABLED=false
```

### 3.4 On-Prem Feature Tiers

| Feature | Standard | Professional | Enterprise |
|---------|----------|--------------|------------|
| Newsletter generation | ✓ | ✓ | ✓ |
| Email delivery | ✓ | ✓ | ✓ |
| Ollama (air-gapped LLM) | ✓ | ✓ | ✓ |
| Custom system prompts | ✗ | ✓ | ✓ |
| Multi-user / seats | ✗ (1 seat) | Up to 10 | Unlimited |
| SSO / SAML | ✗ | ✗ | ✓ |
| Audit logging export | ✗ | ✓ | ✓ |
| SLA / support | Community | Email, 2 BD | 24/7, 4hr |
| White-label | ✗ | ✗ | ✓ |

### 3.5 On-Prem Metering Strategy

Since we don't control their infrastructure, metering is lighter — focused on
license compliance, not per-unit billing:

**Option A — Trust-based (Standard tier)**
- Customer self-reports seat count at renewal
- No telemetry agent required
- Enforced by license key (encodes max_seats, expiry)

**Option B — License Agent (Professional/Enterprise)**
- Lightweight sidecar records only counts: newsletters_generated, active_users, videos_ingested
- Reports aggregate summary to our license server weekly (no content, no PII)
- Customer can inspect exactly what is sent (open log)
- If telemetry is blocked, falls back to offline certificate with 90-day validity

**Option C — Air-gapped (Enterprise + Gov)**
- No outbound traffic permitted
- License is a time-limited signed certificate (RSA-2048, 1-year validity)
- At renewal: customer sends aggregate CSV, we issue new cert
- Feature flags baked into the certificate payload

### 3.6 On-Prem Upgrade Path

```
New version released
       │
       ▼
  Customer pulls new Docker image tag
  (or downloads tarball from customer portal)
       │
       ▼
  docker compose pull && docker compose up -d
       │
       ▼
  Database migrations auto-run at startup
  (Alembic or custom migration runner)
       │
       ▼
  License agent validates new version is
  within license period
```

### 3.7 On-Prem Deployment Checklist

- [ ] Finalize Docker images: `stream2stack/backend:x.y.z`, `stream2stack/frontend:x.y.z`
- [ ] Postgres init SQL: ship migration runner (not Supabase-specific)
- [ ] Replace all `supabase_client` calls with generic `postgres_client` fallback
- [ ] License agent: sidecar service (Python/Go) that reads S2S_LICENSE_KEY
- [ ] License server: minimal FastAPI service we host (`api.stream2stack.com/license`)
- [ ] Offline cert generator: CLI tool (internal) to sign certs for air-gapped customers
- [ ] Helm chart: values.yaml for Kubernetes deployments
- [ ] Customer portal: license key download, version history, support tickets
- [ ] Documentation: on-prem install guide, upgrade runbook, air-gap guide

---

## 4. Shared Concerns

### 4.1 Data Portability

Customers who move from SaaS to On-Prem (or vice versa) must be able to export:
- All newsletters (Markdown + HTML)
- All video transcripts
- User settings

Provide: `GET /export/full` → ZIP of all user data as JSON + Markdown files.

### 4.2 API Compatibility

On-prem and SaaS must expose the same REST API. Version pinned at `/v1/`.
Customers using the API with on-prem have the same integration as SaaS.

### 4.3 Security Differences

| Concern | SaaS | On-Prem |
|---------|------|---------|
| API key custody | Us | Customer |
| Data at rest | Supabase encryption | Customer's disk encryption |
| Network isolation | VPC + RLS | Customer's firewall |
| Audit logs | Centralized (Datadog) | Customer's SIEM |
| Pen test | Our responsibility | Customer's responsibility; we provide architecture docs |

### 4.4 Deployment Decision Matrix

| Requirement | Recommended Mode |
|-------------|-----------------|
| Quick start, no ops | SaaS |
| Data must not leave premises | On-Prem |
| Air-gapped network | On-Prem (air-gap mode) |
| Custom LLM / Ollama | On-Prem |
| Multi-region redundancy | SaaS Enterprise |
| White-label | On-Prem Enterprise |
| < 5 users | SaaS Pro |
| > 25 users | SaaS Enterprise or On-Prem |
