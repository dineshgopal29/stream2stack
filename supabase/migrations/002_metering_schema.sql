-- ============================================================================
-- Migration 002: Metering, Quotas & Gates
-- ============================================================================
-- Adds:
--   usage_events   — one row per LLM/API call with token counts + USD cost
--   quota_ledger   — running totals per user per billing period
--   plan_quotas    — quota limits per plan tier (seeded)
--   user_settings  — adds plan_id column (default 'free')
-- ============================================================================

-- ----------------------------------------------------------------------------
-- usage_events
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS usage_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT        NOT NULL,
    org_id          TEXT,
    -- 'llm_call' | 'embedding' | 'scrape' | 'email' | 'ingest'
    event_type      TEXT        NOT NULL,
    -- 'concept_extraction' | 'blog_generation' | 'newsletter_assembly' | 'embed_video' | ...
    operation       TEXT        NOT NULL,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER     GENERATED ALWAYS AS (
                        COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)
                    ) STORED,
    cost_usd        NUMERIC(10, 6),
    resource_id     UUID,           -- linked newsletter_id or video_id
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_events_user_period
    ON usage_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_usage_events_org_period
    ON usage_events (org_id, created_at DESC)
    WHERE org_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_usage_events_resource
    ON usage_events (resource_id)
    WHERE resource_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- quota_ledger  (upserted on every event flush)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS quota_ledger (
    user_id             TEXT        NOT NULL,
    -- Truncated to first day of billing month: date_trunc('month', now())::date
    period_start        DATE        NOT NULL,
    newsletters_used    INTEGER     NOT NULL DEFAULT 0,
    videos_ingested     INTEGER     NOT NULL DEFAULT 0,
    emails_sent         INTEGER     NOT NULL DEFAULT 0,
    scrapes_used        INTEGER     NOT NULL DEFAULT 0,
    llm_tokens_used     BIGINT      NOT NULL DEFAULT 0,
    cost_usd_accrued    NUMERIC(12, 6) NOT NULL DEFAULT 0,
    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_quota_ledger_user
    ON quota_ledger (user_id, period_start DESC);

-- ----------------------------------------------------------------------------
-- plan_quotas  (static lookup table — seeded below)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS plan_quotas (
    plan_id                 TEXT        PRIMARY KEY,
    display_name            TEXT        NOT NULL,
    -- NULL means unlimited
    newsletters_per_month   INTEGER,
    videos_per_month        INTEGER,
    emails_per_month        INTEGER,
    scrapes_per_month       INTEGER,
    llm_tokens_per_month    BIGINT,
    max_seats               INTEGER,
    overage_allowed         BOOLEAN     NOT NULL DEFAULT FALSE,
    -- USD per token when in overage (NULL if no overage allowed)
    overage_cost_per_token  NUMERIC(12, 8)
);

-- Seed plan tiers (idempotent via ON CONFLICT DO UPDATE)
INSERT INTO plan_quotas
    (plan_id, display_name, newsletters_per_month, videos_per_month,
     emails_per_month, scrapes_per_month, llm_tokens_per_month,
     max_seats, overage_allowed, overage_cost_per_token)
VALUES
    ('free',
     'Free',
     3, 20, 0, 20, 500000,
     1, FALSE, NULL),

    ('pro',
     'Pro',
     20, 200, 20, 200, 5000000,
     1, FALSE, NULL),

    ('team',
     'Team',
     100, 1000, 100, 500, 25000000,
     25, TRUE, 0.000015),

    ('enterprise',
     'Enterprise',
     NULL, NULL, NULL, NULL, NULL,
     NULL, TRUE, 0.000012)

ON CONFLICT (plan_id) DO UPDATE SET
    display_name            = EXCLUDED.display_name,
    newsletters_per_month   = EXCLUDED.newsletters_per_month,
    videos_per_month        = EXCLUDED.videos_per_month,
    emails_per_month        = EXCLUDED.emails_per_month,
    scrapes_per_month       = EXCLUDED.scrapes_per_month,
    llm_tokens_per_month    = EXCLUDED.llm_tokens_per_month,
    max_seats               = EXCLUDED.max_seats,
    overage_allowed         = EXCLUDED.overage_allowed,
    overage_cost_per_token  = EXCLUDED.overage_cost_per_token;

-- ----------------------------------------------------------------------------
-- user_settings — add plan_id column
-- ----------------------------------------------------------------------------

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS plan_id TEXT NOT NULL DEFAULT 'free'
        REFERENCES plan_quotas (plan_id);

-- ----------------------------------------------------------------------------
-- upsert_quota_ledger  — atomic increment called from the metering drain loop
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION upsert_quota_ledger(
    p_user_id           TEXT,
    p_period_start      DATE,
    p_newsletters_delta INTEGER,
    p_videos_delta      INTEGER,
    p_emails_delta      INTEGER,
    p_scrapes_delta     INTEGER,
    p_tokens_delta      BIGINT,
    p_cost_delta        NUMERIC
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO quota_ledger
        (user_id, period_start,
         newsletters_used, videos_ingested, emails_sent, scrapes_used,
         llm_tokens_used, cost_usd_accrued, last_updated_at)
    VALUES
        (p_user_id, p_period_start,
         p_newsletters_delta, p_videos_delta, p_emails_delta, p_scrapes_delta,
         p_tokens_delta, p_cost_delta, now())
    ON CONFLICT (user_id, period_start) DO UPDATE SET
        newsletters_used  = quota_ledger.newsletters_used  + EXCLUDED.newsletters_used,
        videos_ingested   = quota_ledger.videos_ingested   + EXCLUDED.videos_ingested,
        emails_sent       = quota_ledger.emails_sent       + EXCLUDED.emails_sent,
        scrapes_used      = quota_ledger.scrapes_used      + EXCLUDED.scrapes_used,
        llm_tokens_used   = quota_ledger.llm_tokens_used   + EXCLUDED.llm_tokens_used,
        cost_usd_accrued  = quota_ledger.cost_usd_accrued  + EXCLUDED.cost_usd_accrued,
        last_updated_at   = now();
END;
$$;
