# Wiki Phase D Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Wire the compiled wiki knowledge base into blog generation (context injection + Learn More links) and add a frontend `/wiki` browse/search/compile route.

**Architecture:** A new `wiki_context.py` service slug-matches extracted concepts against compiled wiki pages and returns relevant pages. `blog_generator.py` injects these as a context block into the LLM prompt and appends a deterministic `## Learn More` section after generation. The frontend adds a `/wiki` route with tabs, search, and a recompile button, plus a detail page for individual wiki pages.

**Tech Stack:** Python 3.11, FastAPI, Next.js 14 (App Router), shadcn/ui, Tailwind CSS, pytest, ReactMarkdown + remark-gfm

---

## File Map

| File | Change |
|------|--------|
| `backend/services/wiki_context.py` | **New** — `get_relevant_pages`, `build_wiki_context_block`, `append_learn_more` |
| `backend/tests/unit/test_wiki_context.py` | **New** — unit tests for wiki_context.py |
| `backend/services/blog_generator.py` | **Modify** — inject wiki context in `generate_blog`, append Learn More |
| `frontend/lib/api.ts` | **Modify** — add wiki API types and functions |
| `frontend/components/navbar.tsx` | **Modify** — add Wiki entry to navLinks |
| `frontend/app/wiki/page.tsx` | **New** — browse, search, compile trigger |
| `frontend/app/wiki/[type]/[slug]/page.tsx` | **New** — single page detail view |

---

## Task 1: wiki_context.py — Core Service

**Files:**
- Create: `backend/services/wiki_context.py`
- Create: `backend/tests/unit/test_wiki_context.py`

- [x] **Step 1.1: Write failing tests**

Create `backend/tests/unit/test_wiki_context.py`:

```python
"""Unit tests for services/wiki_context.py."""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from unittest.mock import patch, MagicMock
from services.wiki_context import (
    get_relevant_pages,
    build_wiki_context_block,
    append_learn_more,
)
from services.wiki_store import WikiPage


def _make_page(title: str, slug: str, page_type: str, content: str = "Some content") -> WikiPage:
    return WikiPage(
        title=title,
        slug=slug,
        page_type=page_type,
        content=content,
        source_ids=["vid-1"],
        source_hash="abc123",
        compiled_at="2026-04-06T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# get_relevant_pages
# ---------------------------------------------------------------------------

def test_get_relevant_pages_returns_matching_concepts():
    rag_page = _make_page("RAG Pipeline", "rag-pipeline", "concept")

    def fake_read_page(page_type: str, slug: str):
        if page_type == "concept" and slug == "rag-pipeline":
            return rag_page
        return None

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page):
        pages = get_relevant_pages(
            concepts=["RAG Pipeline"],
            tools=[],
            patterns=[],
        )

    assert len(pages) == 1
    assert pages[0].title == "RAG Pipeline"


def test_get_relevant_pages_deduplicates():
    page = _make_page("LangChain", "langchain", "tool")

    def fake_read_page(page_type: str, slug: str):
        if page_type == "tool" and slug == "langchain":
            return page
        return None

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page):
        # Same term in tools twice — should deduplicate
        pages = get_relevant_pages(concepts=[], tools=["LangChain", "LangChain"], patterns=[])

    assert len(pages) == 1


def test_get_relevant_pages_respects_max_pages():
    def fake_read_page(page_type: str, slug: str):
        return _make_page(slug, slug, page_type)

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page):
        pages = get_relevant_pages(
            concepts=["a", "b", "c", "d", "e", "f"],
            tools=[],
            patterns=[],
            max_pages=3,
        )

    assert len(pages) == 3


def test_get_relevant_pages_returns_empty_when_no_wiki():
    with patch("services.wiki_context.store.read_page", return_value=None):
        pages = get_relevant_pages(concepts=["RAG"], tools=["LangChain"], patterns=["CQRS"])

    assert pages == []


def test_get_relevant_pages_never_raises():
    with patch("services.wiki_context.store.read_page", side_effect=Exception("disk error")):
        pages = get_relevant_pages(concepts=["RAG"], tools=[], patterns=[])

    assert pages == []


# ---------------------------------------------------------------------------
# build_wiki_context_block
# ---------------------------------------------------------------------------

def test_build_wiki_context_block_empty():
    assert build_wiki_context_block([]) == ""


def test_build_wiki_context_block_includes_title_and_content():
    pages = [_make_page("RAG Pipeline", "rag-pipeline", "concept", content="RAG content here")]
    block = build_wiki_context_block(pages)

    assert "RAG Pipeline" in block
    assert "RAG content here" in block
    assert "Wiki Context" in block


def test_build_wiki_context_block_truncates_long_content():
    long_content = "x" * 2000
    pages = [_make_page("Big Page", "big-page", "concept", content=long_content)]
    block = build_wiki_context_block(pages)

    # Content is capped at 800 chars per page
    assert len(block) < 1200


# ---------------------------------------------------------------------------
# append_learn_more
# ---------------------------------------------------------------------------

def test_append_learn_more_empty_pages():
    content = "# My Blog Post\n\nSome content."
    result = append_learn_more(content, [])
    assert result == content


def test_append_learn_more_appends_section():
    content = "# My Blog Post\n\nSome content."
    pages = [
        _make_page("RAG Pipeline", "rag-pipeline", "concept"),
        _make_page("LangChain", "langchain", "tool"),
    ]
    result = append_learn_more(content, pages)

    assert "## Learn More" in result
    assert "/wiki/concepts/rag-pipeline" in result
    assert "/wiki/tools/langchain" in result


def test_append_learn_more_preserves_original_content():
    content = "# My Blog Post\n\nSome content."
    pages = [_make_page("RAG Pipeline", "rag-pipeline", "concept")]
    result = append_learn_more(content, pages)

    assert result.startswith(content)
```

