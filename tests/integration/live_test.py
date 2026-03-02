"""
tests/integration/live_test.py — Live end-to-end download test suite.

Phase 1 — URL Discovery (browser open):
  Opens headless Chromium, searches DuckDuckGo (HTML) for each platform,
  and extracts the first real public video URL matching the platform pattern.
  Browser is fully closed after all URLs are found.

Phase 2 — Download (no browser):
  Passes each discovered URL through the MMI router (mmi.ingest(url)).
  Keeping the two phases separate prevents nested sync_playwright() conflicts
  when FacebookWorker / RumbleStealthWorker open their own Playwright sessions.

Phase 3 — Report:
  Prints a summary table and exits 0 if all platforms passed, 1 otherwise.

Usage:
  python tests/integration/live_test.py                  # all platforms
  python tests/integration/live_test.py --platform YouTube
  python tests/integration/live_test.py --platform Rumble
  python tests/integration/live_test.py --platform Odysee
  python tests/integration/live_test.py --platform Facebook
  python tests/integration/live_test.py --keep           # keep downloaded files
  python tests/integration/live_test.py -v               # verbose/debug logging
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Make mmi importable regardless of CWD
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mmi.config import get_logger

logger = get_logger("mmi.live_test")

# Persistent Chromium profile — survives between runs so cookies/session look real.
# Stored inside the project so it's easy to wipe; gitignored.
_BROWSER_PROFILE_DIR = Path(__file__).resolve().parents[2] / ".browser_profile"

# Injected on every page before any scripts run — removes the webdriver fingerprint.
_STEALTH_INIT_SCRIPT = """
    // Remove the #1 bot-detection signal
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

    // Add chrome runtime object that headless Chrome omits
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
    };

    // Report real-looking plugins list
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = [1, 2, 3, 4, 5];
            arr.__proto__ = {
                namedItem: () => null,
                item: () => null,
                refresh: () => {},
            };
            return arr;
        }
    });

    // Report US English as language preference
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});

    // Fix permissions API (headless returns wrong state)
    const _origPermQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) => (
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : _origPermQuery(params)
    );
