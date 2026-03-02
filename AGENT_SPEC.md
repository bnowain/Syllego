# MMI (Syllego) — Agent Specification

**Version:** 0.1.0
**Type:** Standalone CLI tool + Python library
**Purpose:** Download media (video, audio, images) from any URL — auto-routes to the correct strategy per platform.

---

## Quick Decision Guide

| You have | Use |
|----------|-----|
| A page URL (YouTube, Facebook, Rumble, etc.) | `mmi.ingest(url)` |
| A raw `.m3u8` stream URL you already found | `mmi.ingest_m3u8(stream_url, referer)` |
| Multiple URLs to download | Call `mmi.ingest(url)` in a loop |
| Just need to shell out | `mmi <url>` via CLI |

---

## Python API (preferred for agents)

### Install

```bash
pip install -e "E:/0-Automated-Apps/random-app-dev/Syllego"
```

### Import

```python
import mmi
from mmi import IngestionResult
```

### `mmi.ingest(url, output_dir=None) → IngestionResult`

Downloads media from any URL. Auto-routes to the best worker.

```python
result = mmi.ingest("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

if result.success:
    print(result.filename)   # absolute path to saved file
else:
    print(result.error_code)    # e.g. "403", "NO_STREAM_FOUND"
    print(result.error_message) # human-readable description
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | Any media page URL |
| `output_dir` | `Path \| None` | `./downloads/` | Where to save the file |

### `mmi.ingest_m3u8(stream_url, referer, output_dir=None) → IngestionResult`

Use this when you already have a raw HLS stream URL (e.g. from network inspection). Bypasses URL routing entirely — always uses ffmpeg.

```python
result = mmi.ingest_m3u8(
    stream_url="https://cdn.example.com/video/playlist.m3u8",
    referer="https://www.example.com/watch/video-123",
)
```

---

## IngestionResult Fields

```python
@dataclass
class IngestionResult:
    success: bool           # True = file saved, False = all workers failed
    url: str                # The original URL passed in
    worker_name: str        # Which worker handled it (e.g. "YtdlpWorker")
    filename: str | None    # Absolute path of the saved file (None on failure)
    error_code: str | None  # Short error label (see table below)
    error_message: str | None  # Full human-readable error
    stack_trace: str | None    # Python traceback string (on exceptions)
    page_html: str | None      # Raw page HTML captured on failure (for debugging)
    metadata: dict             # Worker-specific extras (e.g. {"stream_url": "..."})
```

### Checking results

```python
result = mmi.ingest(url)

# Minimal check
if not result.success:
    raise RuntimeError(f"Download failed: {result.error_code} — {result.error_message}")

