# MMI — Modular Media Ingestor

A priority-ordered worker chain for downloading media from virtually any website.
Point it at a URL — it figures out the right tool automatically.

```
mmi https://rumble.com/v123-video.html
mmi https://www.facebook.com/reel/1253338540224786
mmi https://odysee.com/@channel/video
mmi https://youtube.com/watch?v=abc
mmi --m3u8 https://stream.example.com/live.m3u8 --referer https://example.com/page
```

---

## Install

**Requirements:** Python 3.9+, [yt-dlp](https://github.com/yt-dlp/yt-dlp), [gallery-dl](https://github.com/mikf/gallery-dl), [ffmpeg](https://ffmpeg.org/) (for m3u8 only)

```bash
# Clone and install
git clone <repo>
cd Syllego
pip install -e .

# With dev/test deps
pip install -e ".[dev]"
```

---

## Usage

```bash
# Auto-route to the best available worker
mmi https://rumble.com/v123-video.html

# Download an HLS m3u8 stream with ffmpeg
mmi --m3u8 https://stream.example.com/live.m3u8 --referer https://example.com/page

# Override the output directory
mmi -o /path/to/downloads https://odysee.com/@channel/video

# Show recent download history
mmi --history

# Verbose/debug logging
mmi -v https://youtube.com/watch?v=abc

# Show version
mmi --version
```

### Output

Files are saved to `./downloads/` by default (set `MMI_OUTPUT_DIR` env var or use `-o` to override).
Download history is stored in `./downloads/mmi_history.db` (SQLite, moves with the folder).
Failed download details are written to `./downloads/debug/failure_bundle_*.json`.

---

## How It Works

Workers are tried in priority order. The first one that claims the URL and succeeds wins.

| Priority | Worker | Sites |
|----------|--------|-------|
| 10 | **RumbleWorker** | rumble.com, rmbl.ws |
| 20 | **OdyseeWorker** | odysee.com |
| 30 | **GalleryWorker** | instagram, reddit, imgur, deviantart, pixiv, flickr, x.com/twitter (images), artstation, danbooru, gelbooru |
| 40 | **YtdlpWorker** | youtube, vimeo, tiktok, facebook, twitch, dailymotion, twitter (video), bilibili, soundcloud, bandcamp, mixcloud |
| 100 | **GenericWorker** | everything else — tries yt-dlp generic extractor, then httpx direct download |

`CustomWorker` (ffmpeg m3u8) is only invoked via `--m3u8` — never auto-routed.

---

## Python API

```python
import mmi

# Auto-route
result = mmi.ingest("https://rumble.com/v123-video.html")
if result.success:
    print(f"Saved to: {result.filename}")
else:
    print(f"Failed: {result.error_message}")

# Manual m3u8
result = mmi.ingest_m3u8(
    stream_url="https://stream.example.com/live.m3u8",
    referer="https://example.com/page",
)

# Custom output directory
from pathlib import Path
result = mmi.ingest("https://...", output_dir=Path("/my/downloads"))
```

### `IngestionResult`

```python
result.success        # bool
result.url            # original URL
result.worker_name    # which worker handled it
result.filename       # path to saved file (None on failure)
result.error_code     # HTTP status or short label (None on success)
result.error_message  # human-readable error (None on success)
result.stack_trace    # full traceback string (None if no exception)
result.metadata       # dict of worker-specific extras
```

---

## Adding a Worker

One file, no registration:

```python
# mmi/engine/mysite_worker.py
from pathlib import Path
from mmi.engine._ytdlp_common import run_ytdlp
from mmi.engine.base import BaseWorker, IngestionResult

class MySiteWorker(BaseWorker):
    priority = 35  # pick a gap between existing priorities

    def can_handle(self, url: str) -> bool:
        return "mysite.com" in url

    def download(self, url: str, output_dir: Path) -> IngestionResult:
        return run_ytdlp(url=url, output_dir=output_dir, worker_name=type(self).__name__)
```

The Router discovers it automatically. Add tests in `tests/engine/test_mysite_worker.py`.

---

## Development

```bash
# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=mmi --cov-report=term-missing

# Run a single file
pytest tests/engine/test_router.py -v
```

**Test stats:** 205 tests, 99% coverage. All subprocess/HTTP calls are mocked — no real binaries needed to run the suite.

---

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `MMI_OUTPUT_DIR` | `./downloads` | Where files are saved |

The debug dir (`MMI_OUTPUT_DIR/debug/`) and DB (`MMI_OUTPUT_DIR/mmi_history.db`) always follow the output dir — move the folder, everything moves with it.
