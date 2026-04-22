#!/usr/bin/env python3
"""Find every Squarespace-CDN asset referenced in the mirrored HTML and download
any that aren't already in site/ locally.

wget only downloads page requisites it recognizes (src, href, link rel, ...). It
misses `data-src` (Squarespace lazy-loaded images) and root-relative URLs like
`/universal/svg/social-accounts.svg`. This script fills those gaps.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIRROR = ROOT / "mirror"
MIRROR_HTML = MIRROR / "www.poliquicks.com"

# Attributes whose values may contain CDN URLs we care about
ATTR_RE = re.compile(
    r'(?:src|href|data-src|data-image|data-content-image-url|poster)'
    r'\s*=\s*["\']([^"\']+)["\']'
)
SRCSET_RE = re.compile(r'srcset\s*=\s*["\']([^"\']+)["\']')

ASSET_HOSTS = ("images.squarespace-cdn.com", "static1.squarespace.com")
UNIVERSAL_PREFIX = "/universal/"

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def extract_cdn_urls(html: str) -> set[str]:
    urls: set[str] = set()
    for m in ATTR_RE.finditer(html):
        urls.add(m.group(1))
    for m in SRCSET_RE.finditer(html):
        for part in m.group(1).split(","):
            part = part.strip().split()
            if part:
                urls.add(part[0])
    # Strip URL fragments — for SVG sprites, `foo.svg#icon-1` and `foo.svg#icon-2`
    # are both served by the single file `foo.svg`.
    urls = {u.split("#", 1)[0] for u in urls}
    # Keep only CDN-hosted or /universal/ URLs
    filtered: set[str] = set()
    for u in urls:
        if any(h in u for h in ASSET_HOSTS):
            filtered.add(u)
        elif u.startswith(UNIVERSAL_PREFIX):
            filtered.add(u)
    return filtered


def local_path_for(url: str) -> Path | None:
    """Return the local mirror/ path where this URL's bytes should live.

    Matches the layout wget creates: host/path[?query → literal ?query in filename].
    Files live in mirror/ so `build.py` picks them up when it copies assets to site/.
    """
    if url.startswith(UNIVERSAL_PREFIX):
        # /universal/... lives under static1.squarespace.com/universal/...
        return MIRROR / "static1.squarespace.com" / url.lstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in ASSET_HOSTS:
        return None
    # Reconstruct filename including query (wget does this)
    path = parsed.path.lstrip("/")
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return MIRROR / parsed.netloc / path


def to_absolute(url: str) -> str:
    if url.startswith(UNIVERSAL_PREFIX):
        return "https://static1.squarespace.com" + url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    # Host without scheme (images.squarespace-cdn.com/...)
    if any(url.startswith(h) for h in ASSET_HOSTS):
        return "https://" + url
    return url


def download(url: str, dest: Path) -> bool:
    """Download url to dest. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    abs_url = to_absolute(url)
    req = urllib.request.Request(abs_url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            dest.write_bytes(data)
            return True
    except Exception as e:
        print(f"    FAIL {abs_url}: {e}")
        return False


def main() -> None:
    all_urls: set[str] = set()
    for html_file in MIRROR_HTML.glob("*.html"):
        html = html_file.read_text(encoding="utf-8")
        all_urls |= extract_cdn_urls(html)

    print(f"Found {len(all_urls)} unique CDN URLs across mirrored HTML.")

    missing = []
    present = 0
    for url in sorted(all_urls):
        dest = local_path_for(url)
        if dest is None:
            continue
        if dest.exists():
            present += 1
        else:
            missing.append((url, dest))

    print(f"{present} already on disk, {len(missing)} missing.")

    ok = 0
    fail = 0
    for url, dest in missing:
        if download(url, dest):
            ok += 1
            print(f"  ok  {url[:110]}")
        else:
            fail += 1

    print(f"\nDownloaded {ok}, failed {fail}.")


if __name__ == "__main__":
    main()
