# Stream2Stack Implementation Plan

## Phase 1 — Core Pipeline (Ingestion → Blog)
- [x] Project scaffold — monorepo dirs
- [x] Supabase migration SQL
- [x] Backend: FastAPI app setup (main.py, requirements.txt, .env.example)
- [x] Backend: Pydantic schemas (models/schemas.py)
- [x] Backend: Supabase client (db/supabase_client.py)
- [x] Backend: YouTube ingestion service (services/youtube_ingestion.py)
- [x] Backend: Transcription service (services/transcription.py)
- [x] Backend: Concept extraction service (services/concept_extraction.py)
- [x] Backend: Blog generator service (services/blog_generator.py)
- [x] Backend: API routes — videos.py, newsletters.py, settings.py
- [x] Frontend: Next.js 14 scaffold with shadcn + Tailwind
- [x] Frontend: Input page (submit URLs)
- [x] Frontend: Dashboard page (show generated blog)

## Phase 2 — Ranking, Email, Markdown
- [x] Backend: Embeddings service (services/embeddings.py)
- [x] Backend: Ranking engine (services/ranking.py)
- [x] Backend: Deduplication (services/deduplication.py)
- [x] Backend: Markdown export (services/markdown_export.py)
- [x] Backend: Email service (services/email_service.py)
- [x] Frontend: History page (past newsletters + .md download)
- [x] Frontend: Settings page

## Phase 3 — Personalization & Auth
- [x] Backend: User settings endpoint
- [x] Backend: Newsletter /send endpoint
- [x] Backend: Scheduled cron endpoint (POST /cron/run + POST /cron/digest)
- [ ] Frontend: Supabase Auth integration
- [ ] Frontend: Replace DEMO_USER_ID with real auth

## Phase 4 — Source URLs & Description UI

### Definition of Done
- [x] `lib/api.ts` — `generateNewsletter` accepts optional `description` and `sourceUrls`; omits from body when empty
- [x] `app/input/page.tsx` — Step 2 card adds:
  - [x] Optional description `<Textarea>` (post angle / intent)
  - [x] Source URL input + "Add" button with per-item remove; http/https validation
- [x] `handleReset` clears description, sourceUrls, sourceUrlInput
- [x] Caller in `input/page.tsx` updated to new `generateNewsletter` signature
- [ ] Manual smoke test: browser devtools confirm `description` + `source_urls` in request body

### Progress
- [x] Plan written (2026-03-22)
- [x] `lib/api.ts` updated — `generateNewsletter` now takes options object with `description` + `sourceUrls`
- [x] `app/input/page.tsx` updated — description textarea + source URL add/remove UI + reset
- [x] Frontend build passes (no type errors)
- [ ] Manual smoke test

---

## Phase 5 — Metering & Cost Tracking
> Goal: understand every token, dollar, and API call consumed per user.
> See: doc/metering-quotas-gates.md

### Phase 5A — Token Capture (Week 1–2) ✅
- [x] DB migration: usage_events, quota_ledger, plan_quotas tables (002_metering_schema.sql)
- [x] backend/services/cost_rates.py — pricing constants per model
- [x] backend/services/metering.py — UsageEvent, record_sync(), async drain loop
- [x] Modify blog_generator._chat() to capture token counts + emit UsageEvent
- [x] Modify concept_extraction._call_claude/ollama() to emit UsageEvent
- [x] Modify embeddings.get_embedding() to emit UsageEvent
- [x] Async drain loop started in main.py lifespan (flushes every 5s)
- [x] GET /usage/summary, /usage/events, /usage/cost endpoints

### Phase 5B — Quota Gates (Week 3–4) ✅
- [x] backend/services/quota_gate.py — QuotaGate class (hard gate 100%, soft warning 80%)
- [x] Gate wired on POST /newsletters/generate (newsletters quota)
- [x] Gate wired on POST /videos/ingest (videos quota, when user_id provided)
- [x] Feature gate on email send (email_send feature, emails quota)
- [x] X-Quota-Warning header injection at 80% usage
- [x] Feature gates: email_send, custom_prompts via require_feature()

