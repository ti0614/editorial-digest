# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 応答言語

Claudeはこのリポジトリで作業する際、ユーザーへの応答を必ず日本語で行うこと。

## What this is

editorial-digest: a scraper that crawls Japanese newspapers' editorial/opinion list
pages and generates a static, self-contained HTML page summarizing titles, links,
and dates. It intentionally collects metadata only (title/link/date) — never
article body text — for copyright reasons.

## Setup

```bash
pip install -r requirements.txt
```

## Commands

```bash
# Check connectivity for all sources without writing any files
python main.py check

# Check only specific papers
python main.py check --only 朝日新聞 毎日新聞

# Fetch everything, write output/digest.html (last 7 days) + output/YYYY-MM-DD.json
python main.py run

# Same, but restrict papers and/or override the reference date
python main.py run --only 朝日新聞 読売新聞 --date 2026-07-21

# Fetch everything, write output/today.html (same-day articles only) +
# output/YYYY-MM-DD-today.json
python main.py today
python main.py today --only 朝日新聞 読売新聞 --date 2026-07-21
```

There is no test suite, linter, or build step in this repo — `python main.py check`
is the closest thing to a smoke test (it hits real sites over the network but
writes no files).

## Architecture

Pipeline: `sources.yaml` → `main.py` (orchestration) → `fetch.py`/`robots.py`
(networking) → `extract.py` (parsing) → `pubdate.py` (date normalization) →
`render.py` (HTML templating) → `output/*.html`.

- **`sources.yaml`** — one entry per newspaper: `index_url`, CSS selectors
  (`item_selector`/`title_selector`/`link_selector`/`date_selector`/`paid_selector`),
  `tier` (`national`/`block`/`regional`), and flags like `always_paid` or
  `unavailable_reason`. Adding a newspaper is normally just adding an entry here —
  no code changes needed. `verified: true/false` tracks whether the selectors have
  been checked against live HTML recently.
- **`main.py`** — CLI entrypoint (`check` / `run` / `today` subcommands). Loads
  sources, iterates them via `_iter_results`/`process_source`, and writes the JSON
  snapshot + HTML. `process_source` fails a single source into `SourceResult.error`
  rather than aborting the whole run. Between sources it sleeps
  `robots.interval_after(...)` to throttle requests.
- **`robots.py`** — `RobotsChecker` caches `robots.txt` per origin, decides
  `allows(url)` (fails closed if `robots.txt` couldn't be read), and computes the
  wait interval from `Crawl-delay` when a site specifies one.
- **`fetch.py`** — thin `requests` wrapper (fixed `User-Agent`, timeout, encoding
  auto-detection — deliberately not `urllib`, since some sites serve Shift-JIS and
  `urlopen` mis-decodes it as UTF-8).
- **`extract.py`** — `extract_items()` parses one source's list-page HTML into
  `Item(title, link, published, paid)` using the selectors from `sources.yaml`,
  filtering to `within_digest_window` (or, in same-day mode, to `is_same_day` —
  see below) as it goes. `enrich_missing_times()` is a second pass: for items whose
  list-page date has no time component, it fetches the individual article page and
  pulls a time out of `<time>` tags or date+time text in the body.
- **`pubdate.py`** — the date-parsing core. Each paper formats dates differently
  ("2026年7月22日", "7/22", "22日", time-only, etc.); `parse_published_date()`
  normalizes all of them against a `reference_date`, correcting to the previous
  year/month if the naive parse would land in the future. `within_digest_window`
  (weekly digest) and `is_same_day` (today-only mode) both build on this parser,
  and both default to *including* unparseable dates rather than dropping them —
  losing an article silently is worse than over-including one.
- **`render.py`** — pure templating: turns a `list[SourceResult]` into a
  self-contained HTML string (inline CSS/JS, no external CDN or webfonts).
  `render_html()` produces the weekly digest (`digest.html`), grouping articles by
  date with a date-pill nav and tier toggle chips (national/block/regional,
  independently shown/hidden client-side via body classes + localStorage).
  `render_today_html()` produces the same-day version (`today.html`) — single
  section, no date nav, and (unlike the weekly digest) a source having zero items
  is *not* treated as a failure, since not every paper publishes an editorial every
  day.

### Same-day vs weekly mode

`process_source()` takes a `same_day_only` flag. When set, filtering to the
reference date happens *before* `enrich_missing_times()`, so the today-only path
doesn't waste requests fetching individual article pages for older articles that
will just be discarded — this ordering matters for both correctness and request
volume.

### Compliance behavior baked into the code

- Every fetch checks `robots.txt` first via `RobotsChecker`; disallowed sources are
  skipped (`SourceResult.skipped_by_robots`), not force-fetched.
  `sources.yaml`/README document specific papers whose `robots.txt` blocks
  Claude/Anthropic crawlers by name — those are deliberately left unimplemented
  rather than worked around.
  - Only title/link/date are ever extracted; article body HTML is not stored.
- Requests are throttled (default 2s between sources, more if `Crawl-delay` says so).