- [x] **Step 1.2: Run tests — verify they fail**

```bash
cd backend && python3 -m pytest tests/unit/test_wiki_context.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'services.wiki_context'`

- [x] **Step 1.3: Create `backend/services/wiki_context.py`**

```python
"""
Wiki context loader for blog/newsletter generation.

Slug-matches extracted concept/tool/pattern terms against compiled wiki pages
and returns relevant pages to inject as LLM context.

Public API:
    get_relevant_pages(concepts, tools, patterns, max_pages) -> list[WikiPage]
    build_wiki_context_block(pages) -> str
    append_learn_more(content, pages) -> str
"""
from __future__ import annotations

import logging
from services import wiki_store as store
from services.wiki_store import WikiPage, slugify

logger = logging.getLogger(__name__)

_MAX_PAGE_CHARS = 800  # chars per page in context block


def get_relevant_pages(
    concepts: list[str],
    tools: list[str],
    patterns: list[str],
    max_pages: int = 5,
) -> list[WikiPage]:
    """Slug-match extracted terms against compiled wiki pages.

    Returns up to max_pages pages in priority order: concepts → tools → patterns.
    Returns empty list if wiki has no matching pages (graceful degradation).
    Never raises — all exceptions are caught and logged.
    """
    seen: set[tuple[str, str]] = set()
    results: list[WikiPage] = []

    term_types = (
        [("concept", t) for t in concepts]
        + [("tool", t) for t in tools]
        + [("pattern", t) for t in patterns]
    )

    for page_type, term in term_types:
        if len(results) >= max_pages:
            break
        slug = slugify(term)
        key = (page_type, slug)
        if key in seen:
            continue
        seen.add(key)
        try:
            page = store.read_page(page_type, slug)
            if page:
                results.append(page)
        except Exception as exc:
            logger.warning("wiki_context: failed to read %s/%s: %s", page_type, slug, exc)

    return results


def build_wiki_context_block(pages: list[WikiPage]) -> str:
    """Format wiki pages as a context block for LLM injection.

    Returns empty string if pages is empty.
    Each page body is truncated to _MAX_PAGE_CHARS to control token usage.
    """
    if not pages:
        return ""

    parts = ["### Wiki Context\n\nRelevant pages from our knowledge base:\n"]
    for page in pages:
        body = page.content[:_MAX_PAGE_CHARS]
        if len(page.content) > _MAX_PAGE_CHARS:
            body += "\n...[truncated]"
        parts.append(
            f"=== {page.page_type.upper()}: {page.title} ===\n{body}"
        )
    return "\n\n".join(parts) + "\n"


def append_learn_more(content: str, pages: list[WikiPage]) -> str:
    """Append a ## Learn More section with wiki links to generated content.

    Returns content unchanged if pages is empty.
    Links use frontend /wiki/{type}/{slug} paths.
    """
    if not pages:
        return content

    lines = ["\n\n## Learn More\n"]
    for page in pages:
        path = f"/wiki/{page.page_type}s/{page.slug}"
        lines.append(f"- [{page.title}]({path})")

    return content + "\n".join(lines)
```

