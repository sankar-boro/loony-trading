# The Docs Reader

The Docs page (`/docs/*`, `pages/Docs.tsx`) is where you are reading this
handbook. This chapter explains how it works and how to add to the book.

## Reading

- **Table of contents** (left): parts, numbered chapters, and — for the open
  chapter — its numbered sections. The section you are reading is highlighted
  as you scroll. **◧ Hide contents** gives the text the full width.
- **Search**: type two or more characters in the box at the top of the
  contents. Results list the chapter and section of every matching line;
  click one to jump straight to that section.
- **Links** between chapters open inside the reader; external links open in a
  new tab. Every chapter and section has its own URL, e.g.
  `/docs/engine/risk-management.md#position-sizing`, so you can bookmark or
  share them.
- **Previous / next** buttons at the end of each chapter follow the book order.

## How the book is assembled

The content is plain markdown under `docs/`. The order comes from
`docs/book.yaml`:

```yaml
title: The Loony Trading Handbook
subtitle: NSE trading bot + MarketPulse AI dashboard
parts:
  - title: Getting Started
    chapters:
      - getting-started/introduction.md
      - getting-started/installation.md
```

- A **chapter** is one file. Its title is the file's first `# ` heading.
- Its **sections** are the `## ` headings (`###` and below are sub-sections
  that appear in the text but not in the table of contents).
- Chapters are numbered across the whole book in manifest order.
- Markdown files under `docs/` that the manifest does not list still appear,
  at the end, under **Other documents**.

The backend (`dashboard/backend/routers/doc_files.py`) serves:

| Endpoint | Returns |
|---|---|
| `GET /api/doc-files` | The book: parts → chapters (path, title, number) → sections (id, title) |
| `GET /api/doc-files/search?q=…` | Up to 40 matching lines with chapter, section and a snippet |
| `GET /api/doc-files/{path}` | One chapter's raw markdown |

Only `.md` files inside `docs/` can be read; anything else returns 404.
Section ids are generated the same way in Python and in the browser
(GitHub-style slugs), so contents links always land on the heading.

Rendering supports GitHub-flavoured markdown: tables, task lists
(`- [x]`), strikethrough and autolinks. Files are read from disk on every
request, so edits show up on the next page load — no rebuild needed.

## Writing a new chapter

1. Create `docs/<part-folder>/<name>.md` starting with `# Title`.
2. Organise it with `## ` sections.
3. Add its path to the right part in `docs/book.yaml`.
4. Link to other chapters with relative paths, e.g.
   `[Risk Management](../engine/risk-management.md#position-sizing)`.

Keep a section's heading stable once others link to it — the link target is
derived from the heading text.
