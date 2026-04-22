#!/usr/bin/env python3
"""Transform the wget mirror at ../mirror/ into a clean, deployable site at ../site/.

This script is idempotent — running it twice produces the same output.

Transformations applied to each HTML page:
  - Path flatten: `../images.squarespace-cdn.com/` → `images.squarespace-cdn.com/`
    (mirror had pages under www.poliquicks.com/ so assets were up one level; in the
    deployed site, pages live alongside asset dirs at the root).
  - Slug rename: `curriculum-supplements-1.html` → `teacher-trainings.html`
    (the former is a Squarespace rename artifact; the nav item is "Teacher Trainings").
  - Remove cart link and cart DOM (site has no e-commerce).
  - Strip Squarespace runtime / analytics / CMS scripts.
  - Rewrite footer "ads.txt" link to `app-ads.txt` (the real file).
  - Replace newsletter form action with a Formspree placeholder (real ID wired in later).

auth-action.html is treated specially: the Firebase SDK imports and handler logic
must survive the JS strip.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIRROR = ROOT / "mirror"
SITE = ROOT / "site"
SRC_PAGES_DIR = MIRROR / "www.poliquicks.com"

# source filename -> output filename (relative to site/)
PAGE_MAP = {
    "index.html": "index.html",
    "about.html": "about.html",
    "curriculum-supplements-1.html": "teacher-trainings.html",
    "curriculum-supplements.html": "curriculum-supplements.html",
    "partners-and-sources.html": "partners-and-sources.html",
    "for-candidates-and-reps.html": "for-candidates-and-reps.html",
    "privacy-policy.html": "privacy-policy.html",
    "delete-account.html": "delete-account.html",
    "auth-action.html": "auth-action.html",
}

# asset directories copied verbatim from mirror to site
ASSET_DIRS = ["images.squarespace-cdn.com", "static1.squarespace.com"]

# <script src="..."> patterns to drop entirely (Squarespace runtime / analytics / CMS).
# Matched against the src attribute value.
SCRIPT_SRC_DROP_PATTERNS = [
    re.compile(r"squarespace\.com/universal/"),
    re.compile(r"static1\.squarespace\.com/static/vta/.*site-bundle"),
    re.compile(r"assets\.squarespace\.com/"),
    re.compile(r"google-analytics\.com/"),
    re.compile(r"googletagmanager\.com/"),
    re.compile(r"static1\.squarespace\.com/.*performance"),
]

# Inline <script> bodies to drop if they contain any of these substrings
INLINE_SCRIPT_DROP_SUBSTRINGS = [
    "Squarespace.Constants",
    "Static.SQUARESPACE_CONTEXT",
    "SquarespaceFonts",
    "window.Squarespace",
    "sqs-spa",
    "dataLayer",
]


def strip_scripts(html: str, keep_firebase: bool = False) -> str:
    """Remove Squarespace <script> tags while preserving non-Squarespace ones.

    If keep_firebase=True (auth-action page), preserve <script type="module">
    blocks that import from gstatic.com/firebasejs.
    """
    def repl(match: re.Match) -> str:
        tag = match.group(0)
        src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', tag)
        if src_match:
            src = src_match.group(1)
            if any(p.search(src) for p in SCRIPT_SRC_DROP_PATTERNS):
                return ""
            return tag  # external script we don't recognize — keep it
        # inline script
        if keep_firebase and "firebasejs" in tag:
            return tag
        if any(s in tag for s in INLINE_SCRIPT_DROP_SUBSTRINGS):
            return ""
        return tag

    return re.sub(r"<script\b[^>]*>.*?</script>", repl, html, flags=re.DOTALL)


_ASSET_HOST_RE = re.compile(
    r'(src|href)\s*=\s*(["\'])(?:https?:)?//(images\.squarespace-cdn\.com|static1\.squarespace\.com)/'
)


def _localize_asset_urls(html: str) -> str:
    """Strip the scheme+host from absolute CDN URLs in src/href so they resolve locally.

    wget's --convert-links missed many of these; the mirrored files ARE on disk under
    images.squarespace-cdn.com/ and static1.squarespace.com/, we just need the HTML
    to point at them as relative paths.
    """
    return _ASSET_HOST_RE.sub(r'\1=\2\3/', html)


def _encode_query_in_asset_refs(html: str) -> str:
    """URL-encode `?` in CDN asset refs.

    wget saved files with a literal `?` in the filename (e.g. `logo.png?format=1500w`).
    Browsers treat `?` in a URL as a query-string delimiter, so the server strips it
    and 404s. Encoding as `%3F` makes the browser request the literal filename.
    Only applied to src/href attrs on our CDN hosts — og:image meta tags keep absolute
    URLs for social previews.
    """
    pattern = re.compile(
        r'((?:src|href)\s*=\s*["\'](?:images\.squarespace-cdn\.com|static1\.squarespace\.com)/[^"\']*?)'
        r'\?'
        r'(format=[^"\']*)'
    )
    return pattern.sub(r'\1%3F\2', html)


def _encode_spaces_in_asset_refs(html: str) -> str:
    """Replace literal spaces in CDN asset URLs with %20.

    Some image filenames contain spaces (e.g. `Screenshot+2024-09-14+at+8.34.12 PM.png`)
    that the HTML source carries verbatim, breaking URL parsing. Must be handled with
    care for srcset, whose grammar uses a space to separate URL from width descriptor.
    """

    # Map of whitespace code points to their canonical percent-encodings. Squarespace
    # filenames sometimes contain U+202F (NARROW NO-BREAK SPACE, as used in macOS
    # timestamps like "8:34 PM"), which was not URL-encoded in every context.
    _WS_ENCODINGS = {
        " ": "%20",
        " ": "%E2%80%AF",
        " ": "%C2%A0",
    }

    def encode_url_spaces(url: str) -> str:
        for ch, repl in _WS_ENCODINGS.items():
            url = url.replace(ch, repl)
        return url

    # src / href: entire attribute value is the URL → encode all spaces.
    # Match includes the closing quote so we don't accidentally leave the
    # original quote intact after our replacement re-inserts one.
    def repl_single(m: re.Match) -> str:
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        return f'{attr}={quote}{encode_url_spaces(url)}{quote}'

    html = re.sub(
        r'(src|href)\s*=\s*(["\'])'
        r'((?:images\.squarespace-cdn\.com|static1\.squarespace\.com)/[^"\']*)'
        r'\2',
        repl_single, html,
    )

    # srcset: `url1 WwD, url2 WwD, ...` — use a smart split that recognizes the
    # descriptor by its `<digits>w` or `<digits>x` shape, so spaces inside URL
    # paths aren't mistakenly treated as URL/descriptor boundaries.
    descriptor_re = re.compile(r'\s+(\d+(?:\.\d+)?[wx])\s*$')

    def split_entry(entry: str) -> tuple[str, str]:
        m = descriptor_re.search(entry)
        if not m:
            return entry, ""
        return entry[: m.start()], m.group(1)

    def repl_srcset(m: re.Match) -> str:
        quote, body = m.group(1), m.group(2)
        parts = []
        for entry in body.split(","):
            entry = entry.strip()
            if not entry:
                continue
            url, descriptor = split_entry(entry)
            url = encode_url_spaces(url)
            parts.append(f"{url} {descriptor}".rstrip())
        return f'srcset={quote}{", ".join(parts)}{quote}'

    html = re.sub(
        r'srcset\s*=\s*(["\'])([^"\']+)\1',
        repl_srcset, html,
    )

    return html


def _promote_data_src(html: str) -> str:
    """Copy `data-src` attribute values into a `src` attribute.

    Squarespace lazy-loads images via a JS runtime that, on scroll, copies
    data-src → src. We stripped that runtime, so images never load. Promoting
    statically means they load on page render instead.

    Only promotes when no explicit `src=` already exists on the tag.
    """
    def promote(match: re.Match) -> str:
        tag = match.group(0)
        # `\b` matches between `-` and `s` inside `data-src=`, so `\bsrc=` would
        # false-positive. Use a negative lookbehind for any word char *or* hyphen.
        if re.search(r'(?<![\w-])src\s*=', tag):
            return tag
        data_src = re.search(r'\bdata-src\s*=\s*["\']([^"\']+)["\']', tag)
        if not data_src:
            return tag
        return tag.replace(
            data_src.group(0),
            f'{data_src.group(0)} src="{data_src.group(1)}"',
            1,
        )

    return re.sub(r'<img\b[^>]*>', promote, html)


def rewrite_paths(html: str) -> str:
    """Rewrite asset + internal-link paths for the flattened site/ layout."""
    # Flatten `../` prefix on asset refs (was needed in mirror, not in site)
    html = html.replace("../images.squarespace-cdn.com/", "images.squarespace-cdn.com/")
    html = html.replace("../static1.squarespace.com/", "static1.squarespace.com/")
    # Strip scheme+host on src/href attrs pointing at our CDN dirs (wget missed these)
    html = _localize_asset_urls(html)
    # Promote data-src -> src so lazy-loaded images display without the stripped JS runtime
    html = _promote_data_src(html)
    # Re-run localize pass to catch the src attributes we just added from data-src
    html = _localize_asset_urls(html)
    # Encode `?` in CDN asset filenames (files have literal `?` on disk)
    html = _encode_query_in_asset_refs(html)
    # Encode spaces in CDN asset refs
    html = _encode_spaces_in_asset_refs(html)

    # Dead internal link: references /curriculum-supplements/index.html#... still
    # appear from the Squarespace editor. Rewrite to the flat file.
    html = re.sub(
        r'(href\s*=\s*["\'])curriculum-supplements/index\.html',
        r'\1curriculum-supplements.html', html,
    )

    # Social-accounts SVG sprite is served from Squarespace's universal/ path.
    # On the live site it resolves via CDN rewrites; locally it lives under
    # static1.squarespace.com/universal/. Rewrite root-relative /universal/ refs.
    html = re.sub(
        r'(href\s*=\s*["\'])/universal/',
        r'\1static1.squarespace.com/universal/',
        html,
    )

    # Rename slug in every internal link — cover both the flat (.html) and
    # subdir (/index.html) forms that wget emits depending on how a page was linked.
    html = re.sub(r'(href\s*=\s*["\'])curriculum-supplements-1\.html',
                  r'\1teacher-trainings.html', html)
    html = re.sub(r'(href\s*=\s*["\'])curriculum-supplements-1/index\.html',
                  r'\1teacher-trainings.html', html)
    # Canonical / OG / Twitter meta URLs on the renamed page
    html = html.replace(
        "https://www.poliquicks.com/curriculum-supplements-1",
        "https://www.poliquicks.com/teacher-trainings",
    )

    # Repoint footer "ads.txt" to the real file
    html = html.replace('href="s/app-ads.txt"', 'href="app-ads.txt"')
    html = re.sub(r'href\s*=\s*["\']/?ads\.txt["\']', 'href="app-ads.txt"', html)

    return html


def strip_cart(html: str) -> str:
    """Remove the cart icon/link from the header. The live site has one but no products.

    Matches the anchor tag whose href is cart.html and wrapping sqs-cart elements.
    """
    # Remove the cart link anchor
    html = re.sub(
        r'<a[^>]*href\s*=\s*["\']cart\.html["\'][^>]*>.*?</a>',
        '', html, flags=re.DOTALL,
    )
    # Remove any element with class containing sqs-cart
    html = re.sub(
        r'<div[^>]*class\s*=\s*"[^"]*sqs-cart[^"]*"[^>]*>.*?</div>',
        '', html, flags=re.DOTALL,
    )
    return html


FORMSPREE_FORM_ID = "mvzdwjnb"  # https://formspree.io/f/mvzdwjnb
FORMSPREE_ACTION = f"https://formspree.io/f/{FORMSPREE_FORM_ID}"

# Static replacement for the empty Squarespace form-block shell on the homepage's
# "Get in touch" section. Fields mirror the original Squarespace config
# (name/email/message, all required, submit button "Send"). Success message
# handled inline via JS shim (see interactivity.js).
CONTACT_FORM_HTML = f'''
<form class="contact-form-shim" action="{FORMSPREE_ACTION}" method="POST">
  <input type="hidden" name="_subject" value="Poliquicks contact form message">
  <fieldset class="contact-form-shim__group">
    <legend class="contact-form-shim__legend">Name</legend>
    <div class="contact-form-shim__row">
      <label class="contact-form-shim__field">
        <span class="contact-form-shim__label">First Name <span class="contact-form-shim__req">(required)</span></span>
        <input type="text" name="firstName" required autocomplete="given-name">
      </label>
      <label class="contact-form-shim__field">
        <span class="contact-form-shim__label">Last Name <span class="contact-form-shim__req">(required)</span></span>
        <input type="text" name="lastName" required autocomplete="family-name">
      </label>
    </div>
  </fieldset>
  <label class="contact-form-shim__field">
    <span class="contact-form-shim__label">Email <span class="contact-form-shim__req">(required)</span></span>
    <input type="email" name="email" required autocomplete="email">
  </label>
  <label class="contact-form-shim__field">
    <span class="contact-form-shim__label">Message <span class="contact-form-shim__req">(required)</span></span>
    <textarea name="message" required></textarea>
  </label>
  <button type="submit" class="contact-form-shim__submit">Send</button>
  <div class="contact-form-shim__status" aria-live="polite"></div>
</form>
'''.strip()


def replace_form_action(html: str) -> str:
    """Rewire every Squarespace newsletter form to submit to Formspree.

    Squarespace renders the form with no `action` (submission is JS-driven
    via `onsubmit="Y.use('squarespace-form-submit', ...)"`). We strip that
    handler and inject an `action` + conventional form attributes so the
    browser's native form POST goes to Formspree.
    """
    def fix_form(match: re.Match) -> str:
        tag = match.group(0)
        # Drop the onsubmit handler (may span newlines)
        tag = re.sub(r'\sonsubmit\s*=\s*"[^"]*"', '', tag, flags=re.DOTALL)
        tag = re.sub(r"\sonsubmit\s*=\s*'[^']*'", '', tag, flags=re.DOTALL)
        # Inject action + hidden subject if not already present
        if 'action=' not in tag:
            tag = tag[:-1] + f' action="{FORMSPREE_ACTION}" >'
        return tag

    html = re.sub(
        r'<form\b[^>]*\bclass="[^"]*newsletter-form[^"]*"[^>]*>',
        fix_form, html, flags=re.DOTALL,
    )

    # Squarespace's <input> for email has lots of squarespace-specific attrs;
    # Formspree just needs name="email", which is already present. Add a hidden
    # subject so we can tell newsletter submits apart in Formspree's dashboard.
    if FORMSPREE_ACTION in html and '_subject" value="New Poliquicks' not in html:
        html = re.sub(
            r'(<div[^>]*class="newsletter-form-button-wrapper)',
            '<input type="hidden" name="_subject" value="New Poliquicks subscriber">'
            r'\1',
            html, count=0,
        )

    return html


FOOTER_HTML = f'''
<footer class="site-footer" id="footer-sections" data-footer-sections>
  <div class="site-footer__inner">
    <div class="site-footer__col">
      <h3>Contact Us</h3>
      <p><a href="tel:+15186490838">(518) 649-0838</a></p>
      <p><a href="mailto:poliquicksapp@gmail.com">poliquicksapp@gmail.com</a></p>
      <p>Based in Delaware.</p>
      <div class="site-footer__social">
        <a href="https://www.instagram.com/poliquicks/" target="_blank" rel="noopener" aria-label="Instagram">
          <svg viewBox="0 0 24 24"><use href="static1.squarespace.com/universal/svg/social-accounts.svg#instagram-unauth-icon"/></svg>
        </a>
        <a href="https://www.linkedin.com/company/poliquicks/" target="_blank" rel="noopener" aria-label="LinkedIn">
          <svg viewBox="0 0 24 24"><use href="static1.squarespace.com/universal/svg/social-accounts.svg#linkedin-unauth-icon"/></svg>
        </a>
      </div>
    </div>
    <div class="site-footer__col">
      <h3>Stay informed on staying informed</h3>
      <p>Sign up with your email address to receive news and updates.</p>
      <form class="site-footer__newsletter-form" action="{FORMSPREE_ACTION}" method="POST">
        <input type="hidden" name="_subject" value="New Poliquicks subscriber">
        <input type="email" name="email" required autocomplete="email" placeholder="Email Address">
        <button type="submit">Sign Up</button>
      </form>
      <p class="site-footer__privacy"><a href="privacy-policy.html">We respect your privacy.</a></p>
    </div>
  </div>
  <div class="site-footer__bottom">
    <span>&copy; 2026 Poliquicks Inc. All rights reserved.</span>
    <a href="app-ads.txt">ads.txt</a>
  </div>
</footer>
'''.strip()


def replace_footer(html: str) -> str:
    """Replace the entire Squarespace fluid-engine footer with a clean, hand-written one."""
    return re.sub(
        r'<footer\b[^>]*id="footer-sections"[^>]*>.*?</footer>',
        FOOTER_HTML,
        html, count=1, flags=re.DOTALL,
    )


def replace_contact_form_block(html: str) -> str:
    """Replace the empty Squarespace form-block (Get in touch) with a working
    HTML form wired to Formspree.

    Matches the <div class="sqs-block-form">...</div> wrapper whose only real
    content is a `form-context` JSON script Squarespace's runtime would have
    used to render the form. Since we stripped that runtime, the block shows
    nothing — we swap in our own static form."""
    return re.sub(
        r'<div\b[^>]*class="[^"]*sqs-block-form[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>',
        f'<div class="sqs-block form-block sqs-block-form">'
        f'<div class="sqs-block-content">{CONTACT_FORM_HTML}</div>'
        f'</div>',
        html, count=1, flags=re.DOTALL,
    )


INTERACTIVITY_SCRIPT_TAG = '<script src="assets/interactivity.js" defer></script>'
INTERACTIVITY_STYLE_TAG = '<link rel="stylesheet" href="assets/interactivity.css">'


def inject_interactivity(html: str) -> str:
    """Inject our vanilla-JS shim + CSS for hamburger, accordion, marquee, carousel."""
    if INTERACTIVITY_STYLE_TAG not in html and "</head>" in html:
        html = html.replace("</head>", f"  {INTERACTIVITY_STYLE_TAG}\n</head>", 1)
    if INTERACTIVITY_SCRIPT_TAG not in html:
        if "</body>" in html:
            html = html.replace("</body>", f"  {INTERACTIVITY_SCRIPT_TAG}\n</body>", 1)
        else:
            html = html + "\n" + INTERACTIVITY_SCRIPT_TAG + "\n"
    return html


def process(src: Path, dest: Path) -> None:
    html = src.read_text(encoding="utf-8")
    keep_firebase = src.name == "auth-action.html"
    html = rewrite_paths(html)
    html = strip_scripts(html, keep_firebase=keep_firebase)
    html = strip_cart(html)
    html = replace_form_action(html)
    html = replace_contact_form_block(html)
    html = replace_footer(html)
    html = inject_interactivity(html)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    print(f"  {src.relative_to(MIRROR)} -> {dest.relative_to(ROOT)} ({len(html):,} bytes)")


def copy_assets() -> None:
    for name in ASSET_DIRS:
        src = MIRROR / name
        dst = SITE / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        total = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
        print(f"  copied {name} -> site/{name} ({total/1e6:.1f} MB)")


def main() -> None:
    print("Copying asset directories...")
    copy_assets()
    print("\nTransforming HTML pages...")
    for src_name, dst_name in PAGE_MAP.items():
        process(SRC_PAGES_DIR / src_name, SITE / dst_name)
    print("\nDone.")


if __name__ == "__main__":
    main()