- [x] **Step 1.4: Run tests — verify they pass**

```bash
cd backend && python3 -m pytest tests/unit/test_wiki_context.py -v
```

Expected: all 11 tests pass.

- [x] **Step 1.5: Commit**

```bash
cd backend && git add services/wiki_context.py tests/unit/test_wiki_context.py
git commit -m "feat: add wiki_context service — get_relevant_pages, build_wiki_context_block, append_learn_more"
```

---

## Task 2: Inject Wiki Context into Blog Generator

**Files:**
- Modify: `backend/services/blog_generator.py` — `generate_blog()` function (lines ~180–241)

- [x] **Step 2.1: Write failing test**

Add to `backend/tests/unit/test_wiki_context.py` (append to the end of the file):

```python
# ---------------------------------------------------------------------------
# Integration: blog_generator uses wiki_context
# ---------------------------------------------------------------------------

def test_generate_blog_appends_learn_more_when_wiki_has_pages():
    """generate_blog appends ## Learn More when wiki pages exist."""
    from services.blog_generator import generate_blog
    from models.schemas import ConceptExtractionResult

    rag_page = _make_page("RAG Pipeline", "rag-pipeline", "concept")

    def fake_read_page(page_type: str, slug: str):
        if page_type == "concept" and slug == "rag-pipeline":
            return rag_page
        return None

    with patch("services.wiki_context.store.read_page", side_effect=fake_read_page), \
         patch("services.blog_generator._chat", return_value="# My Post\n\nContent here."), \
         patch("services.blog_generator._get_client", return_value=(MagicMock(), "test-model", "ollama")), \
         patch("services.blog_generator.load_blog_system_prompt", return_value="system prompt"):

        result = generate_blog(
            transcript="RAG Pipeline explained...",
            title="RAG Tutorial",
            concepts=ConceptExtractionResult(
                concepts=["RAG Pipeline"], tools=[], patterns=[], code_hints=[]
            ),
            user_id="test-user",
        )

    assert "## Learn More" in result
    assert "/wiki/concepts/rag-pipeline" in result


def test_generate_blog_no_learn_more_when_wiki_empty():
    """generate_blog does not append ## Learn More when no wiki pages match."""
    from services.blog_generator import generate_blog
    from models.schemas import ConceptExtractionResult

    with patch("services.wiki_context.store.read_page", return_value=None), \
         patch("services.blog_generator._chat", return_value="# My Post\n\nContent here."), \
         patch("services.blog_generator._get_client", return_value=(MagicMock(), "test-model", "ollama")), \
         patch("services.blog_generator.load_blog_system_prompt", return_value="system prompt"):

        result = generate_blog(
            transcript="Some transcript",
            title="Some Video",
            concepts=ConceptExtractionResult(
                concepts=["Unknown Term"], tools=[], patterns=[], code_hints=[]
            ),
            user_id="test-user",
        )

    assert "## Learn More" not in result
```

- [x] **Step 2.2: Run tests — verify they fail**

