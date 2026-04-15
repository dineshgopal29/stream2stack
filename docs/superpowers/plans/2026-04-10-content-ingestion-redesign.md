# Content Ingestion Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Fix session isolation (blog content uses only currently ingested sources), add playlist top-3 cohesive video selection, split the Video URLs tab UI into YouTube + Website textareas with a live mode badge, and surface past DB content as reference links only.

**Architecture:** Frontend passes explicit `video_ids` from the ingest response to newsletter generation instead of `auto_select=True`. Backend gains `select_cohesive_top_n` (centroid similarity) for playlist narrowing and `_find_related_references` (DB similarity search, excluding session IDs) for appending reference links.

**Tech Stack:** FastAPI + Pydantic (backend), Next.js 14 App Router + React + Tailwind (frontend), NumPy (centroid math), Supabase Python client (DB), Playwright (E2E)

---

## File Map

| File | Change |
|---|---|
| `backend/services/ranking.py` | Add `select_cohesive_top_n` |
| `backend/tests/unit/test_ranking.py` | Add tests for `select_cohesive_top_n` |
| `backend/api/routes/videos.py` | Apply playlist top-3 selection after ingest |
| `backend/api/routes/newsletters.py` | Add `_find_related_references` + `_build_related_content_section`; append related content to `combined_md` |
| `frontend/lib/api.ts` | Update `GenerateOptions`: remove `autoSelect`/`force`, add `videoIds` |
| `frontend/app/input/page.tsx` | Split textarea → two textareas, mode badge, `sessionVideoIds` state, pass `videoIds` to generate |
| `frontend/tests/e2e/ingest-and-wiki.spec.ts` | Update UI label assertions for new two-textarea layout |

---

## Task 1: Add `select_cohesive_top_n` to ranking.py

**Files:**
- Modify: `backend/services/ranking.py`
- Test: `backend/tests/unit/test_ranking.py`

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_ranking.py`:

```python
from services.ranking import select_cohesive_top_n


# ---------------------------------------------------------------------------
# select_cohesive_top_n
# ---------------------------------------------------------------------------


def test_select_cohesive_top_n_empty_returns_empty():
    assert select_cohesive_top_n([], n=3) == []


def test_select_cohesive_top_n_fewer_than_n_returns_all():
    videos = [
        {"id": "v1", "embedding": [1.0, 0.0], "published_at": "2024-01-01T00:00:00Z"},
        {"id": "v2", "embedding": [0.9, 0.1], "published_at": "2024-01-02T00:00:00Z"},
    ]
    result = select_cohesive_top_n(videos, n=3)
    assert len(result) == 2
    assert {v["id"] for v in result} == {"v1", "v2"}


def test_select_cohesive_top_n_picks_closest_to_centroid():
    # centroid of v1 [1,0] and v2 [0,1] is [0.5, 0.5]
    # v1 and v2 are equidistant; v3 [-1, 0] is far — should be excluded
    videos = [
        {"id": "v1", "embedding": [1.0, 0.0], "published_at": "2024-01-01T00:00:00Z"},
        {"id": "v2", "embedding": [0.0, 1.0], "published_at": "2024-01-02T00:00:00Z"},
        {"id": "v3", "embedding": [-1.0, 0.0], "published_at": "2024-01-03T00:00:00Z"},
    ]
    result = select_cohesive_top_n(videos, n=2)
    assert len(result) == 2
    ids = {v["id"] for v in result}
    assert "v3" not in ids


def test_select_cohesive_top_n_no_embeddings_falls_back_to_recency():
    # Without embeddings, should return n most recent videos
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)
    videos = [
        {"id": "old", "embedding": None, "published_at": (now - timedelta(days=10)).isoformat()},
        {"id": "mid", "embedding": None, "published_at": (now - timedelta(days=5)).isoformat()},
        {"id": "new", "embedding": None, "published_at": now.isoformat()},
    ]
    result = select_cohesive_top_n(videos, n=2)
    assert len(result) == 2
    ids = [v["id"] for v in result]
    assert ids[0] == "new"   # most recent first
    assert "old" not in ids


