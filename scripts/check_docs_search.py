#!/usr/bin/env python3
"""Real-browser search regression for a generated Zensical site.

Serves the built site over HTTP on an ephemeral localhost port and drives
Chromium (Playwright) through the search interface: open it, type a known
indexed term, wait for results, open one and check the destination loads.
Zensical's search is a shadow-DOM dialog, so elements are found by ARIA role
(`combobox`, `option`), never by Material CSS classes. Direct `file://` access
is out of scope: the search index is fetched over HTTP.

    python scripts/check_docs_search.py --site SITE [--self-test]
                                        [--diagnostics-dir DIR]

Exit status: 0 = all scenarios passed (and, with --self-test, every mutation
was detected); 1 = a check failed; 2 = the check could not run (Playwright or
Chromium missing). Nothing that fails to run is ever reported as a pass.

Prerequisites: `pip install -r docs/requirements-docs-browser.txt` and
`python -m playwright install chromium`.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlsplit

TERM = "chromosome"
TIMEOUT_MS = 8000
DESKTOP = {"width": 1280, "height": 900}
MOBILE = {"width": 390, "height": 844}


@dataclass(frozen=True)
class Scenario:
    name: str
    viewport: dict[str, int]
    activation: str  # "mouse" or "keyboard"


SCENARIOS = (
    Scenario("desktop-mouse", DESKTOP, "mouse"),
    Scenario("desktop-keyboard", DESKTOP, "keyboard"),
    Scenario("mobile-mouse", MOBILE, "mouse"),
)


class BrowserUnavailable(RuntimeError):
    """Playwright or its Chromium build cannot be used (exit status 2)."""


# --- HTTP server ------------------------------------------------------------


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static files only: no request logging and no directory listings.

    A listing is a 200 page with an <h1>; without this a missing page would
    look like a successful navigation.
    """

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def list_directory(self, path):
        self.send_error(404, "No permission to list directory")
        return None


@contextlib.contextmanager
def serving(site: Path, ready_timeout: float = 10.0) -> Iterator[str]:
    """Serve `site` on 127.0.0.1:<ephemeral port>; always shut down on exit."""
    handler = functools.partial(_QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        _wait_until_ready(base, ready_timeout)
        yield base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_until_ready(base: str, timeout: float) -> None:
    """Bounded polling until the server answers (no fixed sleeps)."""
    deadline = time.monotonic() + timeout
    pause = threading.Event()
    last: object = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base, timeout=2):
                return
        except urllib.error.HTTPError:
            return  # the server answered, whatever the status
        except OSError as exc:
            last = exc
            pause.wait(0.05)
    raise RuntimeError(f"HTTP server at {base} not ready within {timeout}s: {last}")


# --- browser scenarios ------------------------------------------------------


def _import_playwright():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised via exit status 2
        raise BrowserUnavailable(f"playwright is not installed: {exc}") from exc
    return sync_playwright, PlaywrightError, PlaywrightTimeout


def _run_scenario(browser, base: str, scenario: Scenario, term: str, timeout_ms: int,
                  diagnostics: Path | None, timeout_error: type[Exception]) -> list[str]:
    origin = urlsplit(base).netloc
    problems: list[str] = []
    log: list[str] = []
    context = browser.new_context(viewport=scenario.viewport)
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    def same_origin(url: str) -> bool:
        return urlsplit(url).netloc == origin

    page.on("pageerror", lambda exc: log.append(f"pageerror: {exc}"))
    page.on("console", lambda m: log.append(f"console.{m.type}: {m.text}")
            if m.type == "error" and same_origin(m.location.get("url", base)) else None)
    page.on("requestfailed", lambda r: log.append(f"request failed: {r.url} {r.failure}") if same_origin(r.url) else None)
    page.on("response", lambda r: log.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 and same_origin(r.url) else None)

    prefix = scenario.name
    try:
        page.goto(base, wait_until="networkidle")
        _activate(page, scenario)
        combobox = page.get_by_role("combobox").first
        try:
            combobox.wait_for(state="visible")
        except timeout_error:
            problems.append(f"{prefix}: search input did not appear after activation")
            return problems
        combobox.click()
        combobox.press_sequentially(term, delay=20)
        options = page.get_by_role("option")
        try:
            options.first.wait_for(state="visible")
        except timeout_error:
            problems.append(f"{prefix}: no results for {term!r}")
            return problems
        texts = [t.lower() for t in options.all_inner_texts()]
        if not any(term in t for t in texts):
            problems.append(f"{prefix}: {len(texts)} results but none mention {term!r}")
        try:
            with page.expect_navigation() as navigation:
                options.first.click()
            response = navigation.value
        except timeout_error:
            problems.append(f"{prefix}: selecting a result did not navigate")
            return problems
        if response is None or not response.ok:
            status = "no response" if response is None else response.status
            problems.append(f"{prefix}: result navigation failed ({status}) at {page.url}")
            return problems
        page.get_by_role("main").get_by_role("heading", level=1).first.wait_for(state="visible")
        if not page.title().strip():
            problems.append(f"{prefix}: destination page has an empty title")
    except timeout_error as exc:
        problems.append(f"{prefix}: timed out: {str(exc).splitlines()[0]}")
    except Exception as exc:  # noqa: BLE001 - report, never swallow
        problems.append(f"{prefix}: {type(exc).__name__}: {str(exc).splitlines()[0]}")
    finally:
        problems += [f"{prefix}: {entry}" for entry in log]
        if problems and diagnostics is not None:
            diagnostics.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(Exception):
                page.screenshot(path=str(diagnostics / f"{scenario.name}.png"))
            (diagnostics / f"{scenario.name}.txt").write_text("\n".join(problems) + "\n", "utf-8")
        context.close()
    return problems