# Access the file
from pathlib import Path
file_path = Path(result.filename)
file_size_mb = file_path.stat().st_size / (1024 * 1024)
```

---

## Worker Chain (priority order)

Workers are tried in ascending priority order. The first successful result wins. Failed workers are skipped and the next is tried automatically.

| Priority | Worker | Handles | Strategy |
|----------|--------|---------|----------|
| 0 | CustomWorker | *(never auto-routed)* | m3u8 via ffmpeg |
| 10 | RumbleWorker | rumble.com, rmbl.ws | yt-dlp + cookies |
| 20 | OdyseeWorker | odysee.com | yt-dlp |
| 30 | GalleryWorker | instagram, reddit, imgur, deviantart, pixiv, flickr, x.com, artstation, danbooru, gelbooru | gallery-dl |
| **35** | **FacebookWorker** | **facebook.com, fb.watch** | **Tor + stealth Playwright (always default for Facebook)** |
| 40 | YtdlpWorker | youtube, youtu.be, vimeo, tiktok, facebook\*, twitch, dailymotion, twitter, bilibili, soundcloud, bandcamp, mixcloud | yt-dlp |
| 85 | PlaywrightWorker | rumble.com, rmbl.ws | Headless Chromium — intercepts CDN URL |
| 87 | RumbleStealthWorker | rumble.com, rmbl.ws | Tor + stealth Playwright |
| 100 | GenericWorker | *everything else* | yt-dlp generic → httpx direct download |

\* Facebook URLs go to FacebookWorker (35) first — YtdlpWorker (40) is only the fallback.

**You do not need to pick a worker.** Pass the URL to `mmi.ingest()` and the chain handles it.

---

## Error Codes

| Code | Meaning | What to try |
|------|---------|-------------|
| `403` | HTTP 403 Forbidden | Site blocked yt-dlp; a higher-priority worker should handle it automatically |
| `YTDLP_NOT_FOUND` | yt-dlp not installed | `pip install yt-dlp` |
| `FFMPEG_NOT_FOUND` | ffmpeg not installed | Install ffmpeg and add to PATH |
| `GALLERY_DL_NOT_FOUND` | gallery-dl not installed | `pip install gallery-dl` |
| `PLAYWRIGHT_NOT_INSTALLED` | Playwright not installed | `pip install playwright && playwright install chromium` |
| `STEALTH_NOT_AVAILABLE` | Facebook-Monitor stealth system missing | Check `E:/0-Automated-Apps/Facebook-Monitor` exists |
| `TOR_START_FAILED` | Could not start Tor | Check `tor-bundle/tor/tor.exe` in Facebook-Monitor |
| `NO_STREAM_FOUND` | Browser opened page but no video URL intercepted | Video may require login or interaction |
| `NO_WORKER` | No worker matched the URL | URL may not contain media |
| `DIRECT_DOWNLOAD_FAILED` | httpx stream failed | URL may not be a direct file link |
| `STEALTH_BROWSE_FAILED` | Stealth browser threw an exception | Check Tor is running; may be a nested Playwright conflict |
| `URL_DISCOVERY_FAILED` | *(live test only)* | Search engine returned no matching URLs |

---

## Configuration

All configuration is via environment variable or defaults — no config file needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `MMI_OUTPUT_DIR` | `./downloads/` (relative to CWD) | Where files are saved |

The debug directory (`MMI_OUTPUT_DIR/debug/`) and SQLite history DB (`MMI_OUTPUT_DIR/mmi_history.db`) are created automatically inside the output directory.

### Override output directory in code

```python
from pathlib import Path

result = mmi.ingest(url, output_dir=Path("/my/custom/path"))
```

---

## CLI Reference

For agents that prefer shell commands over Python imports.

```bash
# Download any URL
mmi <url>

# Download to a specific directory
mmi -o /path/to/dir <url>

# Provide a raw m3u8 stream directly
mmi --m3u8 <stream_url> --referer <page_url>

# Show recent download history
mmi --history

# Harvest browser cookies (helps Rumble bypass 403)
mmi --harvest-cookies

# Verbose logging (shows which workers were tried)
mmi -v <url>
```

**Exit codes:** `0` = success, `1` = failure.

---

## Platform-Specific Notes

### YouTube
- Works without authentication for public videos.
- Uses yt-dlp (YtdlpWorker, priority 40).
- Age-restricted or private videos require cookies — not currently supported automatically.

### Facebook
- **Always routes through stealth Tor+Playwright first** (FacebookWorker, priority 35).
- Each download uses a fresh randomized browser fingerprint and Tor circuit.
- Requires `E:/0-Automated-Apps/Facebook-Monitor` with `stealth.py` and `tor_pool.py`.
- Tor must be available on `127.0.0.1:9050` or launchable from `Facebook-Monitor/tor-bundle/`.
- If stealth fails, falls through to YtdlpWorker (yt-dlp handles public Reels well).

### Rumble
- yt-dlp (RumbleWorker) fails with 403 without cookies.
- PlaywrightWorker (priority 85) catches this: opens real Chromium, intercepts the CDN URL.
- RumbleStealthWorker (priority 87) is the Tor+stealth last resort.
- To pre-harvest cookies: `mmi --harvest-cookies` (stores at `MMI_OUTPUT_DIR/cookies.txt`).

### Instagram / Reddit / Twitter images
- Routed to GalleryWorker (gallery-dl, priority 30).
- Requires `gallery-dl` installed: `pip install gallery-dl`.
- For authenticated content, configure `~/.config/gallery-dl/config.json`.

### Twitter/X video
- Both GalleryWorker (30) and YtdlpWorker (40) claim twitter.com / x.com.
- GalleryWorker is tried first (priority 30) — handles image tweets well.
- YtdlpWorker handles video tweets as fallback.

### Unknown / generic URLs
- GenericWorker (priority 100) always fires last.
- Tries yt-dlp generic extractor first, then httpx direct download.
- Works for direct `.mp4`, `.pdf`, `.zip`, etc. links.

---

## Download History

All downloads (success and failure) are recorded automatically to SQLite.

```python
from mmi.db.history import get_recent