def test_select_cohesive_top_n_pads_with_no_embedding_videos():
    # 1 video has embedding, 2 don't — need 3 → returns 1 scored + 2 unscored
    videos = [
        {"id": "emb", "embedding": [1.0, 0.0], "published_at": "2024-01-03T00:00:00Z"},
        {"id": "no1", "embedding": None, "published_at": "2024-01-02T00:00:00Z"},
        {"id": "no2", "embedding": None, "published_at": "2024-01-01T00:00:00Z"},
    ]
    result = select_cohesive_top_n(videos, n=3)
    assert len(result) == 3
    assert result[0]["id"] == "emb"
```

- [x] **Step 2: Run tests to verify they fail**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python -m pytest tests/unit/test_ranking.py::test_select_cohesive_top_n_empty_returns_empty -v
```

Expected: `FAILED` with `ImportError: cannot import name 'select_cohesive_top_n'`

- [x] **Step 3: Implement `select_cohesive_top_n` in ranking.py**

Add at the end of `backend/services/ranking.py` (after `rank_and_select`):

```python
def select_cohesive_top_n(
    videos: list[dict[str, Any]],
    n: int = 3,
) -> list[dict[str, Any]]:
    """Return the n videos closest to the group embedding centroid.

    Algorithm:
      1. Separate into has_embedding / no_embedding groups.
      2. If no embeddings at all, fall back to top-n by recency (desc).
      3. Compute centroid = mean of all embedding vectors.
      4. Score each embedded video by cosine_similarity(embedding, centroid).
      5. Return top-n scored, padded with no_embedding videos if needed.

    Args:
        videos: List of video dicts, each optionally containing an 'embedding' list.
        n:      Maximum number of videos to return.

    Returns:
        Up to n videos, ordered by closeness to group centroid.
    """
    if not videos:
        return []
    if len(videos) <= n:
        return videos

    has_emb = [v for v in videos if v.get("embedding")]
    no_emb  = [v for v in videos if not v.get("embedding")]

    if not has_emb:
        # No embeddings — fall back to recency sort descending.
        sorted_by_recency = sorted(
            videos,
            key=lambda v: v.get("published_at") or "",
            reverse=True,
        )
        return sorted_by_recency[:n]

    # Compute centroid of all embedding vectors.
    emb_matrix = np.array([v["embedding"] for v in has_emb], dtype=np.float64)
    centroid: list[float] = emb_matrix.mean(axis=0).tolist()

    # Score each embedded video by similarity to centroid.
    scored: list[tuple[float, dict[str, Any]]] = [
        (cosine_similarity(v["embedding"], centroid), v)
        for v in has_emb
    ]
    scored.sort(key=lambda t: t[0], reverse=True)

    result = [v for _, v in scored[:n]]

    # Pad with unembedded videos if we don't have enough scored ones.
    if len(result) < n:
        result.extend(no_emb[: n - len(result)])

    logger.info(
        "select_cohesive_top_n: %d input → %d selected (n=%d). "
        "Top scores: %s",
        len(videos),
        len(result),
        n,
        [f"{s:.4f}" for s, _ in scored[:n]],
    )
    return result[:n]
```

Also add `select_cohesive_top_n` to the import in the test file (already present from Step 1).

- [x] **Step 4: Run all ranking tests**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python -m pytest tests/unit/test_ranking.py -v
```

Expected: All tests PASS (including the 5 new ones).

- [x] **Step 5: Commit**

```bash
git add backend/services/ranking.py backend/tests/unit/test_ranking.py
git commit -m "feat: add select_cohesive_top_n to ranking service"
```

---

## Task 2: Apply playlist top-3 selection in videos.py

**Files:**
- Modify: `backend/api/routes/videos.py`

- [x] **Step 1: Add playlist narrowing after `processed` is built**

In `backend/api/routes/videos.py`, find the line:

```python
    return VideoIngestResponse(
        videos=processed,
        message=f"Successfully ingested {len(processed)} source(s).",
    )