"""


# ---------------------------------------------------------------------------
# Platform definitions
# ---------------------------------------------------------------------------

@dataclass
class Platform:
    name: str
    browse_urls: list[str]                  # platform pages to navigate — tried in order
    url_must_contain: str                   # required substring in the extracted URL
    url_must_contain_any: tuple[str, ...] = field(default_factory=tuple)  # OR check
    url_must_not_contain: tuple[str, ...] = field(default_factory=tuple)  # blocklist


ALL_PLATFORMS: list[Platform] = [
    Platform(
        name="YouTube",
        # Search results page — works without login, reliably returns /watch?v= links
        browse_urls=[
            "https://www.youtube.com/results?search_query=popular+video",
        ],
        url_must_contain="youtube.com/watch?v=",
        # Strip playlist/radio extras — keep only the bare watch URL
        url_must_not_contain=("&list=", "&start_radio=", "/shorts/"),
    ),
    Platform(
        name="Rumble",
        browse_urls=[
            "https://rumble.com/videos?date=today",
            "https://rumble.com/",
        ],
        url_must_contain="rumble.com/v",
        url_must_not_contain=("rumble.com/videos", "rumble.com/video-", "rumble.com/vip"),
    ),
    Platform(
        name="Facebook",
        # Public pages' video tabs — visible without login
        browse_urls=[
            "https://www.facebook.com/FacebookApp/videos/",
            "https://www.facebook.com/Meta/videos/",
            "https://www.facebook.com/watch",
        ],
        url_must_contain="facebook.com",
        url_must_contain_any=("facebook.com/reel/", "facebook.com/watch/?v=",
                              "facebook.com/watch?v=", "/videos/"),
        url_must_not_contain=("/posts/", "facebook.com/groups", "facebook.com/events",
                              "facebook.com/marketplace", "facebook.com/pages/"),
    ),
]


# ---------------------------------------------------------------------------
# Phase 1 — URL discovery via DuckDuckGo HTML
# ---------------------------------------------------------------------------

_SKIP_FRAGMENTS = (
    "/help/", "/support/", "/about/", "?hl=",
    "google.com", "bing.com", "duckduckgo.com",
)


def discover_url(platform: Platform, page) -> str | None:
    """
    Navigate directly to the platform's own browse/trending page and extract
    the first public video URL that matches the platform's URL pattern.
    No search engine involved — avoids CAPTCHA entirely.
    Tries each browse_url in order until one yields a match.
    """
    for browse_url in platform.browse_urls:
        logger.debug("Navigating to %s for %s", browse_url, platform.name)
        try:
            page.goto(browse_url, wait_until="domcontentloaded", timeout=25_000)
        except Exception as exc:
            logger.debug("Navigation error (continuing): %s", exc)

        # Let JS-rendered video grids populate, then scroll to trigger lazy loading
        page.wait_for_timeout(3000)
        try:
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(2000)
        except Exception:
            pass

        try:
            hrefs: list[str] = page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
            )
        except Exception:
            hrefs = []

        url = _first_matching(hrefs, platform)
        if url:
            return url

    return None


def _first_matching(hrefs: list[str], platform: Platform) -> str | None:
    for href in hrefs:
        if not href or not href.startswith("http"):
            continue
        if platform.url_must_contain not in href:
            continue
        if any(excl in href for excl in platform.url_must_not_contain):
            continue
        if platform.url_must_contain_any and not any(p in href for p in platform.url_must_contain_any):
            continue
        if any(skip in href for skip in _SKIP_FRAGMENTS):
            continue
        # Platform-specific validators
        if not _platform_validate(platform.name, href):
            continue
        return href
    return None


def _platform_validate(platform_name: str, href: str) -> bool:
    """Extra per-platform validation that can't be expressed as simple substring checks."""
    if platform_name == "Odysee":
        # Must be a video URL: /@channel:x/video-slug:x
        # Channel-only URLs are /@channel:x (one segment) — reject those
        path = urlparse(href).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        # Need at least 2 path parts: the @channel and the video slug
        return len(parts) >= 2 and parts[0].startswith("@")
    if platform_name == "Facebook":
        # Reject the bare Watch homepage (no specific video)
        path = urlparse(href).path.rstrip("/")
        if path in ("/watch", ""):
            return False
    return True


# ---------------------------------------------------------------------------
# Phase 2 — Download via MMI router
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    platform: str
    discovered_url: str | None
    worker_used: str | None
    download_success: bool
    filename: str | None
    file_size_mb: float | None
    error_code: str | None
    error_message: str | None


def run_download(url: str, output_dir: Path) -> TestResult:
    from mmi.engine.router import Router

    router = Router(output_dir=output_dir)
    result = router.ingest(url)

    file_size = None
    if result.filename:
        p = Path(result.filename)
        if p.exists():
            file_size = p.stat().st_size / (1024 * 1024)

    return TestResult(
        platform="",            # filled in by caller
        discovered_url=url,
        worker_used=result.worker_name,
        download_success=result.success,
        filename=result.filename,
        file_size_mb=file_size,
        error_code=result.error_code,
        error_message=result.error_message,
    )


# ---------------------------------------------------------------------------
# Main test runner — two strictly separated phases
# ---------------------------------------------------------------------------