### Phase 5C — Usage Dashboard (Week 5–6) ✅
- [x] GET /usage/events with pagination + date filter
- [x] GET /usage/cost — breakdown by operation, model, period
- [x] Frontend: Usage & Billing tab in Settings page (quota meters + cost table)
- [x] Monthly usage digest email (email_service.send_usage_digest())
- [x] POST /cron/run — scheduled newsletter generation for all due users
- [x] POST /cron/digest — monthly digest emails for all users

### Phase 5D — Billing Integration (Week 7–8)
- [ ] Stripe integration: plan product + price objects (Free/Pro/Team/Enterprise)
- [ ] Stripe metered billing for Team-plan token overage
- [ ] Webhooks: checkout.session.completed, customer.subscription.updated/deleted
- [ ] Invoice line items sourced from usage_events

---

## Phase 6 — SaaS Hardening
> See: doc/saas-vs-onprem-plan.md

- [ ] Supabase Auth: replace DEMO_USER_ID with real JWT claims (Phase 3 prerequisite)
- [ ] user_settings: add plan_id, stripe_customer_id, org_id columns
- [ ] RLS policies on all tables (newsletters, videos, usage_events, quota_ledger)
- [ ] GDPR: DELETE /users/{id} cascades all user data
- [ ] Observability: Sentry DSN + structured logging → Datadog/Grafana
- [ ] Status page (betteruptime.com)
- [ ] Rate limiting at edge: 100 req/min per IP via Cloudflare/Nginx

---

## Phase 7 — On-Premises & Licensing
> See: doc/saas-vs-onprem-plan.md + doc/licensing-plan.md

### Phase 7A — License Foundation (Week 1–2)
- [ ] RSA-2048 key pair generation + AWS KMS secure storage (ops-side, not in repo)
- [x] License JWT payload schema finalized (matches licensing-plan.md §2.1)
- [ ] License issuance CLI (internal ops tool)
- [x] backend/services/license.py: validate(), is_feature_enabled(), get_seat_limit()
- [x] S2S_DEPLOY_MODE env var + startup hard-stop on invalid license (main.py:36-52)
- [x] GET /license/status endpoint (backend/api/routes/license.py)

### Phase 7B — On-Prem Gate Wiring (Week 3)
- [ ] Feature gates: custom_prompts, audit_logs, sso, white_label
- [ ] Seat enforcement middleware at login/session create
- [ ] Expiry warning: log daily at 30 days, UI banner at 14 days
- [ ] Read-only mode on license expiry (view only, no generation)

### Phase 7C — License Server (Week 4–5)
- [ ] License server FastAPI (separate deploy at api.stream2stack.com/license)
- [ ] license_records table + migrations
- [ ] POST /license/issue + POST /license/revoke endpoints
- [ ] Renewal email automation: 60/30/7-day drip
- [ ] Customer portal: license download, renewal, seat history

### Phase 7D — Packaging & Distribution (Week 6–7)
- [ ] Docker images: stream2stack/backend:x.y.z, stream2stack/frontend:x.y.z
- [ ] Postgres-only migration runner (decouple from Supabase)
- [ ] Helm chart with values.yaml for Kubernetes
- [ ] Air-gapped tarball build pipeline
- [ ] Docker Hub (public CE) + private registry (paid tiers)

### Phase 7E — Community Edition (Future)
- [ ] CE feature flag set defined + CE Docker image (no license check)
- [ ] Apache 2.0 LICENSE file in repo
- [ ] README: CE vs Commercial feature comparison

---

## Review
- [ ] End-to-end test: ingest URL → transcript → blog → email
- [x] Syntax validation: all Python files pass ast.parse
- [x] Frontend build: npm run build succeeds

## Notes
- Frontend is pre-built at frontend/.next
- user_id is hardcoded as "demo-user-id" — Phase 3 wires real auth
- YouTube image domains whitelisted in next.config.js
- pgvector IVFFlat index needs 100+ vectors before it's useful; will fall back to seq-scan on small datasets
