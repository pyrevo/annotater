#!/usr/bin/env python3
"""Deterministic checks for a built documentation site.

Used by the production ``build`` job of the docs workflow to compare the
Zensical build that will be published with a Material for MkDocs build of the
same sources, without depending on generated asset hashes or incidental HTML
formatting.

    python scripts/check_docs_site.py --site SITE --reference MATERIAL_SITE [--self-test]
    python scripts/check_docs_site.py --site SITE --write-inventory   # print pages

Checks: exact page inventory, internal link and anchor resolution, content
anchors, article text parity, navigation structure and order, canonical URLs,
sitemap URLs, the Classic stylesheet variant, and a non-empty search index.
``--self-test`` applies deliberate breakages to isolated copies of the site and
requires each to be detected, proving the gate itself fails closed.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import posixpath
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tests" / "fixtures" / "docs_site_pages.txt"

_ARTICLE = re.compile(r"<article[^>]*>(.*?)</article>", re.S)
_ID = re.compile(r'\bid="([^"]+)"')
_HREF = re.compile(r'<a\b[^>]*?\bhref="([^"]*)"')
_TAG = re.compile(r"<[^>]+>")
_CANONICAL = re.compile(r'<link\s+rel="canonical"\s+href="([^"]*)"')
_LOC = re.compile(r"<loc>([^<]+)</loc>")

# Pages where Material renders a fenced block nested in a 3-space-indented list
# item as inline code with the fence language word ("bash", "text", ...) leaked
# into the text, while Zensical renders a proper code block. The Material output
# is the defect, so on these pages the only accepted difference is the Zensical
# build lacking those language words. Source content is deliberately unchanged.
LEAKED_FENCE_PAGES = {
    "deployment/index.html",
    "preparing-your-data/supported-formats/index.html",
}
_FENCE_WORDS = {"bash", "text", "tsv", "json", "yaml", "python"}


def pages(site: Path) -> list[str]:
    return sorted(p.relative_to(site).as_posix() for p in site.rglob("*.html"))


def article(text: str) -> str:
    match = _ARTICLE.search(text)
    return match.group(1) if match else ""


def content_anchors(text: str) -> set[str]:
    """Anchors in the article body (theme-internal ``__*`` ids excluded)."""
    return {i for i in _ID.findall(article(text)) if not i.startswith("__")}


def normalized_text(text: str) -> str:
    """Article text with tags and all whitespace removed.

    Syntax-highlighting spans and wrappers differ between builders and add or
    remove incidental spacing; the characters themselves must not change.
    """
    body = _TAG.sub("", article(text))
    return re.sub(r"\s+", "", html.unescape(body))


def only_leaked_fence_words(reference: str, built: str) -> bool:
    ops = difflib.SequenceMatcher(None, reference, built, autojunk=False).get_opcodes()
    return all(
        tag == "equal" or (tag == "delete" and reference[i1:i2] in _FENCE_WORDS)
        for tag, i1, i2, _j1, _j2 in ops
    )


def read(site: Path, page: str) -> str:
    return (site / page).read_text("utf-8")


class _PrimaryNav(HTMLParser):
    """Links of the primary navigation (site nav and the active page's TOC)."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.links: list[list[str]] = []
        self._cur: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "nav":
            if self.depth:
                self.depth += 1
            elif "md-nav" in classes and "md-nav--primary" in classes:
                self.depth = 1
        elif tag == "a" and self.depth and "md-nav__link" in classes:
            self._cur = [dict(attrs).get("href") or "", ""]

    def handle_endtag(self, tag):
        if tag == "nav" and self.depth:
            self.depth -= 1
        elif tag == "a" and self._cur is not None:
            self.links.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[1] += data


def navigation(text: str, page: str) -> list[tuple[str, str]]:
    """Primary navigation as ordered (site-root target, label) pairs."""
    parser = _PrimaryNav()
    parser.feed(text)
    out = []
    for href, label in parser.links:
        parts = urlsplit(html.unescape(href))
        target = posixpath.normpath(posixpath.join(posixpath.dirname("/" + page), parts.path or "."))
        out.append((target + (f"#{parts.fragment}" if parts.fragment else ""), " ".join(label.split())))
    return out


def canonical(text: str) -> list[str]:
    return _CANONICAL.findall(text)


def sitemap_urls(site: Path) -> list[str]:
    path = site / "sitemap.xml"
    return sorted(_LOC.findall(path.read_text("utf-8"))) if path.is_file() else []


def check_links(site: Path) -> list[str]:
    """Every relative link in the article body resolves, fragment included."""
    errors: list[str] = []
    known = set(pages(site))
    anchors = {p: {i for i in _ID.findall(read(site, p))} for p in known}
    for page in sorted(known):
        for href in _HREF.findall(article(read(site, page))):
            parts = urlsplit(html.unescape(href))
            if parts.scheme or parts.netloc:
                continue
            target = page
            if parts.path:
                base = (Path("/") / page).parent
                resolved = (base / unquote(parts.path)).resolve().as_posix().lstrip("/")
                if resolved.endswith(".html"):
                    target = resolved
                elif (site / resolved).is_file():
                    continue  # asset or other file
                else:
                    target = f"{resolved.rstrip('/')}/index.html".lstrip("/")
                    if resolved in ("", "."):
                        target = "index.html"
                if target not in known:
                    errors.append(f"{page}: link {href!r} resolves to missing {target}")
                    continue
            if parts.fragment and unquote(parts.fragment) not in anchors[target]:
                errors.append(f"{page}: link {href!r} has missing anchor in {target}")
    return errors


def check(site: Path, reference: Path) -> list[str]:
    errors: list[str] = []
    expected = INVENTORY.read_text("utf-8").split()
    got = pages(site)
    if got != expected:
        errors.append(
            f"page inventory differs: missing={sorted(set(expected) - set(got))} "
            f"unexpected={sorted(set(got) - set(expected))}"
        )
    errors += check_links(site)

    ref_pages = pages(reference)
    if ref_pages != expected:
        errors.append("reference build page inventory differs from the pinned inventory")
    for page in sorted(set(got) & set(ref_pages)):
        a, b = read(reference, page), read(site, page)
        if content_anchors(a) != content_anchors(b):
            errors.append(f"{page}: content anchors differ from the reference build")
        ta, tb = normalized_text(a), normalized_text(b)
        if ta == tb:
            continue
        if page in LEAKED_FENCE_PAGES and only_leaked_fence_words(ta, tb):
            continue
        errors.append(f"{page}: article text differs from the reference build")

    for page in sorted(set(got) & set(ref_pages)):
        a, b = read(reference, page), read(site, page)
        if navigation(a, page) != navigation(b, page):
            errors.append(f"{page}: navigation differs from the reference build")
        if canonical(a) != canonical(b):
            errors.append(f"{page}: canonical URL differs from the reference build")
        elif page != "404.html" and not canonical(b):
            errors.append(f"{page}: canonical URL is missing")

    if sitemap_urls(site) != sitemap_urls(reference) or not sitemap_urls(site):
        errors.append("sitemap URLs differ from the reference build (or the sitemap is empty)")

    home = read(site, "index.html") if "index.html" in got else ""
    if "assets/stylesheets/classic/" not in home or "assets/stylesheets/modern/" in home:
        errors.append("home page does not use the Classic stylesheet variant")

    search = site / "search.json"
    try:
        data = json.loads(search.read_text("utf-8"))
        items = data.get("items") or data.get("docs")
        if not items:
            errors.append("search.json has no entries")
    except (OSError, ValueError) as exc:
        errors.append(f"search.json unreadable: {exc}")
    return errors


# --- mutation self-test -------------------------------------------------------


def _first_article_link(site: Path, fragment: bool = False) -> tuple[str, str]:
    """(page, href) of the first relative article link, optionally with a #fragment."""
    for page in pages(site):
        for href in _HREF.findall(article(read(site, page))):
            parts = urlsplit(html.unescape(href))
            if parts.scheme or parts.netloc or not parts.path:
                continue
            if bool(parts.fragment) == fragment:
                return page, href
    raise RuntimeError("no suitable link found for the mutation")


def _edit(site: Path, page: str, edit: Callable[[str], str]) -> None:
    path = site / page
    before = path.read_text("utf-8")
    after = edit(before)
    if after == before:
        raise RuntimeError(f"mutation changed nothing in {page}")
    path.write_text(after, "utf-8")


def _drop_page(site: Path) -> None:
    (site / "faq" / "index.html").unlink()


def _broken_link(site: Path) -> None:
    page, href = _first_article_link(site)

    def edit(text: str) -> str:
        body = article(text)
        return text.replace(body, body.replace(f'href="{href}"', 'href="no-such-page/"', 1), 1)

    _edit(site, page, edit)


def _missing_anchor(site: Path) -> None:
    for page in pages(site):
        for href in _HREF.findall(article(read(site, page))):
            parts = urlsplit(html.unescape(href))
            if parts.fragment and not parts.scheme and not parts.netloc:
                target = page if not parts.path else posixpath.normpath(
                    posixpath.join(posixpath.dirname("/" + page), unquote(parts.path), "index.html")
                ).lstrip("/")
                if (site / target).is_file() and f'id="{parts.fragment}"' in read(site, target):
                    _edit(site, target, lambda t: t.replace(f'id="{parts.fragment}"', 'id="anchor-gone"', 1))
                    return
    raise RuntimeError("no fragment link found for the mutation")


def _changed_text(site: Path) -> None:
    _edit(site, "faq/index.html", lambda t: t.replace("</article>", "<p>unreviewed addition</p></article>", 1))


def _broken_navigation(site: Path) -> None:
    link = next(h for h, _ in _nav_raw(read(site, "index.html")) if h and not h.startswith(("#", "http")))
    _edit(site, "index.html", lambda t: t.replace(f'href="{link}"', 'href="nav-gone/"'))


def _nav_raw(text: str) -> list[tuple[str, str]]:
    parser = _PrimaryNav()
    parser.feed(text)
    return [(h, label) for h, label in parser.links]


def _changed_canonical(site: Path) -> None:
    _edit(site, "index.html", lambda t: _CANONICAL.sub('<link rel="canonical" href="https://example.invalid/"', t, count=1))


def _shrunk_sitemap(site: Path) -> None:
    _edit(site, "sitemap.xml", lambda t: re.sub(r"<url>.*?</url>", "", t, count=1, flags=re.S))


def _empty_search_index(site: Path) -> None:
    path = site / "search.json"
    data = json.loads(path.read_text("utf-8"))
    data["items"] = []
    path.write_text(json.dumps(data), "utf-8")


def _modern_stylesheet(site: Path) -> None:
    _edit(site, "index.html", lambda t: t.replace("assets/stylesheets/classic/", "assets/stylesheets/modern/"))


# name -> (mutation, text one reported problem must contain)
MUTATIONS: dict[str, tuple[Callable[[Path], None], str]] = {
    "missing page": (_drop_page, "page inventory differs"),
    "broken internal link": (_broken_link, "resolves to missing"),
    "missing content anchor": (_missing_anchor, "content anchors differ"),
    "changed article text": (_changed_text, "article text differs"),
    "broken navigation": (_broken_navigation, "navigation differs"),
    "changed canonical URL": (_changed_canonical, "canonical URL differs"),
    "shrunk sitemap": (_shrunk_sitemap, "sitemap URLs differ"),
    "empty search index": (_empty_search_index, "search.json has no entries"),
    "Modern instead of Classic stylesheet": (_modern_stylesheet, "Classic stylesheet"),
}


def self_test(site: Path, reference: Path) -> list[str]:
    """Each mutation, applied to an isolated copy of the site, must be detected."""
    failures: list[str] = []
    for name, (mutate, expected) in MUTATIONS.items():
        with tempfile.TemporaryDirectory(prefix="docs-site-mutation-") as tmp:
            copy = Path(tmp) / "site"
            shutil.copytree(site, copy)
            mutate(copy)
            problems = check(copy, reference)
        caught = any(expected in p for p in problems)
        print(f"  mutation {name!r}: {'detected' if caught else 'NOT DETECTED'}")
        if not caught:
            failures.append(f"mutation {name!r} was not detected (wanted a problem containing {expected!r})")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--write-inventory", action="store_true")
    parser.add_argument("--self-test", action="store_true", help="also prove the gate fails on broken copies of the site")
    args = parser.parse_args()
    if args.write_inventory:
        sys.stdout.write("\n".join(pages(args.site)) + "\n")
        return 0
    if args.reference is None:
        parser.error("--reference is required unless --write-inventory")
    errors = check(args.site, args.reference)
    for error in errors:
        print(f"FAIL {error}", file=sys.stderr)
    print(f"{len(pages(args.site))} pages checked, {len(errors)} problem(s)")
    if args.self_test:
        print("mutation self-test:")
        failures = self_test(args.site, args.reference)
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        errors += failures
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