def run_tests(
    platforms: list[Platform],
    keep_files: bool = False,
) -> list[TestResult]:
    from playwright.sync_api import sync_playwright

    # ── Phase 1: URL discovery (browser open) ──────────────────────────────
    print("\n--- Phase 1: URL Discovery ---")
    discovered: dict[str, str | None] = {}

    # Persistent profile directory — cookies and session state survive between
    # runs, making the browser look like a real returning user to search engines.
    _BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(_BROWSER_PROFILE_DIR),
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )
        # Inject stealth overrides into every page before any scripts load
        context.add_init_script(_STEALTH_INIT_SCRIPT)
        page = context.new_page()

        for i, platform in enumerate(platforms):
            print(f"  Searching for {platform.name}...", end=" ", flush=True)
            url = discover_url(platform, page)
            discovered[platform.name] = url
            if url:
                print(f"found.")
                print(f"    {url}")
            else:
                print(f"not found.")
            if i < len(platforms) - 1:
                time.sleep(2)      # polite pause between searches

        context.close()
    # ── browser fully closed — safe to open new Playwright sessions below ──

    # ── Phase 2: Downloads ─────────────────────────────────────────────────
    print("\n--- Phase 2: Downloads ---")

    if keep_files:
        output_dir = Path("mmi_live_test_output")
        output_dir.mkdir(exist_ok=True)
        print(f"  Files kept in: {output_dir.resolve()}")
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="mmi_live_"))

    results: list[TestResult] = []

    try:
        for platform in platforms:
            _print_header(platform.name)
            url = discovered.get(platform.name)

            if not url:
                print(f"  [SKIP] URL discovery failed — nothing to download.")
                results.append(TestResult(
                    platform=platform.name,
                    discovered_url=None,
                    worker_used=None,
                    download_success=False,
                    filename=None,
                    file_size_mb=None,
                    error_code="URL_DISCOVERY_FAILED",
                    error_message="DuckDuckGo and Google returned no matching URLs",
                ))
                continue

            print(f"  URL:  {url}")
            print(f"  Downloading...", flush=True)

            result = run_download(url, output_dir)
            result.platform = platform.name

            if result.download_success:
                size_str = f"{result.file_size_mb:.1f} MB" if result.file_size_mb is not None else "size unknown"
                print(f"  [OK]  Worker: {result.worker_used}  |  Size: {size_str}")
                if not keep_files and result.filename:
                    try:
                        Path(result.filename).unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                print(f"  [FAIL] {result.worker_used}: ({result.error_code}) {result.error_message}")

            results.append(result)

    finally:
        if not keep_files:
            shutil.rmtree(output_dir, ignore_errors=True)

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_summary(results: list[TestResult]) -> None:
    passed = [r for r in results if r.download_success]

    print(f"\n{'='*65}")
    print("  SUMMARY")
    print(f"{'='*65}")
    print(f"  {len(passed)}/{len(results)} platforms succeeded\n")

    for r in results:
        status = "PASS" if r.download_success else "FAIL"
        size_str = f"  ({r.file_size_mb:.1f} MB)" if r.file_size_mb is not None else ""
        worker_str = f"  via {r.worker_used}" if r.worker_used else ""
        print(f"  [{status}] {r.platform}{size_str}{worker_str}")
        if r.discovered_url:
            print(f"         URL:   {r.discovered_url}")
        if r.error_message:
            msg = r.error_message[:120]
            print(f"         Error: ({r.error_code}) {msg}")

    print(f"\n{'='*65}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _print_header(name: str) -> None:
    print(f"\n{'─'*65}")
    print(f"  {name}")
    print(f"{'─'*65}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="MMI live integration test — discovers real URLs then downloads them"
    )
    parser.add_argument(
        "--platform",
        metavar="NAME",
        help="Test only one platform: YouTube, Rumble, Odysee, Facebook",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep downloaded files in ./mmi_live_test_output/",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.getLogger("mmi").setLevel(logging.DEBUG)

    platforms = ALL_PLATFORMS
    if args.platform:
        platforms = [p for p in ALL_PLATFORMS if p.name.lower() == args.platform.lower()]
        if not platforms:
            names = ", ".join(p.name for p in ALL_PLATFORMS)
            print(f"Unknown platform '{args.platform}'. Choose from: {names}")
            sys.exit(1)

    print("\nMMI Live Integration Test")
    print("Phase 1: Playwright + DuckDuckGo discovers real video URLs")
    print("Phase 2: MMI router downloads each one")
    print("Phase 3: Summary\n")

    results = run_tests(platforms, keep_files=args.keep)
    print_summary(results)

    sys.exit(0 if all(r.download_success for r in results) else 1)


if __name__ == "__main__":
    main()
