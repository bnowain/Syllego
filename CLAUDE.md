# MMI — Modular Media Ingestor (Syllego)

Standalone tool. Not an Atlas spoke. No backend, no server, no UI.
Everything is a pure Python library + CLI callable directly.

---

## Quick Reference

```bash
pip install -e ".[dev]"           # install with dev deps
mmi <url>                         # auto-route to best worker
mmi --m3u8 <stream> --referer <page>  # manual HLS stream
mmi --history                     # recent downloads
mmi -o /path/to/dir <url>        # override output dir
mmi -v <url>                      # verbose/debug logging
pytest tests/ -v                  # run test suite
pytest tests/ --cov=mmi           # with coverage
```

---

## Architecture

Priority-ordered worker chain. Workers are discovered and sorted by `priority` int.
Adding a new site = add one file in `mmi/engine/`, subclass `BaseWorker`. No core changes needed.

```
mmi/
├── __init__.py         Public API: ingest(), ingest_m3u8(), IngestionResult
├── cli.py              Argparse CLI — entry point for `mmi` command
├── config.py           Constants: MMI_OUTPUT_DIR, MMI_DEBUG_DIR, MMI_DB_PATH, get_logger()
├── db/
│   └── history.py      SQLite WAL history: record_download(), get_recent()
├── engine/
│   ├── base.py         BaseWorker ABC + IngestionResult dataclass
│   ├── _ytdlp_common.py  Shared yt-dlp subprocess helper (run_ytdlp, _parse_filename)
│   ├── rumble_worker.py    priority=10, rumble.com / rmbl.ws
│   ├── odysee_worker.py    priority=20, odysee.com
│   ├── gallery_worker.py   priority=30, gallery-dl sites (instagram, reddit, imgur, ...)
│   ├── ytdlp_worker.py     priority=40, youtube / vimeo / tiktok / facebook / etc.
│   ├── facebook_worker.py       priority=35, facebook.com / fb.watch — stealth Tor+Playwright (default)
│   ├── playwright_worker.py     priority=85, rumble.com — headless Chromium CDN interception
│   ├── rumble_stealth_worker.py priority=87, rumble.com — stealth Tor+Playwright fallback
│   ├── generic_worker.py        priority=100, catch-all (yt-dlp → httpx direct fallback)
│   ├── custom_worker.py    priority=0, m3u8 via ffmpeg — NEVER auto-routed
│   └── router.py           Discovers workers, dispatches, records to DB, writes bundles
└── reporting/
    └── reporter.py     Writes failure_bundle_*.json to MMI_DEBUG_DIR
```

## Worker Priority Order

| Priority | Worker | Sites |
|----------|--------|-------|
| 10 | RumbleWorker | rumble.com, rmbl.ws |
| 20 | OdyseeWorker | odysee.com |
| 30 | GalleryWorker | instagram, reddit, imgur, deviantart, pixiv, flickr, x.com, artstation, danbooru, gelbooru |
| 35 | FacebookWorker | facebook.com, fb.watch — stealth Tor+Playwright, default for all Facebook downloads |
| 40 | YtdlpWorker | youtube, youtu.be, vimeo, tiktok, facebook, twitch, dailymotion, twitter, bilibili, soundcloud, bandcamp, mixcloud |
| 85 | PlaywrightWorker | rumble.com, rmbl.ws — headless Chromium intercepts CDN URL (Cloudflare fallback) |
| 87 | RumbleStealthWorker | rumble.com, rmbl.ws — stealth Tor+Playwright, last resort before generic |
| 100 | GenericWorker | everything else — yt-dlp generic, then httpx direct download |

`CustomWorker` is never auto-routed — only via `mmi --m3u8`.

### FacebookWorker (priority 35)
Default path for all Facebook downloads — routes through Tor + stealth Playwright.
YtdlpWorker (40) serves as automatic fallback if stealth fails.
- Requires: `stealth.py` and `tor_pool.py` in `E:/0-Automated-Apps/Facebook-Monitor`
- Tor must be available: already on port 9050, or `tor-bundle/tor/tor.exe` in Facebook-Monitor
- Fresh random browser fingerprint + circuit renewal per request
- Intercepts `*.fbcdn.net` video CDN requests

