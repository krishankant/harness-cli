"""A local mini-web (week 8): a folder of pages, served over HTTP on 127.0.0.1 and searchable,
so the research agent's evals are offline and give the same results every run."""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from harnessy.tools.schema import tool
from harnessy.types import Tool


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


class LocalWeb:
    """Pages are *.md files whose first line is "# Title"; the slug is the file name without .md."""

    def __init__(self, folder: str | Path):
        self.pages: dict[str, tuple[str, str]] = {}
        for path in sorted(Path(folder).glob("*.md")):
            first, _, rest = path.read_text().partition("\n")
            self.pages[path.stem] = (first.lstrip("#").strip(), rest.strip())
        self._server: ThreadingHTTPServer | None = None

    # --- Given ---

    def start(self) -> LocalWeb:
        pages = self.pages

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                slug = self.path.split("?")[0].strip("/")
                if slug in pages:
                    title, text = pages[slug]
                    code, body = 200, f"# {title}\n\n{text}\n".encode()
                else:
                    code, body = 404, b"Not found"
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> LocalWeb:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    @property
    def host(self) -> str:
        assert self._server, "start() the web first"
        return f"127.0.0.1:{self._server.server_port}"

    def url(self, slug: str) -> str:
        return f"http://{self.host}/{slug}"

    def slug_for(self, url: str) -> str | None:
        parsed = urlparse(url)
        return parsed.path.strip("/") if parsed.netloc == self.host else None

    # --- Week 8 exercise ---

    def search(self, query: str, limit: int = 5) -> list[tuple[str, str, str]]:
        """Search the pages: [(url, title, snippet), ...], best first, at most limit.

        Words are _words(...) (lowercase [a-z0-9]+, at least 3 characters). A page's score is
        2 × (distinct query words in its title) + (distinct query words in its text). Keep pages
        scoring > 0; sort by score, highest first, then by slug. The snippet is the first
        sentence of the text (split on whitespace after . ! or ?) that contains a query word,
        cut to 200 characters.
        """
        words = _words(query)
        scored = []
        for slug, (title, text) in self.pages.items():
            score = 2 * len(words & _words(title)) + len(words & _words(text))
            if score > 0:
                scored.append((-score, slug))
        results = []
        for _, slug in sorted(scored)[:limit]:
            title, text = self.pages[slug]
            sentences = re.split(r"(?<=[.!?])\s+", text)
            snippet = next((s for s in sentences if words & _words(s)), sentences[0] if sentences else "")
            results.append((self.url(slug), title, snippet[:200]))
        return results


# --- Given -----------------------------------------------------------------------------


def web_tools(web: LocalWeb) -> list[Tool]:
    @tool(tags={"untrusted_input"})
    def web_search(query: str) -> str:
        """Search the web. Returns up to 5 results, each with a title, URL and snippet. Read a page with http_get before relying on it.

        Args:
            query: Keywords to search for.
        """
        results = web.search(query)
        if not results:
            return f"No results for '{query}'."
        return "\n".join(f"{i}. {title}\n   {url}\n   {snippet}" for i, (url, title, snippet) in enumerate(results, 1))

    return [web_search]
