-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Videos table
-- NOTE: embedding is 768-dim for local Ollama (nomic-embed-text).
--       Production uses 1536-dim (OpenAI text-embedding-3-small).
CREATE TABLE videos (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  youtube_id text UNIQUE NOT NULL,
  title text,
  description text,
  channel_name text,
  published_at timestamptz,
  duration_seconds int,
  thumbnail_url text,
  transcript text,
  embedding vector(1024),
  created_at timestamptz DEFAULT now()
);

-- Newsletters table
CREATE TABLE newsletters (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id text,  -- text for consistency with user_settings and processed_videos
  title text,
  content_md text,
  content_html text,
  status text DEFAULT 'draft' CHECK (status IN ('draft', 'sent')),
  created_at timestamptz DEFAULT now(),
  sent_at timestamptz,
  storage_url text
);

-- Junction table: which videos are in each newsletter
CREATE TABLE newsletter_videos (
  newsletter_id uuid REFERENCES newsletters(id) ON DELETE CASCADE,
  video_id uuid REFERENCES videos(id),
  PRIMARY KEY (newsletter_id, video_id)
);

-- Track which videos have been processed per user
CREATE TABLE processed_videos (
  user_id text NOT NULL,
  video_id uuid REFERENCES videos(id),
  processed_at timestamptz DEFAULT now(),
  PRIMARY KEY (user_id, video_id)
);

-- User settings
CREATE TABLE user_settings (
  user_id text PRIMARY KEY,
  email_frequency text DEFAULT 'weekly' CHECK (email_frequency IN ('daily', 'weekly', 'monthly')),
  topics text[] DEFAULT '{}',
  playlist_urls text[] DEFAULT '{}',
  recipient_email text,
  updated_at timestamptz DEFAULT now()
);

-- Indexes
CREATE INDEX idx_videos_youtube_id ON videos(youtube_id);
CREATE INDEX idx_videos_published_at ON videos(published_at DESC);
CREATE INDEX idx_newsletters_user_id ON newsletters(user_id);
CREATE INDEX idx_newsletters_created_at ON newsletters(created_at DESC);
CREATE INDEX idx_processed_videos_user ON processed_videos(user_id);

-- pgvector index for cosine similarity search (768-dim)
CREATE INDEX idx_videos_embedding ON videos USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- RPC function: check if a similar video was already processed for a user (768-dim)
CREATE OR REPLACE FUNCTION match_processed_videos(
  query_embedding vector(1024),
  match_threshold float,
  user_id_filter text
)
RETURNS TABLE(video_id uuid, similarity float)
LANGUAGE sql
AS $$
  SELECT pv.video_id, 1 - (v.embedding <=> query_embedding) AS similarity
  FROM processed_videos pv
  JOIN videos v ON v.id = pv.video_id
  WHERE pv.user_id = user_id_filter
    AND v.embedding IS NOT NULL
    AND 1 - (v.embedding <=> query_embedding) >= match_threshold
  LIMIT 1;
$$;

-- RPC function for cosine similarity deduplication check (768-dim)
CREATE OR REPLACE FUNCTION check_similar_videos(
  query_embedding vector(1024),
  similarity_threshold float DEFAULT 0.85,
  result_limit int DEFAULT 5
)
RETURNS TABLE(id uuid, youtube_id text, title text, similarity float)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    v.id,
    v.youtube_id,
    v.title,
    1 - (v.embedding <=> query_embedding) AS similarity
  FROM videos v
  WHERE v.embedding IS NOT NULL
    AND 1 - (v.embedding <=> query_embedding) >= similarity_threshold
  ORDER BY v.embedding <=> query_embedding
  LIMIT result_limit;
END;
$$;

-- ============================================================================
-- Metering, Quotas & Gates
-- ============================================================================

-- usage_events — one row per LLM/API call with token counts + USD cost
CREATE TABLE IF NOT EXISTS usage_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT        NOT NULL,
    org_id          TEXT,
    event_type      TEXT        NOT NULL,
    operation       TEXT        NOT NULL,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER     GENERATED ALWAYS AS (
                        COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)
                    ) STORED,
    cost_usd        NUMERIC(10, 6),
    resource_id     UUID,
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

-- quota_ledger — running totals per user per billing period
CREATE TABLE IF NOT EXISTS quota_ledger (
    user_id             TEXT        NOT NULL,
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

-- plan_quotas — quota limits per plan tier
CREATE TABLE IF NOT EXISTS plan_quotas (
    plan_id                 TEXT        PRIMARY KEY,
    display_name            TEXT        NOT NULL,
    newsletters_per_month   INTEGER,
    videos_per_month        INTEGER,
    emails_per_month        INTEGER,
    scrapes_per_month       INTEGER,
    llm_tokens_per_month    BIGINT,
    max_seats               INTEGER,
    overage_allowed         BOOLEAN     NOT NULL DEFAULT FALSE,
    overage_cost_per_token  NUMERIC(12, 8)
);

INSERT INTO plan_quotas
    (plan_id, display_name, newsletters_per_month, videos_per_month,
     emails_per_month, scrapes_per_month, llm_tokens_per_month,
     max_seats, overage_allowed, overage_cost_per_token)
VALUES
    ('free',       'Free',       3,    20,   0,    20,  500000,   1,    FALSE, NULL),
    ('pro',        'Pro',        20,   200,  20,   200, 5000000,  1,    FALSE, NULL),
    ('team',       'Team',       100,  1000, 100,  500, 25000000, 25,   TRUE,  0.000015),
    ('enterprise', 'Enterprise', NULL, NULL, NULL, NULL, NULL,    NULL, TRUE,  0.000012)
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

-- Add plan_id to user_settings
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS plan_id TEXT NOT NULL DEFAULT 'free'
        REFERENCES plan_quotas (plan_id);

-- upsert_quota_ledger — atomic increment called from metering drain loop
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
