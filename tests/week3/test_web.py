import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from harnessy.tools.web import http_get


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code, body = {"/": (200, b"hello"), "/big": (200, b"z" * 1000)}.get(self.path, (404, b"nope"))
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def test_ok(server):
    assert http_get.fn(server + "/") == "HTTP 200\n\nhello"


def test_error_status_is_returned_as_text(server):
    assert http_get.fn(server + "/missing") == "HTTP 404\n\nnope"


def test_byte_cap(server):
    out = http_get.fn(server + "/big", max_bytes=100)
    assert out == "HTTP 200\n\n" + "z" * 100 + "\n[cut off at 100 bytes]"


def test_only_http_and_https():
    with pytest.raises(ValueError, match="http"):
        http_get.fn("file:///etc/passwd")


def test_http_get_is_a_tool():
    assert http_get.name == "http_get" and http_get.spec.parameters["required"] == ["url"]
