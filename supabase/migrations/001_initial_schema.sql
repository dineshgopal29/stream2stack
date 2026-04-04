-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Videos table
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
  embedding vector(1536),
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
  sent_at timestamptz
);

-- Junction table: which videos are in each newsletter
CREATE TABLE newsletter_videos (
  newsletter_id uuid REFERENCES newsletters(id) ON DELETE CASCADE,
  video_id uuid REFERENCES videos(id),
  PRIMARY KEY (newsletter_id, video_id)
);

-- Track which videos have been processed per user
CREATE TABLE processed_videos (
  user_id text NOT NULL,  -- text for demo (no auth yet)
  video_id uuid REFERENCES videos(id),
  processed_at timestamptz DEFAULT now(),
  PRIMARY KEY (user_id, video_id)
);

-- User settings
CREATE TABLE user_settings (
  user_id text PRIMARY KEY,  -- text for demo
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

-- pgvector index for cosine similarity search
CREATE INDEX idx_videos_embedding ON videos USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- RPC function for cosine similarity deduplication check
CREATE OR REPLACE FUNCTION check_similar_videos(
  query_embedding vector(1536),
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

-- Storage bucket for newsletter markdown files (run separately in Supabase dashboard or via API)
-- INSERT INTO storage.buckets (id, name, public) VALUES ('newsletters', 'newsletters', true)
-- ON CONFLICT DO NOTHING;
