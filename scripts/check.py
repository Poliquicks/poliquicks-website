#!/usr/bin/env python3
"""Smoke-test: fetch each HTML page from localhost and HEAD every src/href it references.

Reports any 404s or other non-success responses. Run while `python3 -m http.server 3000`
is serving site/.
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "docs"
BASE = "http://localhost:3000"

PAGES = sorted(p.name for p in SITE.glob("*.html"))

URL_RE = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']')
SRCSET_RE = re.compile(r'srcset\s*=\s*["\']([^"\']+)["\']')

# URL patterns to skip (third-party stuff we don't host)
SKIP = re.compile(
    r"^(?:mailto:|tel:|javascript:|#|data:)|"
    r"^https?://(?:fonts\.googleapis\.com|fonts\.gstatic\.com|definitions\.sqspcdn\.com|"
    r"apps\.apple\.com|play\.google\.com|www\.instagram\.com|www\.linkedin\.com|"
    r"creator-spring\.com|static\.squarespace\.com|assets\.squarespace\.com|"
    r"www\.gstatic\.com|poliquicks\.creator-spring\.com|www\.poliquicks\.com)"
)


def extract_urls(html: str) -> list[str]:
    urls: list[str] = []
    urls.extend(URL_RE.findall(html))
    for srcset in SRCSET_RE.findall(html):
        for part in srcset.split(","):
            part = part.strip().split()
            if part:
                urls.append(part[0])
    return urls


def check(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def main() -> int:
    failures: list[tuple[str, str, int]] = []
    counts: Counter = Counter()
    for page in PAGES:
        html = (SITE / page).read_text(encoding="utf-8")
        urls = extract_urls(html)
        seen: set[str] = set()
        for raw in urls:
            if SKIP.match(raw) or raw in seen or not raw:
                continue
            seen.add(raw)
            # build absolute url relative to BASE
            full = urllib.parse.urljoin(f"{BASE}/{page}", raw)
            # skip external absolute URLs (different host)
            parsed = urllib.parse.urlparse(full)
            if parsed.netloc != "localhost:3000":
                continue
            status = check(full)
            counts[status] += 1
            if status >= 400 or status == 0:
                failures.append((page, raw, status))
        print(f"  {page}: {sum(counts.values())} checked, {sum(v for k, v in counts.items() if k >= 400)} failing so far")

    print(f"\nStatus totals: {dict(counts)}")
    if failures:
        print(f"\n{len(failures)} broken refs:")
        for page, url, status in failures[:30]:
            print(f"  [{status}] {page} -> {url[:130]}")
        return 1
    print("\nAll refs OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