```

Replace it with:

```python
    # For playlist ingests with more than 3 videos: narrow to the 3 most
    # thematically cohesive videos so the response (and generation) stays focused.
    if body.playlist_url and len(processed) > 3:
        from services.ranking import select_cohesive_top_n
        processed = select_cohesive_top_n(processed, n=3)
        logger.info(
            "Playlist ingest narrowed to %d cohesive videos.", len(processed)
        )

    return VideoIngestResponse(
        videos=processed,
        message=f"Successfully ingested {len(processed)} source(s).",
    )
```

- [x] **Step 2: Manual smoke test (no unit test needed — behaviour covered by ranking tests)**

Start the backend and POST a playlist URL with > 3 videos, confirm the response contains ≤ 3 videos:

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack
# (in a separate terminal) uvicorn backend.main:app --port 8080 --reload
curl -s -X POST http://localhost:8080/videos/ingest \
  -H "Content-Type: application/json" \
  -d '{"playlist_url": "https://www.youtube.com/playlist?list=PLbpi6ZahtOH6Ar_3GPy3workl69X5UOxh"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['videos']), 'videos')"
```

Expected output: `3 videos` (or fewer if playlist has < 3 accessible videos).

- [x] **Step 3: Commit**

```bash
git add backend/api/routes/videos.py
git commit -m "feat: narrow playlist ingest to top-3 cohesive videos"
```

---

## Task 3: Add related content references to newsletters.py

**Files:**
- Modify: `backend/api/routes/newsletters.py`

- [x] **Step 1: Add `_find_related_references` and `_build_related_content_section` helpers**

Add these two functions to `backend/api/routes/newsletters.py` immediately after the `_build_references_section` function (around line 182):

```python
async def _find_related_references(
    session_video_ids: list[str],
    primary_embedding: list[float],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Return up to top_n DB videos similar to primary_embedding,
    excluding any video whose ID is in session_video_ids.

    Scores all DB videos with embeddings using cosine similarity, then
    returns the top_n that exceed RELATED_CONTENT_THRESHOLD (default 0.75).
    Returns an empty list if no candidates meet the threshold or on any error.
    """
    import os
    threshold = float(os.getenv("RELATED_CONTENT_THRESHOLD", "0.75"))

    supabase = get_supabase_client()
    try:
        result = (
            supabase.table("videos")
            .select("id, title, youtube_id, source_type, source_url, embedding")
            .not_.is_("embedding", "null")
            .execute()
        )
        all_videos: list[dict[str, Any]] = result.data or []
    except Exception as exc:
        logger.warning("Related references DB query failed: %s", exc)
        return []

    session_id_set = set(session_video_ids)
    candidates = [v for v in all_videos if v["id"] not in session_id_set]

    scored: list[tuple[float, dict[str, Any]]] = []
    for video in candidates:
        emb = video.get("embedding")
        if not emb:
            continue
        try:
            sim = ranking_svc.cosine_similarity(emb, primary_embedding)
            if sim >= threshold:
                scored.append((sim, video))
        except Exception:
            continue

    scored.sort(key=lambda t: t[0], reverse=True)
    related = [v for _, v in scored[:top_n]]
    logger.info(
        "_find_related_references: %d candidates, %d above threshold %.2f, returning %d.",
        len(candidates), len(scored), threshold, len(related),
    )
    return related


def _build_related_content_section(related: list[dict[str, Any]]) -> str:
    """Build a Markdown '## Related Content' section from video records."""
    from urllib.parse import urlparse
    lines = ["\n\n---\n\n## Related Content\n"]
    for video in related:
        title = video.get("title", "Untitled")
        source_type = video.get("source_type", "youtube")
        if source_type == "web":
            url = video.get("source_url", "")
        else:
            yt_id = video.get("youtube_id", "")
            url = f"https://www.youtube.com/watch?v={yt_id}" if yt_id else ""
        if url:
            lines.append(f"- [{title}]({url})")
    return "\n".join(lines) + "\n"
```