```bash
cd backend && python3 -m pytest tests/unit/test_wiki_context.py::test_generate_blog_appends_learn_more_when_wiki_has_pages tests/unit/test_wiki_context.py::test_generate_blog_no_learn_more_when_wiki_empty -v
```

Expected: FAIL — `## Learn More` not in result.

- [x] **Step 2.3: Modify `generate_blog()` in `blog_generator.py`**

Add import at the top of the file (after existing imports):

```python
from services.wiki_context import get_relevant_pages, build_wiki_context_block, append_learn_more
```

Then modify `generate_blog()`. Replace the block starting at `user_content = "\n\n".join(parts)` through `return blog_md`:

```python
    user_content = "\n\n".join(parts)

    # Wiki context injection — prepend relevant wiki pages to the user prompt.
    wiki_pages = get_relevant_pages(
        concepts=concepts.concepts,
        tools=concepts.tools,
        patterns=concepts.patterns,
    )
    if wiki_pages:
        wiki_block = build_wiki_context_block(wiki_pages)
        user_content = wiki_block + "\n\n" + user_content

    logger.info(
        "Generating blog post for: %r (user=%s, description=%s, crawled=%s, wiki_pages=%d)",
        title, user_id, bool(description), bool(crawled_context), len(wiki_pages),
    )
    blog_md = _chat(
        client, model, backend, system_prompt, user_content, max_tokens=4096,
        user_id=user_id, operation="blog_generation", resource_id=resource_id,
    )
    logger.info("Generated blog post for %r (%d chars).", title, len(blog_md))

    # Append Learn More section with wiki links.
    blog_md = append_learn_more(blog_md, wiki_pages)

    return blog_md
```

- [x] **Step 2.4: Run all tests — verify they pass**

```bash
cd backend && python3 -m pytest tests/unit/test_wiki_context.py -v
```

Expected: all 13 tests pass.

- [x] **Step 2.5: Commit**

```bash
git add services/blog_generator.py tests/unit/test_wiki_context.py
git commit -m "feat: inject wiki context and append Learn More links in blog generation"
```

---

## Task 3: Frontend Wiki API Functions

**Files:**
- Modify: `frontend/lib/api.ts` — append wiki types and functions

- [x] **Step 3.1: Add wiki types and API functions to `frontend/lib/api.ts`**

Append to the end of the file:

```typescript
// ---------------------------------------------------------------------------
// Wiki Knowledge Base
// ---------------------------------------------------------------------------

export interface WikiPage {
  title: string
  slug: string
  type: string           // "concept" | "tool" | "pattern"
  content: string
  source_ids: string[]
  source_hash: string
  compiled_at: string
  schema_version: number
  backlinks: string[]
}

export interface WikiStats {
  total: number
  by_type: Record<string, number>
  wiki_root: string
}

export interface WikiCompileResult {
  compiled: number
  skipped: number
  errors: number
  pages_written: number
  total_terms: number | null
  message: string | null
}

export async function getWikiPages(type?: string): Promise<WikiPage[]> {
  const url = type
    ? `${API_URL}/wiki/pages?type=${encodeURIComponent(type)}`
    : `${API_URL}/wiki/pages`
  const res = await fetch(url)
  return handleResponse<WikiPage[]>(res)
}

export async function getWikiPage(type: string, slug: string): Promise<WikiPage> {
  const res = await fetch(`${API_URL}/wiki/pages/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`)
  return handleResponse<WikiPage>(res)
}

export async function getWikiStats(): Promise<WikiStats> {
  const res = await fetch(`${API_URL}/wiki/stats`)
  return handleResponse<WikiStats>(res)
}

export async function compileWiki(force = false): Promise<WikiCompileResult> {
  const res = await fetch(`${API_URL}/wiki/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "demo-user-id", force }),
  })
  return handleResponse<WikiCompileResult>(res)
}
```

- [x] **Step 3.2: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds (or only pre-existing errors, none from api.ts).

- [x] **Step 3.3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: add wiki API types and functions to frontend api.ts"
```

---

## Task 4: Add Wiki to Navbar