rows = get_recent(limit=10)
for row in rows:
    print(row["url"], row["download_status"], row["worker_name"], row["filename"])
```

**Schema columns:** `id`, `url`, `download_status` (`"success"` or `"failed"`), `worker_name`, `filename`, `timestamp` (ISO 8601 UTC), `error_message`.

---

## Full Working Examples

### Download a YouTube video

```python
import mmi
from pathlib import Path

result = mmi.ingest(
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir=Path("./my_videos"),
)
if result.success:
    print(f"Saved: {result.filename}")
    print(f"Worker: {result.worker_name}")
else:
    print(f"Failed: {result.error_code} — {result.error_message}")
```

### Download and verify file exists

```python
import mmi
from pathlib import Path

result = mmi.ingest("https://rumble.com/v76hu5c-some-video.html")
if result.success and result.filename:
    path = Path(result.filename)
    if path.exists():
        print(f"Downloaded {path.stat().st_size / 1e6:.1f} MB → {path.name}")
```

### Batch download with error collection

```python
import mmi

urls = [
    "https://www.youtube.com/watch?v=abc123",
    "https://rumble.com/vabc123-title.html",
    "https://www.facebook.com/watch?v=123456789",
]

failures = []
for url in urls:
    result = mmi.ingest(url)
    if result.success:
        print(f"[OK]   {result.worker_name} → {result.filename}")
    else:
        print(f"[FAIL] {url}: {result.error_code}")
        failures.append(result)
```

### Manual m3u8 (when you already have the stream URL)

```python
import mmi

result = mmi.ingest_m3u8(
    stream_url="https://cdn.example.com/hls/video/playlist.m3u8",
    referer="https://www.example.com/videos/some-video",
)
```

---

## Prerequisites Checklist

| Dependency | Required for | Install |
|------------|-------------|---------|
| `yt-dlp` | YouTube, Vimeo, TikTok, Facebook fallback, Rumble, Odysee, generic | `pip install yt-dlp` |
| `ffmpeg` | HLS stream stitching (m3u8 downloads) | [ffmpeg.org](https://ffmpeg.org/download.html) + add to PATH |
| `httpx` | Direct file downloads, Facebook CDN | `pip install httpx` |
| `playwright` + chromium | Rumble (PlaywrightWorker), RumbleStealthWorker, FacebookWorker | `pip install playwright && playwright install chromium` |
| `gallery-dl` | Instagram, Reddit, Imgur, etc. | `pip install gallery-dl` |
| Facebook-Monitor stealth system | Facebook downloads (primary path) | `E:/0-Automated-Apps/Facebook-Monitor` must exist |
| Tor | Facebook and Rumble stealth workers | Running on `127.0.0.1:9050`, or launchable from Facebook-Monitor |

**Minimum to handle YouTube/Vimeo/TikTok:** `yt-dlp` only.
**Minimum to handle Rumble:** `yt-dlp` + `playwright` + chromium.
**Minimum to handle Facebook:** `playwright` + chromium + Facebook-Monitor stealth system + Tor.

---

## What NOT to Do

- **Do not import individual workers directly.** Always use `mmi.ingest()` — it handles fallback automatically.
- **Do not call `download()` directly on a worker.** Use `safe_download()` or go through the Router.
- **Do not assume `filename` is set on success.** Always check `result.filename is not None` before accessing it.
- **Do not reuse the output dir for temporary files.** The router creates files there; don't write to it from the calling agent.
- **Do not run `mmi.ingest()` while a `sync_playwright()` context is open in the same thread.** FacebookWorker and RumbleStealthWorker open their own Playwright sessions — nesting them causes `RuntimeError`. If you're running a Playwright session yourself, close it before calling `mmi.ingest()` for Facebook/Rumble.
