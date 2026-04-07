# Wiki Knowledge Base — Phase D Integration Design

**Date:** 2026-04-06  
**Status:** Approved  
**Scope:** Phase D of `doc/wiki-knowledge-base.md`

---

## 1. Goal

Wire the compiled wiki knowledge base into the blog/newsletter generation pipeline so that:

1. Generated blog posts are grounded in accumulated wiki knowledge (richer context).
2. Each blog post contains a deterministic `## Learn More` section linking to relevant wiki pages.
3. Developers can browse, search, and recompile the wiki from a frontend `/wiki` route.

---

## 2. Architecture

```
Concept Extraction (existing)
        │ concepts[], tools[], patterns[]
        ▼
Wiki Context Loader (new — backend/services/wiki_context.py)
        │ slug-match each term → store.read_page(type, slug)
        │ deduplicate, cap at 5 pages
        │ returns: list[WikiPage] (empty if wiki not compiled)
        ▼
Blog Generator (modified — backend/services/blog_generator.py)
        │ inject page summaries into user prompt (### Wiki Context block)
        │ existing LLM call (unchanged)
        │ append ## Learn More section after generation
        ▼
Newsletter Generator (unmodified)
        │ operates on already-generated blog posts
        │ Learn More sections carry through automatically
        ▼
Frontend /wiki route (new)
        │ app/wiki/page.tsx        — browse + search + recompile
        │ app/wiki/[type]/[slug]/  — page detail with rendered Markdown
```

**Graceful degradation:** if no wiki pages exist, generation proceeds exactly as today — zero output change.

---

## 3. Backend: `wiki_context.py`

**File:** `backend/services/wiki_context.py`

### 3.1 Public API

```python
def get_relevant_pages(
    concepts: list[str],
    tools: list[str],
    patterns: list[str],
    max_pages: int = 5,
) -> list[WikiPage]:
    """
    Slug-match extracted terms against compiled wiki pages.
    Returns up to max_pages pages. Empty list if wiki has no pages.
    Priority order: concepts → tools → patterns.
    """
```

### 3.2 Logic

1. For each term in `concepts + tools + patterns` (in priority order):
   - `slug = slugify(term)`
   - `page = store.read_page(type, slug)`
   - If page exists, add to results
2. Deduplicate by `(type, slug)`.
3. Cap at `max_pages`.
4. Return list (may be empty — caller must handle gracefully).

### 3.3 Context Block Format

When pages are found, this block is prepended to the LLM user prompt:

```
### Wiki Context

The following pages from our knowledge base are relevant to this video.
Use them to add depth and accuracy to your writing.

=== CONCEPT: Retrieval-Augmented Generation ===
<first 800 chars of page content>
...

=== TOOL: LangChain ===
<first 800 chars of page content>
...
```

Each page is capped at 800 characters to control token usage.

---

## 4. Backend: `blog_generator.py` Modifications

### 4.1 `generate_blog_post()` changes

After concept extraction (already present), before the LLM call:

```python
# New: inject wiki context
wiki_pages = get_relevant_pages(
    concepts=concepts.concepts,
    tools=concepts.tools,
    patterns=concepts.patterns,
)
if wiki_pages:
    wiki_block = _build_wiki_context_block(wiki_pages)
    user_prompt = wiki_block + "\n\n" + user_prompt
```

After the LLM returns content:

```python
# New: append Learn More section
if wiki_pages:
    content = _append_learn_more(content, wiki_pages)
```

### 4.2 `_append_learn_more(content, pages) -> str`

Appends a `## Learn More` section using frontend `/wiki/{type}/{slug}` paths:

```markdown
## Learn More

- [Retrieval-Augmented Generation](/wiki/concepts/retrieval-augmented-generation)
- [LangChain](/wiki/tools/langchain)
```

Returns content unchanged if `pages` is empty.

### 4.3 Newsletter assembly

No changes. Newsletter assembles from already-generated blog posts — `## Learn More` sections carry through automatically.

---

## 5. Frontend: `/wiki` Route

### 5.1 `app/wiki/page.tsx` — Browse, Search & Compile

**Data fetching:**
- `GET /wiki/stats` — load page counts per type for the header summary
- `GET /wiki/pages` — fetch all pages once, group client-side

**UI:**
- Header: "Wiki Knowledge Base" + stats (e.g., "12 concepts · 8 tools · 5 patterns")
- Three tabs: **Concepts** / **Tools** / **Patterns**
- Search bar: client-side filter by title (no API round-trip)
- List item: title + source video count + last compiled date → links to detail page
- **"Recompile Wiki" button**: calls `POST /wiki/compile {force: false}`, shows spinner, toast with `compiled/skipped` counts on completion

### 5.2 `app/wiki/[type]/[slug]/page.tsx` — Page Detail

**Data fetching:**
- `GET /wiki/pages/{type}/{slug}`

**UI:**
- Type badge (concept / tool / pattern)
- Title as `<h1>`
- Metadata row: source video count + last compiled timestamp
- Markdown rendered using existing `react-markdown` setup (same as newsletter view)
- Backlinks rendered as internal `/wiki/{type}/{slug}` links
- Back button → `/wiki`

### 5.3 Navigation

Add **"Wiki"** entry to the existing sidebar nav (alongside Dashboard / History / Settings).

---

## 6. API Endpoints

No new endpoints required. All four existing wiki endpoints are sufficient:

| Method | Path | Used by |
|--------|------|---------|
| `POST` | `/wiki/compile` | Recompile button |
| `GET` | `/wiki/pages` | Browse page list |
| `GET` | `/wiki/pages/{type}/{slug}` | Page detail |
| `GET` | `/wiki/stats` | Browse header stats |

---

## 7. Token Budget

Per blog post with wiki context:

| Addition | Approx tokens |
|----------|--------------|
| Wiki context block (5 pages × 800 chars) | ~1,000 input tokens |
| Learn More section in output | ~50 output tokens |
| **Extra cost per blog post** | **~$0.003 at Sonnet pricing** |

Acceptable. No quota gate changes needed.

---

## 8. Error Handling

- `wiki_context.py` catches all `read_page` exceptions — never raises to caller.
- If wiki context injection fails, generation proceeds without it (logged as warning).
- Frontend: if `GET /wiki/pages` returns empty list, show "No pages compiled yet" with a prompt to click Recompile.

---

## 9. Files Changed

| File | Change |
|------|--------|
| `backend/services/wiki_context.py` | **New** — context loader |
| `backend/services/blog_generator.py` | **Modified** — inject context + append Learn More |
| `frontend/app/wiki/page.tsx` | **New** — browse + search + compile |
| `frontend/app/wiki/[type]/[slug]/page.tsx` | **New** — page detail |
| `frontend/components/navbar.tsx` | **Modified** — add Wiki entry to `navLinks` array |

---

## 10. Out of Scope (Phase C)

The linter/health checker (orphan concepts, stale pages, broken backlinks) is Phase C and is explicitly excluded from this implementation.
