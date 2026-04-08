-- supabase/migrations/003_web_sources.sql
-- Add source_type and source_url columns to the videos table.
-- source_type: 'youtube' (default) or 'web'
-- source_url:  original URL for web-scraped sources (null for YouTube videos)

ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'youtube';
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_url text;

COMMENT ON COLUMN videos.source_type IS 'youtube | web';
COMMENT ON COLUMN videos.source_url  IS 'Original URL for web-scraped sources (null for YouTube)';
