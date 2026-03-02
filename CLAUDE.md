# MMI — Modular Media Ingestor

Standalone tool. Not an Atlas spoke.

## Architecture
Priority-ordered worker chain. Workers are discovered and sorted by `priority` int.
Adding a new site = add one file in `mmi/engine/`, subclass `BaseWorker`. No core changes.

## Worker Priority Order
| Priority | Worker | Sites |
|----------|--------|-------|
| 10 | RumbleWorker | rumble.com, rmbl.ws |
| 20 | OdyseeWorker | odysee.com |
| 30 | GalleryWorker | instagram, reddit, imgur (gallery-dl) |
| 40 | YtdlpWorker | youtube, vimeo, twitter, etc. |
| 100 | GenericWorker | catch-all fallback |

`CustomWorker` is not auto-routed — invoked only via `--m3u8` CLI flag.

## Key Rules
- `download()` never raises — always returns `IngestionResult`
- `can_handle()` for CustomWorker always returns False
- DB lives inside `MMI_OUTPUT_DIR` for portability
- Failure bundles written to `MMI_OUTPUT_DIR/debug/`
- All file opens use `encoding='utf-8'`
- Column is `download_status` (not `status`) — globally unique per CLAUDE.md rule 17

## Adding a New Worker
1. Create `mmi/engine/mysite_worker.py`
2. Subclass `BaseWorker`, set `priority` (pick a gap between existing workers)
3. Implement `can_handle(url) -> bool` and `download(url, output_dir) -> IngestionResult`
4. No registration needed — Router auto-discovers all BaseWorker subclasses

## Output Directory
Default: `./downloads/` (relative to CWD), overridable via `-o` flag or `MMI_OUTPUT_DIR` env var.