def _activate(page, scenario: Scenario) -> None:
    if scenario.activation == "keyboard":
        page.keyboard.press("ControlOrMeta+k")
    elif scenario.viewport["width"] < 600:
        # Mobile: the header search control is the label for the `__search` toggle.
        page.locator("label[for='__search']").locator("visible=true").first.click()
    else:
        page.get_by_role("button", name="Search").click()


def check_site(site: Path, term: str = TERM, timeout_ms: int = TIMEOUT_MS,
               diagnostics: Path | None = None) -> list[str]:
    """Run every scenario against `site`; return problems (empty list = pass)."""
    sync_playwright, playwright_error, timeout_error = _import_playwright()
    problems: list[str] = []
    index = site / "search.json"
    if not index.is_file():
        problems.append("search.json is missing")
    else:
        try:
            data = json.loads(index.read_text("utf-8"))
            if not (data.get("items") or data.get("docs")):
                problems.append("search.json has no searchable entries")
        except ValueError as exc:
            problems.append(f"search.json is not valid JSON: {exc}")
    with serving(site) as base, sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except playwright_error as exc:
            raise BrowserUnavailable(f"Chromium cannot be launched: {str(exc).splitlines()[0]}") from exc
        try:
            for scenario in SCENARIOS:
                problems += _run_scenario(browser, base, scenario, term, timeout_ms, diagnostics, timeout_error)
        finally:
            browser.close()
    return problems


# --- mutation self-test -----------------------------------------------------


def _missing_index(root: Path) -> None:
    (root / "search.json").unlink()


def _empty_index(root: Path) -> None:
    path = root / "search.json"
    data = json.loads(path.read_text("utf-8"))
    data["items"] = []
    path.write_text(json.dumps(data), "utf-8")


def _no_javascript(root: Path) -> None:
    path = root / "index.html"
    html = path.read_text("utf-8")
    path.write_text(re.sub(r"<script\b[^>]*\bsrc=[^>]*>\s*</script>", "", html), "utf-8")


def _unreachable_results(root: Path) -> None:
    for page in root.rglob("*.html"):
        if page.relative_to(root).as_posix() not in {"index.html", "404.html"}:
            page.unlink()


# name -> (mutation, text the browser-level problem must contain)
MUTATIONS: dict[str, tuple[Callable[[Path], None], str]] = {
    "search.json missing": (_missing_index, "search input did not appear"),
    "search.json without entries": (_empty_index, "no results for"),
    "search interface cannot be activated": (_no_javascript, "search input did not appear"),
    "result cannot be navigated to": (_unreachable_results, "navigation failed"),
}


def self_test(site: Path, term: str, timeout_ms: int) -> list[str]:
    """Each mutation, applied to an isolated copy, must be caught by the browser."""
    failures: list[str] = []
    for name, (mutate, expected) in MUTATIONS.items():
        with tempfile.TemporaryDirectory(prefix="docs-search-mutation-") as tmp:
            copy = Path(tmp) / "site"
            shutil.copytree(site, copy)
            mutate(copy)
            problems = check_site(copy, term, timeout_ms)
        caught = any(expected in p for p in problems)
        print(f"  mutation {name!r}: {'detected' if caught else 'NOT DETECTED'}")
        if not caught:
            failures.append(f"mutation {name!r} was not detected by the browser check (wanted {expected!r})")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--term", default=TERM)
    parser.add_argument("--timeout-ms", type=int, default=TIMEOUT_MS)
    parser.add_argument("--diagnostics-dir", type=Path)
    parser.add_argument("--self-test", action="store_true", help="also prove the check fails on broken sites")
    args = parser.parse_args()
    if not (args.site / "index.html").is_file():
        print(f"FAIL {args.site} is not a built site (no index.html)", file=sys.stderr)
        return 1
    try:
        problems = check_site(args.site, args.term, args.timeout_ms, args.diagnostics_dir)
        print(f"{len(SCENARIOS)} search scenarios run, {len(problems)} problem(s)")
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        if args.self_test:
            print("mutation self-test:")
            failures = self_test(args.site, args.term, min(args.timeout_ms, 4000))
            for failure in failures:
                print(f"FAIL {failure}", file=sys.stderr)
            problems += failures
    except BrowserUnavailable as exc:
        print(f"ERROR cannot run the browser check: {exc}", file=sys.stderr)
        return 2
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
