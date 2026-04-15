# Extraction Quality Improvement Plan

## Goal
Fix severely under-extracting content from YouTube transcripts and web pages.

## Root Causes
1. `blog_generator.py` truncates transcript to 4K chars (10% of a typical video)
2. `concept_extraction.py` truncates to 6K chars  
3. `web_crawler.py` truncates stored content to 8K chars (most articles are 25K+)
4. `firecrawl_crawler.py` truncates to 24K chars at storage time
5. `transcription.py` raw captions: HTML entities, `[Music]` artifacts, no paragraph structure

## Implementation

### Task 1: Clean YouTube transcripts (transcription.py)
- [x] Decode HTML entities (html.unescape)
- [x] Strip `[Music]`, `[Applause]`, `[Laughter]`, etc. artifacts
- [x] Break into readable paragraphs (~60 words each)

### Task 2: Raise web storage limits (web_crawler.py + firecrawl_crawler.py)
- [x] web_crawler.py: 8K → 50K (this is stored in DB; LLM truncates separately)
- [x] firecrawl_crawler.py: 24K → 100K

### Task 3: Adaptive LLM limits (concept_extraction.py + blog_generator.py)
- [x] concept_extraction.py: 6K → backend-aware (Ollama: 12K, Claude: 40K)
- [x] blog_generator.py: 4K default → backend-aware (Ollama: 12K, Claude: 50K)

### Task 4: Test & verify
- [x] Run existing test suite (pytest)
- [x] Manual spot-check: ingest a YouTube video, confirm transcript quality
- [x] Manual spot-check: ingest a web URL, confirm full content stored

## Review
_TBD after implementation_