### PlaywrightWorker (priority 85)
Headless Chromium intercepts the network request the video player fires.
- Requires: `pip install playwright && playwright install chromium`
- Handles Cloudflare-protected sites where yt-dlp cookie injection fails
- Add more sites to `_PLAYWRIGHT_HOSTS` in `playwright_worker.py` as needed

---

## Key Invariants

- `download()` **never raises** — always returns `IngestionResult`
- `can_handle()` for `CustomWorker` **always returns False**
- DB lives inside `MMI_OUTPUT_DIR` — move the folder, history follows
- Failure bundles written to `MMI_OUTPUT_DIR/debug/`
- All file I/O uses `encoding='utf-8'` (Windows cp1252 default would break emoji/CJK filenames)
- Column is `download_status` (not `status`) — globally unique field name
- `yt-dlp` is invoked as `sys.executable -m yt_dlp` (not bare `yt-dlp`) so it always resolves regardless of PATH

## IngestionResult Fields

```python
@dataclass
class IngestionResult:
    success: bool
    url: str
    worker_name: str
    filename: str | None        # path of saved file
    error_code: str | None      # HTTP code or short label
    error_message: str | None
    stack_trace: str | None
    page_html: str | None       # page source on failure (for bundles)
    metadata: dict              # worker-specific extras
```

---

## Adding a New Worker

1. Create `mmi/engine/mysite_worker.py`
2. Subclass `BaseWorker`, pick a `priority` int in a gap between existing workers
3. Implement `can_handle(url) -> bool` and `download(url, output_dir) -> IngestionResult`
4. No registration needed — Router auto-discovers all `BaseWorker` subclasses
5. Add tests in `tests/engine/test_mysite_worker.py` (follow existing worker test files)

---

## Configuration

| Variable | Default | Override |
|----------|---------|----------|
| `MMI_OUTPUT_DIR` | `./downloads` | `MMI_OUTPUT_DIR` env var or `-o` flag |
| `MMI_DEBUG_DIR` | `MMI_OUTPUT_DIR/debug` | (follows output dir) |
| `MMI_DB_PATH` | `MMI_OUTPUT_DIR/mmi_history.db` | (follows output dir) |

---

## Database Schema

```sql
CREATE TABLE download_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    download_status TEXT NOT NULL DEFAULT 'pending',
    worker_name     TEXT,
    filename        TEXT,
    timestamp       TEXT NOT NULL,   -- ISO 8601: YYYY-MM-DDTHH:MM:SS UTC
    error_message   TEXT
);
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

---

## Test Suite

- 205 tests, 99% coverage
- Location: `tests/` — mirrors `mmi/` package structure
- No real binaries called — all subprocess/httpx calls mocked via `unittest.mock`
- `tmp_path` fixture for all filesystem ops — tests never touch `./downloads/`
- DB tests pass a `db_path` param directly — no monkeypatching of globals

```
tests/
├── conftest.py              Shared fixtures
├── test_config.py           Constants + logger
├── test_init.py             Public API + lazy singleton
├── test_cli.py              CLI argument parsing + main() paths
├── db/test_history.py       SQLite CRUD + schema
├── engine/
│   ├── test_base.py         IngestionResult + BaseWorker ABC
│   ├── test_ytdlp_common.py subprocess mocking patterns
│   ├── test_rumble_worker.py
│   ├── test_odysee_worker.py
│   ├── test_gallery_worker.py
│   ├── test_ytdlp_worker.py
│   ├── test_custom_worker.py   m3u8 + _url_to_slug + _unique_path
│   ├── test_generic_worker.py  two-phase fallback + httpx mocking
│   └── test_router.py          dispatch chain + DB recording + failure bundles
└── reporting/test_reporter.py  JSON structure + UTF-8 + never-raise guarantee
```

---

## Known Issues / Gotchas

- **Windows console encoding**: `sys.stdout.reconfigure(encoding='utf-8')` is called in `main()` — emoji/CJK in filenames still display as `?` in non-UTF8 terminals but the actual file is correct
- **yt-dlp not on PATH**: Invoke via `sys.executable -m yt_dlp` (already done) — do not revert to bare `yt-dlp`
- **Facebook/Instagram**: Requires yt-dlp or gallery-dl with cookies for some content; public reels work without auth
- **Twitter/X**: GalleryWorker (priority 30) handles image tweets; YtdlpWorker (priority 40) handles video tweets — both claim `twitter.com`/`x.com`, so gallery-dl is tried first
