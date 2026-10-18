"""Best-effort ``og:image`` lookup for items the agent added without images (stdlib only)."""
from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin

_UA = "Mozilla/5.0 (compatible; HermesFeed/0.1; +https://github.com/NousResearch/hermes-agent)"
_MAX_BYTES = 256 * 1024
_IMAGE_PROPS = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src")


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if self.found or tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").lower()
        if key in _IMAGE_PROPS and a.get("content"):
            self.found = a["content"].strip()


def og_image(url: str, timeout: float = 5.0) -> Optional[str]:
    """Return the page's social preview image as an absolute https URL, or ``None``."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if "html" not in resp.headers.get("Content-Type", ""):
                return None
            raw = resp.read(_MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
        head = raw.decode(charset, errors="replace")
        head = head[: m.start()] if (m := re.search(r"</head\s*>", head, re.I)) else head
        parser = _MetaParser()
        parser.feed(head)
        if not parser.found:
            return None
        image = urljoin(url, parser.found)
        return image if image.startswith("https://") else None
    except Exception:
        return None
