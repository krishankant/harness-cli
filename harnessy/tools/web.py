"""http_get: fetch a web page as text (week 3). Given in full."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from harnessy.tools.schema import tool


# Tagged as untrusted input AND as a way out (week 7): a URL can carry data away.
@tool(timeout_s=15, tags={"untrusted_input", "external_send"})
def http_get(url: str, max_bytes: int = 200_000) -> str:
    """Fetch a URL with HTTP GET and return the status code and the body as text.

    Args:
        url: An http:// or https:// URL.
        max_bytes: Stop reading after this many bytes.
    """
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"only http and https URLs are allowed, got {url!r}")
    request = urllib.request.Request(url, headers={"User-Agent": "harnessy/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            status, body = resp.status, resp.read(max_bytes + 1)
    except urllib.error.HTTPError as e:  # 4xx/5xx: the model should see it, not crash
        status, body = e.code, e.read(max_bytes + 1)
    text = body[:max_bytes].decode("utf-8", errors="replace")
    note = f"\n[cut off at {max_bytes:,} bytes]" if len(body) > max_bytes else ""
    return f"HTTP {status}\n\n{text}{note}"
