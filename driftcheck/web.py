"""Fetch a published MkDocs site and turn each page into Markdown, so the same checks run on web docs."""

from __future__ import annotations

import hashlib
import html
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

UA = "driftcheck/0.1 (docs consistency checker)"


class Fetcher:
    def __init__(self, cache_dir: Path, delay: float = 0.3) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
        self.status: dict[str, int] = {}

    def get(self, url: str) -> str | None:
        key = hashlib.sha1(url.encode()).hexdigest()[:16]
        f = self.cache_dir / f"{key}.html"
        if f.exists():
            self.status[url] = 200
            return f.read_text(encoding="utf-8")
        time.sleep(self.delay)
        try:
            r = self.client.get(url)
        except httpx.HTTPError:
            self.status[url] = 0
            return None
        self.status[url] = r.status_code
        if r.status_code != 200:
            return None
        f.write_text(r.text, encoding="utf-8")
        return r.text


def article_of(page_html: str) -> str:
    m = re.search(r"<article[^>]*>(.*?)</article>", page_html, re.S)
    return m.group(1) if m else page_html


def ids_of(page_html: str) -> set[str]:
    return set(re.findall(r'\sid="([^"]+)"', page_html))


def nav_links(page_html: str, base: str) -> list[str]:
    out = []
    for href in re.findall(r'<a[^>]+class="md-nav__link[^"]*"[^>]+href="([^"#]*)"', page_html) + re.findall(r'<a[^>]+href="([^"#]*)"[^>]+class="md-nav__link', page_html):
        u = urljoin(base, href)
        if urlparse(u).netloc == urlparse(base).netloc and u.startswith(base) and u not in out:
            out.append(u)
    return out


class _ToMd(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out: list[str] = []
        self.in_pre = 0
        self.in_code = 0
        self.pre_lang = ""
        self.pre_buf: list[str] = []
        self.href_stack: list[str | None] = []
        self.skip = 0
        self.div_langs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and ("headerlink" in cls or (a.get("id") or "").startswith("__codelineno")):
            self.skip += 1
            return
        if tag == "div":
            m = re.search(r"language-([\w+-]+)", cls)
            self.div_langs.append(m.group(1) if m else "")
        if self.in_pre:
            return
        if tag == "pre":
            self.in_pre = 1
            self.pre_lang = next((l for l in reversed(self.div_langs) if l), "")
            self.pre_buf = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "li", "tr", "br", "dt", "dd", "blockquote"):
            self.out.append("\n")
            if tag == "li":
                self.out.append("- ")
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag == "code":
            self.in_code += 1
            self.out.append("`")
        elif tag == "a":
            href = a.get("href")
            self.href_stack.append(urljoin(self.base, href) if href else None)
            self.out.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.skip:
            self.skip -= 1
            return
        if tag == "div" and self.div_langs:
            self.div_langs.pop()
        if tag == "pre" and self.in_pre:
            self.in_pre = 0
            code = html.unescape("".join(self.pre_buf)).strip("\n")
            lang = self.pre_lang or _guess_lang(code)
            self.out.append(f"\n\n```{lang}\n{code}\n```\n")
            return
        if self.in_pre:
            return
        if tag == "code" and self.in_code:
            self.in_code -= 1
            self.out.append("`")
        elif tag == "a" and self.href_stack:
            href = self.href_stack.pop()
            self.out.append(f"]({href})" if href else "]")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.in_pre:
            self.pre_buf.append(data)
        else:
            self.out.append(data if self.in_code else re.sub(r"\s+", " ", data))


def _guess_lang(code: str) -> str:
    if re.search(r"^\s*(from \w+ import|import \w+|def \w+\(|class \w+|@\w+)", code, re.M):
        return "python"
    if code.lstrip().startswith(("{", "[")):
        return "json"
    return "bash"


def page_to_markdown(page_html: str, url: str) -> str:
    p = _ToMd(url)
    p.feed(article_of(page_html))
    parts = re.split(r"(\n```[^\n]*\n.*?\n```\n)", "".join(p.out), flags=re.S)
    # tidy prose whitespace only; fenced code keeps its indentation
    text = "".join(part if part.startswith("\n```") else re.sub(r"\n[ \t]+", "\n", part) for part in parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def mirror_site(start_url: str, out_dir: Path, fetcher: Fetcher, limit: int = 200) -> dict[str, Path]:
    """Mirror every page reachable from the site navigation into out_dir as Markdown. Returns url -> file."""
    first = fetcher.get(start_url)
    if first is None:
        raise RuntimeError(f"cannot fetch {start_url}")
    urls = [start_url, *[u for u in nav_links(first, start_url) if u != start_url]][:limit]
    mapping: dict[str, Path] = {}
    for u in urls:
        page = fetcher.get(u)
        if page is None:
            continue
        rel = urlparse(u).path.strip("/").replace("/", "__") or "index"
        f = out_dir / f"{rel}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"<!-- source: {u} -->\n" + page_to_markdown(page, u), encoding="utf-8")
        mapping[u] = f
    return mapping


def check_web_link(target: str, fetcher: Fetcher, site_prefix: str) -> str | None:
    """Return a problem string for a broken same-site link or anchor, None if fine or external."""
    if not target.startswith(site_prefix):
        return None
    page_url, frag = urldefrag(target)
    page = fetcher.get(page_url)
    if page is None:
        return f"HTTP {fetcher.status.get(page_url)} for {page_url}"
    if frag and frag not in ids_of(page):
        return f"page {page_url} has no element with id #{frag}"
    return None