- [x] **Step 2: Call `_find_related_references` after blog generation, before DB persist**

In `backend/api/routes/newsletters.py`, find the comment block:

```python
    # -------------------------------------------------------------------------
    # 5. Assemble final Markdown.
```

Just before that block (after the `videos_with_blogs` check), add:

```python
    # -------------------------------------------------------------------------
    # 4b. Find related past content for reference section.
    # Only run if we have at least one processed video with an embedding.
    # -------------------------------------------------------------------------
    _primary_embedding: list[float] = []
    for v in videos_with_blogs:
        emb = v.get("embedding")
        if emb:
            _primary_embedding = emb
            break

    _related_refs: list[dict[str, Any]] = []
    if _primary_embedding:
        _related_refs = await _find_related_references(
            session_video_ids=[v["id"] for v in videos_with_blogs],
            primary_embedding=_primary_embedding,
        )
```

- [x] **Step 3: Append related content section to `combined_md`**

In `backend/api/routes/newsletters.py`, find the block that ends with:

```python
    # -------------------------------------------------------------------------
    # 6. Convert to HTML.
    # -------------------------------------------------------------------------
```

Just before that block, add:

```python
    # Append related content references (non-empty only).
    if _related_refs:
        combined_md += _build_related_content_section(_related_refs)
```

- [x] **Step 4: Run newsletter API tests to confirm nothing is broken**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python -m pytest tests/api/test_newsletters_api.py -v
```

Expected: All existing tests PASS. The new `_find_related_references` call hits the DB mock — since the mock returns `None` by default for unconfigured chains, the function will catch the exception and return `[]`, so `_related_refs` stays empty and no section is appended. Tests should still pass.

- [x] **Step 5: Commit**

```bash
git add backend/api/routes/newsletters.py
git commit -m "feat: append related content references to generated blog"
```

---

## Task 4: Update `GenerateOptions` in lib/api.ts

**Files:**
- Modify: `frontend/lib/api.ts`

- [x] **Step 1: Update the interface and function**

In `frontend/lib/api.ts`, replace the `GenerateOptions` interface and `generateNewsletter` function:

```typescript
export interface GenerateOptions {
  recipientEmail?: string
  videoIds?: string[]
  description?: string
  sourceUrls?: string[]
}