**Files:**
- Modify: `frontend/components/navbar.tsx` — add Wiki entry to navLinks

- [x] **Step 4.1: Add Wiki link to `navLinks`**

In `frontend/components/navbar.tsx`, replace the `navLinks` array:

```typescript
const navLinks = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/input", label: "Input" },
  { href: "/history", label: "History" },
  { href: "/wiki", label: "Wiki" },
  { href: "/settings", label: "Settings" },
]
```

- [x] **Step 4.2: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [x] **Step 4.3: Commit**

```bash
git add frontend/components/navbar.tsx
git commit -m "feat: add Wiki link to navbar"
```

---

## Task 5: Frontend `/wiki` Browse Page

**Files:**
- Create: `frontend/app/wiki/page.tsx`

- [x] **Step 5.1: Create `frontend/app/wiki/page.tsx`**

```tsx
"use client"

import { useEffect, useState, useMemo } from "react"
import Link from "next/link"
import { getWikiPages, getWikiStats, compileWiki, type WikiPage, type WikiStats } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/use-toast"
import { RefreshCw, BookOpen, Wrench, Layers } from "lucide-react"

const PAGE_TYPES = ["concept", "tool", "pattern"] as const
type PageType = typeof PAGE_TYPES[number]

const TYPE_LABELS: Record<PageType, string> = {
  concept: "Concepts",
  tool: "Tools",
  pattern: "Patterns",
}

const TYPE_ICONS: Record<PageType, React.ReactNode> = {
  concept: <BookOpen className="h-4 w-4" />,
  tool: <Wrench className="h-4 w-4" />,
  pattern: <Layers className="h-4 w-4" />,
}

export default function WikiPage() {
  const [pages, setPages] = useState<WikiPage[]>([])
  const [stats, setStats] = useState<WikiStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [compiling, setCompiling] = useState(false)
  const [search, setSearch] = useState("")
  const { toast } = useToast()

  useEffect(() => {
    Promise.all([getWikiPages(), getWikiStats()])
      .then(([p, s]) => { setPages(p); setStats(s) })
      .catch(() => toast({ title: "Failed to load wiki", variant: "destructive" }))
      .finally(() => setLoading(false))
  }, [])

  const grouped = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = q ? pages.filter(p => p.title.toLowerCase().includes(q)) : pages
    return Object.fromEntries(
      PAGE_TYPES.map(t => [t, filtered.filter(p => p.type === t)])
    ) as Record<PageType, WikiPage[]>
  }, [pages, search])

  async function handleCompile() {
    setCompiling(true)
    try {
      const result = await compileWiki(false)
      toast({
        title: "Wiki compiled",
        description: `${result.compiled} compiled · ${result.skipped} skipped · ${result.errors} errors`,
      })
      const [p, s] = await Promise.all([getWikiPages(), getWikiStats()])
      setPages(p)
      setStats(s)
    } catch {
      toast({ title: "Compile failed", variant: "destructive" })
    } finally {
      setCompiling(false)
    }
  }

  return (
    <div className="container mx-auto max-w-4xl py-8 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">Wiki Knowledge Base</h1>
          {stats && (
            <p className="text-muted-foreground mt-1 text-sm">
              {stats.by_type.concept ?? 0} concepts ·{" "}
              {stats.by_type.tool ?? 0} tools ·{" "}
              {stats.by_type.pattern ?? 0} patterns
            </p>
          )}
        </div>
        <Button onClick={handleCompile} disabled={compiling} variant="outline" className="gap-2">
          <RefreshCw className={`h-4 w-4 ${compiling ? "animate-spin" : ""}`} />
          {compiling ? "Compiling…" : "Recompile Wiki"}
        </Button>
      </div>

      {/* Search */}
      <Input
        placeholder="Search pages…"
        value={search}
        onChange={e => setSearch(e.target.value)}
        className="mb-6"
      />

      {/* Tabs */}
      <Tabs defaultValue="concept">
        <TabsList className="mb-4">
          {PAGE_TYPES.map(t => (
            <TabsTrigger key={t} value={t} className="gap-2">
              {TYPE_ICONS[t]}
              {TYPE_LABELS[t]}
              <Badge variant="secondary" className="ml-1">
                {loading ? "—" : grouped[t].length}
              </Badge>
            </TabsTrigger>
          ))}
        </TabsList>

        {PAGE_TYPES.map(t => (
          <TabsContent key={t} value={t}>
            {loading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
              </div>
            ) : grouped[t].length === 0 ? (
              <div className="text-center py-16 text-muted-foreground">
                {search ? `No ${TYPE_LABELS[t].toLowerCase()} match "${search}"` : `No ${TYPE_LABELS[t].toLowerCase()} compiled yet. Click Recompile Wiki to generate pages.`}
              </div>
            ) : (
              <div className="space-y-2">
                {grouped[t].map(page => (
                  <Link key={page.slug} href={`/wiki/${page.type}s/${page.slug}`}>
                    <Card className="hover:bg-accent/50 transition-colors cursor-pointer">
                      <CardHeader className="py-3 px-4">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-base font-medium">{page.title}</CardTitle>
                          <span className="text-xs text-muted-foreground">
                            {page.source_ids.length} source{page.source_ids.length !== 1 ? "s" : ""}
                          </span>
                        </div>
                      </CardHeader>
                    </Card>
                  </Link>
                ))}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
```

