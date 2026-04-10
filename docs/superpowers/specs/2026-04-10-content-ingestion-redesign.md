# Content Ingestion Redesign — Spec

**Date:** 2026-04-10  
**Status:** Approved for implementation  
**Author:** Dinesh Gopal  

---

## Problem Statement

The current ingestion flow has two core defects:

1. **Session isolation broken**: After ingesting specific URLs, "Generate Newsletter" uses `auto_select=True`, which scans up to 50 historical DB videos — not the ones just ingested. Past content contaminates every new blog post.
2. **Playlist picks everything**: The playlist tab ingests all videos from a playlist with no relevance filtering. The user wants the 3 most thematically cohesive videos selected automatically.

Additionally, the Video URLs tab UI does not clearly communicate the three supported input modes (YouTube-only, Web-only, Mixed), and the output should include related past content as reference links (not mixed into primary content).

---

## Goals

- Blog content uses **only** the sources provided in the current session.
- Past DB content is surfaced as **reference links only**, never as primary input.
- Video URLs tab clearly supports three modes: YouTube-only, Web-only, Mixed.
- Playlist tab auto-selects the top 3 most cohesive videos from the playlist.
- Wiki knowledge base is always compiled after every ingest (already working — no change).

---

## Out of Scope

- Authentication / multi-user isolation
- Changing the newsletter DB schema
- Changing the wiki compilation logic
- Any changes to email delivery

---

## Architecture

### Data Flow — Video URLs Tab

```
User provides YouTube URLs and/or Website URLs
        │
        ▼
POST /videos/ingest  (unchanged backend)
  ├── YouTube URLs → youtube_ingestion → transcript → embedding
  └── Website URLs → firecrawl_crawler → store as transcript → embedding
        │
        ▼
Frontend stores returned video IDs as sessionVideoIds
        │
        ▼
POST /newsletters/generate  { video_ids: sessionVideoIds }  ← KEY CHANGE
  ├── Fetches only those DB records (no auto_select scan)
  ├── Extracts concepts → generates blog per video
  ├── Appends related content references (similarity search, excludes session IDs)
  └── Compiles newsletter markdown → persists → returns
```

### Data Flow — Playlist Tab

```
User provides YouTube Playlist URL
        │
        ▼
POST /videos/ingest  { playlist_url: "..." }
  ├── Expand playlist → all video IDs
  ├── Ingest ALL (metadata + transcript + embedding)
  └── select_cohesive_top_n(videos, n=3)  ← NEW
        │ returns top-3 by centroid similarity
        ▼
Frontend stores top-3 video IDs as sessionVideoIds
        │
        ▼
POST /newsletters/generate  { video_ids: sessionVideoIds }  (same path as above)
```

---

## Component Changes

### Frontend — `frontend/app/input/page.tsx`

**Video URLs tab:**
- Replace single mixed textarea with two labeled textareas:
  - `youtubeUrls` (state): YouTube URLs, one per line
  - `websiteUrls` (state): Website URLs, one per line
- Live **mode badge** derived from state (no API call):
  - Both empty → badge hidden, button disabled
  - Only `youtubeUrls` → badge: "YouTube only"
  - Only `websiteUrls` → badge: "Web only"
  - Both non-empty → badge: "Mixed — YouTube + Web"
- `handleIngest("urls")` combines both into one `urls[]` array sent to `/videos/ingest`
- After ingest: store `result.videos.map(v => v.id)` as `sessionVideoIds` in state

**Playlist tab:**
- No structural change to input
- Update helper text: *"The 3 most thematically related videos will be selected automatically."*
- After ingest: store returned video IDs as `sessionVideoIds` (backend already returns only top-3)

**Generate step:**
- Replace `autoSelect: true` with `videoIds: sessionVideoIds` in `generateNewsletter` call
- Remove the `force` retry path for 409 (no longer relevant — we're using explicit IDs)
- Update `GenerateOptions` interface in `lib/api.ts`: add `videoIds?: string[]`

### Backend — `backend/services/ranking.py`

New function:

```python
def select_cohesive_top_n(
    videos: list[dict],
    n: int = 3,
) -> list[dict]:
    """Return the n videos closest to the group embedding centroid.
    
    Videos without embeddings are excluded from centroid calculation.
    Falls back to recency sort if fewer than n videos have embeddings.
    """
```

Algorithm:
1. Separate videos into `has_embedding` and `no_embedding` groups.
2. If `has_embedding` is empty → return top-n by `published_at` desc.
3. Compute centroid = mean of all embedding vectors.
4. Score each `has_embedding` video by `cosine_similarity(embedding, centroid)`.
5. Sort descending; take top-n from scored list, pad with `no_embedding` videos if needed.
6. Return exactly min(n, len(videos)) results.

### Backend — `backend/api/routes/videos.py`

In `ingest_videos` route, after `processed` list is built:

```python
# For playlist ingests: narrow to top-3 cohesive videos.
if body.playlist_url and len(processed) > 3:
    from services.ranking import select_cohesive_top_n
    processed = select_cohesive_top_n(processed, n=3)
```

`VideoIngestResponse.videos` then contains only the top-3.

### Backend — `backend/api/routes/newsletters.py`

New helper `_find_related_references(session_video_ids, primary_embedding)`:

```python
async def _find_related_references(
    session_video_ids: list[str],
    primary_embedding: list[float],
    top_n: int = 3,
) -> list[dict]:
    """Return up to top_n DB videos similar to primary_embedding, 
    excluding session_video_ids."""
```

Algorithm:
1. Query DB for all videos with non-null embeddings, excluding session IDs.
2. Score each by `cosine_similarity(video.embedding, primary_embedding)`.
3. Return top-n above a similarity threshold of 0.75 (tunable via env var `RELATED_CONTENT_THRESHOLD`, default 0.75).
4. If none meet threshold → return empty list.

Called after blog generation (step 4), before persisting (step 7). Appends a `## Related Content` section to `combined_md` with video titles and source URLs. Only appended if list is non-empty.

### Frontend — `frontend/lib/api.ts`

```typescript
export interface GenerateOptions {
  recipientEmail?: string
  videoIds?: string[]        // explicit video IDs from current session (required post-redesign)
  description?: string
  sourceUrls?: string[]
}
```

In `generateNewsletter`: send `video_ids` in body. Remove `auto_select` and `force` — they are no longer used by any caller after this change.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Both textareas empty | Button disabled, no API call |
| Ingest fails for one URL | Backend logs warning, other URLs succeed; frontend shows count of successful ingestions |
| Playlist has 0 videos with transcripts | Backend returns 422 with clear message |
| Playlist has < 3 videos total | Return all available (no error) |
| No similar content in DB for references | References section omitted silently |
| `video_ids` not found in DB | Newsletter route returns 422 |

---

## Testing

- Unit test: `select_cohesive_top_n` with known embeddings — verify centroid math
- Unit test: `select_cohesive_top_n` fallback when no embeddings present
- Unit test: `_find_related_references` — excludes session IDs, respects threshold
- Integration test: ingest YouTube URL → generate → verify only that video's content appears
- Integration test: ingest web URL → generate → verify scraped content used as primary
- E2E: Video URLs tab mode badge updates correctly for each combination
- E2E: Playlist ingest returns exactly 3 videos (when playlist has > 3)

---

## Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-04-10 | Initial spec |
