"""Shared local-HTTP-server test fixture used by Phase C's Playwright integration tests."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_server(html: bytes, extra_routes: dict[str, bytes] | None = None):
    routes = extra_routes or {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path, html)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def server_url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}"