- [x] **Step 5.2: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds.

- [x] **Step 5.3: Commit**

```bash
git add frontend/app/wiki/page.tsx
git commit -m "feat: add /wiki browse page with tabs, search, and recompile button"
```

---

## Task 6: Frontend Wiki Detail Page

**Files:**
- Create: `frontend/app/wiki/[type]/[slug]/page.tsx`

- [x] **Step 6.1: Create directory structure**

```bash
mkdir -p frontend/app/wiki/\[type\]/\[slug\]
```

- [x] **Step 6.2: Create `frontend/app/wiki/[type]/[slug]/page.tsx`**

```tsx
"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { getWikiPage, type WikiPage } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/use-toast"
import { ArrowLeft, Clock, Film } from "lucide-react"

const TYPE_COLORS: Record<string, string> = {
  concept: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  tool: "bg-green-500/10 text-green-500 border-green-500/20",
  pattern: "bg-purple-500/10 text-purple-500 border-purple-500/20",
}

// Normalise the [type] segment — the nav uses "concepts", "tools", "patterns"
// but the API expects "concept", "tool", "pattern".
function normaliseType(raw: string): string {
  return raw.endsWith("s") ? raw.slice(0, -1) : raw
}

export default function WikiDetailPage() {
  const params = useParams<{ type: string; slug: string }>()
  const router = useRouter()
  const { toast } = useToast()
  const [page, setPage] = useState<WikiPage | null>(null)
  const [loading, setLoading] = useState(true)

  const pageType = normaliseType(params.type)

  useEffect(() => {
    getWikiPage(pageType, params.slug)
      .then(setPage)
      .catch(() => {
        toast({ title: "Page not found", variant: "destructive" })
        router.push("/wiki")
      })
      .finally(() => setLoading(false))
  }, [pageType, params.slug])

  if (loading) {
    return (
      <div className="container mx-auto max-w-3xl py-8 px-4 space-y-4">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-12 w-2/3" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!page) return null

  const compiledDate = page.compiled_at
    ? new Date(page.compiled_at).toLocaleDateString()
    : "Unknown"

  return (
    <div className="container mx-auto max-w-3xl py-8 px-4">
      {/* Back */}
      <Link href="/wiki">
        <Button variant="ghost" size="sm" className="gap-2 mb-6 -ml-2">
          <ArrowLeft className="h-4 w-4" />
          Wiki
        </Button>
      </Link>

      {/* Header */}
      <div className="mb-6">
        <Badge
          variant="outline"
          className={`mb-3 capitalize ${TYPE_COLORS[page.type] ?? ""}`}
        >
          {page.type}
        </Badge>
        <h1 className="text-4xl font-bold mb-3">{page.title}</h1>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <Film className="h-3.5 w-3.5" />
            {page.source_ids.length} source video{page.source_ids.length !== 1 ? "s" : ""}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            Compiled {compiledDate}
          </span>
        </div>
      </div>

      {/* Content */}
      <article className="prose prose-invert prose-sm max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              // Render [[backlinks]] as internal wiki links
              if (href?.startsWith("/wiki/")) {
                return <Link href={href} className="text-primary hover:underline">{children}</Link>
              }
              return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
            },
          }}
        >
          {page.content}
        </ReactMarkdown>
      </article>

      {/* Backlinks */}
      {page.backlinks.length > 0 && (
        <div className="mt-8 pt-6 border-t border-border">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Related Concepts
          </h3>
          <div className="flex flex-wrap gap-2">
            {page.backlinks.map(link => {
              const slug = link.toLowerCase().replace(/\s+/g, "-").replace(/[^\w-]/g, "")
              return (
                <Link key={link} href={`/wiki/concepts/${slug}`}>
                  <Badge variant="secondary" className="hover:bg-accent cursor-pointer">
                    {link}
                  </Badge>
                </Link>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [x] **Step 6.3: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds with no errors.

- [x] **Step 6.4: Commit**

```bash
git add "frontend/app/wiki/[type]/[slug]/page.tsx"
git commit -m "feat: add wiki detail page with rendered Markdown and backlinks"
```

---

## Task 7: Update Design Docs

**Files:**
- Modify: `doc/wiki-knowledge-base.md`
- Modify: `doc/wiki-knowledge-base.html`
- Modify: `tasks/todo.md`

- [x] **Step 7.1: Update `doc/wiki-knowledge-base.md`**

In the Phase D section, replace:

```markdown
## Phase D — Integration (Planned)
```

with:

```markdown
## Phase D — Integration (Complete)
```

And add to the version history table:

```markdown
| 0.4 | 2026-04-06 | Phase D complete — wiki context injection, Learn More links, /wiki frontend route |
```

- [x] **Step 7.2: Update `doc/wiki-knowledge-base.html`**

Find the Phase D badge and update:

```html
<span class="badge badge-muted">Planned</span>
```

to:

```html
<span class="badge badge-green">Complete</span>
```

And add the 0.4 row to the version history table:

```html
<tr><td>0.4</td><td>2026-04-06</td><td>Phase D complete — wiki context injection, Learn More links, /wiki frontend route</td></tr>
```

- [x] **Step 7.3: Update `tasks/todo.md`**

The todo.md does not have a Phase 8 for wiki. Add after the Phase 7 section:

```markdown
## Phase 8 — Wiki Knowledge Base Integration
> See: doc/wiki-knowledge-base.md

- [x] backend/services/wiki_context.py: get_relevant_pages, build_wiki_context_block, append_learn_more
- [x] blog_generator.py: inject wiki context + append Learn More on generate_blog()
- [x] frontend/lib/api.ts: WikiPage, WikiStats, WikiCompileResult types + API functions
- [x] frontend/components/navbar.tsx: Wiki nav entry
- [x] frontend/app/wiki/page.tsx: browse + search + recompile
- [x] frontend/app/wiki/[type]/[slug]/page.tsx: page detail with rendered Markdown
```

- [x] **Step 7.4: Commit**

```bash
git add doc/wiki-knowledge-base.md doc/wiki-knowledge-base.html tasks/todo.md
git commit -m "docs: mark Wiki Phase D complete in all tracking docs"
```

---

## Final Verification

- [x] **Run full backend test suite**

```bash
cd backend && python3 -m pytest tests/unit/ -v 2>&1 | tail -20
```

Expected: all tests pass including the 13 new wiki_context tests.

- [x] **Run frontend build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds.

- [x] **Smoke test: start backend and verify wiki endpoint**

```bash
curl -s http://localhost:8080/wiki/stats | python3 -m json.tool
```

Expected: JSON with `total`, `by_type`, `wiki_root` fields.
