#!/usr/bin/env python3
"""Deterministic checks for a built documentation site.

Used by the experimental ``docs-zensical`` CI job to compare a Zensical build
against the Material for MkDocs build of the same sources, without depending
on generated asset hashes or incidental HTML formatting.

    python scripts/check_docs_site.py --site SITE --reference MATERIAL_SITE
    python scripts/check_docs_site.py --site SITE --write-inventory   # print pages

Checks: exact page inventory, internal link and anchor resolution, content
anchors, article text parity with the reference, and a non-empty search index.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tests" / "fixtures" / "docs_site_pages.txt"

_ARTICLE = re.compile(r"<article[^>]*>(.*?)</article>", re.S)
_ID = re.compile(r'\bid="([^"]+)"')
_HREF = re.compile(r'<a\b[^>]*?\bhref="([^"]*)"')
_TAG = re.compile(r"<[^>]+>")

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

    search = site / "search.json"
    try:
        data = json.loads(search.read_text("utf-8"))
        items = data.get("items") or data.get("docs")
        if not items:
            errors.append("search.json has no entries")
    except (OSError, ValueError) as exc:
        errors.append(f"search.json unreadable: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--write-inventory", action="store_true")
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
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
