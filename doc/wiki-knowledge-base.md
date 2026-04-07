# Wiki Knowledge Base — Design Document

**Status:** Phase A Complete · Phase B Complete · Phase C Planned  
**Version:** 0.3 · Updated 2026-04-06

---

## Overview

The Wiki Knowledge Base treats LLM-powered content synthesis as a **build system**:

| Build concept | Wiki equivalent |
|---|---|
| Source files | Video transcripts in the DB |
| Compiler | `wiki_compiler.py` — LLM extracts + synthesises |
| Build artifacts | Markdown pages in `local_storage/wiki/` |
| Incremental rebuild | Source hash dirty detection per page |
| Linker | `[[Double Bracket]]` backlinks wired across pages |
| Linter | Health checker (Phase C) |

Primary storage is **local filesystem** (Phase A). Supabase/Postgres table storage can be swapped in by replacing `wiki_store.py` only.

---

## Architecture

```
Videos (DB)
    │
    ▼
Concept Extraction (concept_extraction.py)
    │  terms: concepts, tools, patterns
    ▼
Inverted Index: term → [videos]
    │
    ▼
LLM Compiler (wiki_compiler.py)          ← one LLM call per unique term
    │  Markdown: Summary / How It Works /
    │  Code Example / Patterns & Pitfalls /
    │  Related Concepts ([[backlinks]])
    ▼
Wiki Store (wiki_store.py)
    │  local_storage/wiki/
    │    concepts/<slug>.md
    │    tools/<slug>.md
    │    patterns/<slug>.md
    │    indexes/all.md
    │    qa_notes/<slug>.md       ← Phase B
    │    health/report-<date>.md  ← Phase C
    ▼
REST API (api/routes/wiki.py)
    POST /wiki/compile
    GET  /wiki/pages
    GET  /wiki/pages/{type}/{slug}
    GET  /wiki/stats
    POST /wiki/query              ← Phase B
    GET  /wiki/health             ← Phase C
```

---

## Page Schema

Each wiki page is a `.md` file with YAML frontmatter:

```yaml
---
title: "Retrieval-Augmented Generation"
slug: retrieval-augmented-generation
type: concept          # concept | tool | pattern | index | health | qa_note
schema_version: 1
compiled_at: 2026-04-05T10:00:00+00:00
source_hash: a3f1b2c9...
sources:
  - <video-uuid-1>
  - <video-uuid-2>
backlinks:
  - "Vector Database"
  - "Embedding"
---

## Summary
...
```

**Incremental recompile logic** (`needs_recompile`):
- Page missing → recompile
- `schema_version` < `SCHEMA_VERSION` constant → recompile (schema migrations)
- `source_hash` changed (new video added to source set) → recompile
- Otherwise → skip

---

## Phase A — Compiler (Complete)

### Files
| File | Role |
|---|---|
| `backend/services/wiki_store.py` | Filesystem read/write, slug, hash, backlinks |
| `backend/services/wiki_compiler.py` | Full compile pipeline |
| `backend/api/routes/wiki.py` | REST endpoints |

### Endpoints
| Method | Path | Description |
|---|---|---|
| `POST` | `/wiki/compile` | Run incremental (or forced) compile |
| `GET` | `/wiki/pages` | List all pages (filterable by `?type=`) |
| `GET` | `/wiki/pages/{type}/{slug}` | Fetch single page |
| `GET` | `/wiki/stats` | Page counts per type |

### Compile request
```json
{ "user_id": "system", "force": false, "video_ids": null }
```

### Compile response
```json
{ "compiled": 12, "skipped": 3, "errors": 0, "pages_written": 12, "total_terms": 15 }
```

---

## Phase B — Q&A with Artifact Filing (Complete)

### Goal
Allow developers to ask free-form questions against the wiki. Answers are:
1. Grounded in compiled wiki pages (not raw transcripts)
2. Filed back as `qa_notes` — first-class pages in the store
3. Returned with source citations so the user can drill down

### Endpoint
```
POST /wiki/query
```

**Request:**
```json
{ "question": "What are the tradeoffs between RAG and fine-tuning?", "user_id": "alice" }
```

**Response:**
```json
{
  "answer": "...",
  "sources": ["concepts/retrieval-augmented-generation", "concepts/fine-tuning"],
  "qa_note_slug": "what-are-the-tradeoffs-between-rag-and-fine-tuning"
}
```

### Implementation
1. Load all wiki pages from the store (`list_pages()`).
2. Naive relevance filter: score pages by keyword overlap with the question (no embeddings required in Phase B — fast and deterministic).
3. Build context: top-N page summaries + titles.
4. Single LLM call: system = "you are a technical assistant answering from these wiki pages", user = question + context.
5. Extract citations from LLM response.
6. Write `qa_note` to `local_storage/wiki/qa_notes/<slug>.md`.
7. Return answer + sources.

### QA note schema
```yaml
type: qa_note
sources:           # wiki page slugs that grounded the answer
  - concepts/retrieval-augmented-generation
question: "What are the tradeoffs..."
```

---

## Phase C — Linter (Planned)

Scheduled health checks that detect:
- **Orphan concepts** — mentioned in backlinks but no page exists
- **Missing code examples** — pages without a `## Code Example` section
- **Stale pages** — `compiled_at` older than 30 days with new video activity
- **Contradiction candidates** — same term, conflicting definitions across sources
- **Broken backlinks** — `[[Term]]` references that have no corresponding page

Output: `local_storage/wiki/health/report-<date>.md`  
Triggered via: `GET /wiki/health` or scheduled cron

---

## Phase D — Integration (Complete)

Newsletter and blog generation reads compiled wiki pages as supplementary context:
- Relevant wiki pages injected into the generation prompt
- "Learn more" links in generated content point to wiki slugs
- Frontend `/wiki` route browses the knowledge base

---

## Version History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-04-04 | Initial design — build system metaphor, Phase A spec |
| 0.2 | 2026-04-05 | Phase A complete; Phase B spec added (Q&A + artifact filing) |
| 0.3 | 2026-04-06 | Phase B complete — wiki_query.py + POST /wiki/query wired |
| 0.4 | 2026-04-07 | Phase D complete — wiki context injection, Learn More links, /wiki frontend route |
