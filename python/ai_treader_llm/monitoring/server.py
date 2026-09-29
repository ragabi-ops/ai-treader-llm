"""Serve the read-only AI-Treader LLM operations dashboard."""
from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ai_treader_llm.monitoring.collector import Collector

LOGGER = logging.getLogger("ai_treader_llm.dashboard")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, collector: Collector, static_dir: Path):
        super().__init__(address, handler)
        self.collector = collector
        self.static_dir = static_dir.resolve()


class Handler(BaseHTTPRequestHandler):
    server: DashboardServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        LOGGER.info("%s %s", self.client_address[0], fmt % args)

    def _headers(self, content_type: str, length: int, cache: str = "no-store") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - standard library callback name
        path = urlsplit(self.path).path
        if path == "/health":
            self._json({"status": "ok"})
            return
        if path == "/api/v1/status":
            try:
                self._json(self.server.collector.snapshot())
            except Exception:  # keep request failure bounded; details stay in service logs
                LOGGER.exception("telemetry collection failed")
                self._json(
                    {"schema_version": "1", "status": "unavailable", "reason": "collection_failed"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            target = self.server.static_dir / filename
            try:
                body = target.read_bytes()
            except OSError:
                self._json({"error": "asset_unavailable"}, HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            cache = "no-cache" if filename == "index.html" else "public, max-age=300"
            self._headers(content_type, len(body), cache)
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-root", type=Path, default=Path("/data"))
    parser.add_argument("--inference-url", default="http://127.0.0.1:8080")
    parser.add_argument("--container", default="ai-treader-llm-inference-1")
    parser.add_argument("--static-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    root = args.root.resolve()
    static_dir = (args.static_dir or root / "dashboard").resolve()
    for name, _ in STATIC_FILES.values():
        if not (static_dir / name).is_file():
            parser.error(f"missing dashboard asset: {name}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    collector = Collector(
        root=root,
        data_root=args.data_root,
        inference_url=args.inference_url,
        container_name=args.container,
    )
    server = DashboardServer((args.host, args.port), Handler, collector, static_dir)
    LOGGER.info("dashboard listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