export async function generateNewsletter(
  userId: string,
  options: GenerateOptions = {}
): Promise<Newsletter> {
  const { recipientEmail, videoIds, description, sourceUrls } = options
  const body: Record<string, unknown> = { user_id: userId }

  if (videoIds && videoIds.length > 0) {
    body.video_ids = videoIds
  } else {
    // Fallback: auto_select for callers that don't have explicit IDs yet.
    body.auto_select = true
  }
  if (recipientEmail) body.recipient_email = recipientEmail
  if (description?.trim()) body.description = description.trim()
  if (sourceUrls && sourceUrls.length > 0) body.source_urls = sourceUrls

  const res = await fetch(`${API_URL}/newsletters/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return handleResponse<Newsletter>(res)
}
```

- [x] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npx tsc --noEmit
```

Expected: No errors.

- [x] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: update GenerateOptions to use videoIds instead of autoSelect"
```

---

## Task 5: Redesign Video URLs tab in input/page.tsx

**Files:**
- Modify: `frontend/app/input/page.tsx`

- [x] **Step 1: Replace single textarea state with two-textarea state**

In `frontend/app/input/page.tsx`, find and replace the ingest state declarations:

Old:
```typescript
  // Ingest state
  const [videoUrls, setVideoUrls] = useState("")
  const [playlistUrl, setPlaylistUrl] = useState("")
  const [isIngesting, setIsIngesting] = useState(false)
  const [ingestedVideos, setIngestedVideos] = useState<Video[]>([])
  const [ingestComplete, setIngestComplete] = useState(false)
```

New:
```typescript
  // Ingest state
  const [youtubeUrls, setYoutubeUrls] = useState("")
  const [websiteUrls, setWebsiteUrls] = useState("")
  const [playlistUrl, setPlaylistUrl] = useState("")
  const [isIngesting, setIsIngesting] = useState(false)
  const [ingestedVideos, setIngestedVideos] = useState<Video[]>([])
  const [ingestComplete, setIngestComplete] = useState(false)
  const [sessionVideoIds, setSessionVideoIds] = useState<string[]>([])
```

- [x] **Step 2: Add the mode badge helper function**

Add this function inside the `InputPage` component, just before `handleIngest`:

```typescript
  function getUrlMode(): "youtube" | "web" | "mixed" | "none" {
    const hasYt = youtubeUrls.trim().length > 0
    const hasWeb = websiteUrls.trim().length > 0
    if (hasYt && hasWeb) return "mixed"
    if (hasYt) return "youtube"
    if (hasWeb) return "web"
    return "none"
  }
```

- [x] **Step 3: Update `handleIngest` to combine both URL fields and store session IDs**

Replace the existing `handleIngest` function:

```typescript
  async function handleIngest(mode: "urls" | "playlist") {
    const urls =
      mode === "urls"
        ? [
            ...youtubeUrls.split("\n").map((u) => u.trim()).filter(Boolean),
            ...websiteUrls.split("\n").map((u) => u.trim()).filter(Boolean),
          ]
        : []
    const playlist = mode === "playlist" ? playlistUrl.trim() : undefined

    if (urls.length === 0 && !playlist) {
      toast({
        title: "No input provided",
        description:
          mode === "urls"
            ? "Please enter at least one YouTube or Website URL."
            : "Please enter a playlist URL.",
        variant: "destructive",
      })
      return
    }

    setIsIngesting(true)
    try {
      const result = await ingestVideos(urls, playlist)
      setIngestedVideos(result.videos)
      setSessionVideoIds(result.videos.map((v) => v.id))
      setIngestComplete(true)
      toast({
        title: "Sources ingested!",
        description: `Successfully processed ${result.videos.length} source${result.videos.length !== 1 ? "s" : ""}.`,
      })
    } catch (err) {
      toast({
        title: "Ingestion failed",
        description:
          err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
    } finally {
      setIsIngesting(false)
    }
  }
```

- [x] **Step 4: Update `handleGenerateNewsletter` to use `videoIds`**

Replace the newsletter options block inside `handleGenerateNewsletter`:

Old:
```typescript
    setIsGenerating(true)
    const opts = {
      recipientEmail: recipientEmail.trim() || undefined,
      autoSelect: true,
      description: description.trim() || undefined,
      sourceUrls: sourceUrls.length > 0 ? sourceUrls : undefined,
    }
    try {
      let newsletter: Newsletter
      try {
        newsletter = await generateNewsletter(DEMO_USER_ID, opts)
      } catch (err) {
        // 409 = all videos already processed — retry with force=true
        if (err instanceof ApiError && err.status === 409) {
          toast({
            title: "Re-using processed videos",
            description: "All videos were already processed — regenerating from existing content.",
          })
          newsletter = await generateNewsletter(DEMO_USER_ID, { ...opts, force: true })
        } else {
          throw err
        }
      }
```

New:
```typescript
    setIsGenerating(true)
    const opts = {
      recipientEmail: recipientEmail.trim() || undefined,
      videoIds: sessionVideoIds,
      description: description.trim() || undefined,
      sourceUrls: sourceUrls.length > 0 ? sourceUrls : undefined,
    }
    try {
      const newsletter = await generateNewsletter(DEMO_USER_ID, opts)
```

- [x] **Step 5: Update `handleReset` to clear new state**

Replace:
```typescript
  function handleReset() {
    setVideoUrls("")
    setPlaylistUrl("")
    setIngestedVideos([])
    setIngestComplete(false)
    setGeneratedNewsletter(null)
    setRecipientEmail("")
    setDescription("")
    setSourceUrls([])
    setSourceUrlInput("")
  }
```

With:
```typescript
  function handleReset() {
    setYoutubeUrls("")
    setWebsiteUrls("")
    setPlaylistUrl("")
    setIngestedVideos([])
    setIngestComplete(false)
    setSessionVideoIds([])
    setGeneratedNewsletter(null)
    setRecipientEmail("")
    setDescription("")
    setSourceUrls([])
    setSourceUrlInput("")
  }
```

- [x] **Step 6: Remove the now-unused `ApiError` import**

The force-retry path that used `ApiError` has been removed. Update the import in `frontend/app/input/page.tsx`:

```typescript
import {
  ingestVideos,
  generateNewsletter,
  getSettings,
  type Video,
  type Newsletter,
} from "@/lib/api"
```

- [x] **Step 7: Replace the Video URLs `TabsContent` JSX with the two-textarea layout**

Replace the entire `<TabsContent value="urls" ...>` block:

Old:
```tsx
            <TabsContent value="urls" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="video-urls">YouTube or Website URLs</Label>
                <Textarea
                  id="video-urls"
                  placeholder={`https://youtube.com/watch?v=abc123\nhttps://venturebeat.com/data/karpathy-llm-architecture`}
                  value={videoUrls}
                  onChange={(e) => setVideoUrls(e.target.value)}
                  rows={6}
                  disabled={isIngesting || ingestComplete}
                  className="font-mono text-xs resize-none"
                />
                <p className="text-xs text-muted-foreground">
                  One URL per line. Supports YouTube links and any https:// website URL.
                </p>
              </div>
              <Button
                onClick={() => handleIngest("urls")}
                disabled={isIngesting || ingestComplete || !videoUrls.trim()}
                className="gap-2"
              >
                {isIngesting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Youtube className="h-4 w-4" />
                )}
                {isIngesting ? "Ingesting..." : "Ingest Videos"}
              </Button>
            </TabsContent>
```

New:
```tsx
            <TabsContent value="urls" className="space-y-5">
              {/* YouTube URLs */}
              <div className="space-y-2">
                <Label htmlFor="youtube-urls" className="flex items-center gap-2">
                  <Youtube className="h-4 w-4 text-red-500" />
                  YouTube URLs
                </Label>
                <Textarea
                  id="youtube-urls"
                  placeholder={`https://youtube.com/watch?v=abc123\nhttps://youtu.be/xyz456`}
                  value={youtubeUrls}
                  onChange={(e) => setYoutubeUrls(e.target.value)}
                  rows={3}
                  disabled={isIngesting || ingestComplete}
                  className="font-mono text-xs resize-none"
                />
                <p className="text-xs text-muted-foreground">
                  One URL per line. Leave blank if not using YouTube.
                </p>
              </div>

              {/* Website URLs */}
              <div className="space-y-2">
                <Label htmlFor="website-urls" className="flex items-center gap-2">
                  <Globe className="h-4 w-4 text-blue-500" />
                  Website URLs
                </Label>
                <Textarea
                  id="website-urls"
                  placeholder={`https://venturebeat.com/ai/some-article\nhttps://example.com/blog/post`}
                  value={websiteUrls}
                  onChange={(e) => setWebsiteUrls(e.target.value)}
                  rows={3}
                  disabled={isIngesting || ingestComplete}
                  className="font-mono text-xs resize-none"
                />
                <p className="text-xs text-muted-foreground">
                  One URL per line. Content will be scraped via Firecrawl. Leave blank if not using web sources.
                </p>
              </div>

              {/* Mode badge */}
              {getUrlMode() !== "none" && !ingestComplete && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Mode:</span>
                  {getUrlMode() === "youtube" && (
                    <Badge variant="secondary" className="gap-1">
                      <Youtube className="h-3 w-3" /> YouTube only
                    </Badge>
                  )}
                  {getUrlMode() === "web" && (
                    <Badge variant="secondary" className="gap-1">
                      <Globe className="h-3 w-3" /> Web only
                    </Badge>
                  )}
                  {getUrlMode() === "mixed" && (
                    <Badge variant="secondary" className="gap-1">
                      <Youtube className="h-3 w-3" /><Globe className="h-3 w-3" /> Mixed — YouTube + Web
                    </Badge>
                  )}
                </div>
              )}

              <Button
                onClick={() => handleIngest("urls")}
                disabled={isIngesting || ingestComplete || getUrlMode() === "none"}
                className="gap-2"
              >
                {isIngesting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {isIngesting ? "Ingesting..." : "Ingest Sources"}
              </Button>
            </TabsContent>
```

- [x] **Step 8: Verify TypeScript compiles with no errors**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npx tsc --noEmit
```

Expected: No errors.

- [x] **Step 9: Commit**

```bash
git add frontend/app/input/page.tsx
git commit -m "feat: split Video URLs tab into YouTube + Website textareas with mode badge"
```

---

## Task 6: Update Playlist tab copy and E2E test assertions

**Files:**
- Modify: `frontend/app/input/page.tsx` (playlist tab description only)
- Modify: `frontend/tests/e2e/ingest-and-wiki.spec.ts`

- [x] **Step 1: Update playlist helper text**

In `frontend/app/input/page.tsx`, find the playlist tab description:

```tsx
                <p className="text-xs text-muted-foreground">
                  All videos in the playlist will be ingested and processed.
                </p>
```

Replace with:

```tsx
                <p className="text-xs text-muted-foreground">
                  The 3 most thematically related videos will be selected automatically.
                </p>
```

- [x] **Step 2: Update E2E test label assertion**

In `frontend/tests/e2e/ingest-and-wiki.spec.ts`, find:

```typescript
  await expect(page.getByText(/YouTube or Website URLs/i)).toBeVisible()
  await expect(page.getByText(/youtube links and any https/i)).toBeVisible()
```

Replace with:

```typescript
  await expect(page.getByText(/YouTube URLs/i)).toBeVisible()
  await expect(page.getByText(/Website URLs/i)).toBeVisible()
  await expect(page.getByText(/Leave blank if not using YouTube/i)).toBeVisible()
```

- [x] **Step 3: Verify the Next.js dev server compiles without errors**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/frontend
npm run build 2>&1 | tail -20
```

Expected: Build completes with no TypeScript or lint errors.

- [x] **Step 4: Commit**

```bash
git add frontend/app/input/page.tsx frontend/tests/e2e/ingest-and-wiki.spec.ts
git commit -m "feat: update playlist copy and E2E assertions for redesigned input UI"
```

---

## Final Verification

- [x] **Run all backend unit tests**

```bash
cd /Users/dinesh/Documents/My_Product/stream2stack/backend
python -m pytest tests/unit/ tests/api/ -v
```

Expected: All tests PASS.

- [x] **Smoke test the full flow manually**

1. Start backend: `uvicorn backend.main:app --port 8080 --reload` (from repo root)
2. Start frontend: `cd frontend && npm run dev`
3. Navigate to `http://localhost:3000/input`
4. Enter a YouTube URL in the YouTube textarea — verify badge shows "YouTube only"
5. Enter a website URL in the Website textarea — verify badge shows "Mixed — YouTube + Web"
6. Click "Ingest Sources" — verify the ingested videos card shows the correct sources
7. Click "Generate Newsletter" — verify the generated blog uses only those sources
8. Navigate to `http://localhost:3000/wiki` — verify wiki was compiled with new concepts
