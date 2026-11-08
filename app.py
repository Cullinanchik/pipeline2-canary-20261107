"""Synthetic inventory test server; no credentials or external data."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from api import DEFAULT_DB_PATH, ApiError, Inventory, SchemaVersionError

MAX_BODY_BYTES = 4096
REQUEST_TIMEOUT_SECONDS = 10.0


class InventoryServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def make_server(host, port, db_path=DEFAULT_DB_PATH):
    inventory = Inventory(db_path)
    server = InventoryServer((host, port), Handler)
    server.inventory = inventory
    return server


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_content_length(values):
    if not values:
        raise ApiError(411, "length_required", "Content-Length header is required")
    if len(values) != 1:
        raise ApiError(400, "invalid_request", "duplicate Content-Length header")
    raw = values[0].strip()
    if not (raw.isascii() and raw.isdigit()):
        raise ApiError(400, "invalid_request", "Content-Length must be decimal digits")
    digits = raw.lstrip("0") or "0"
    if len(digits) > len(str(MAX_BODY_BYTES)) or int(digits) > MAX_BODY_BYTES:
        raise ApiError(413, "payload_too_large", f"request body must not exceed {MAX_BODY_BYTES} bytes")
    return int(digits)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(REQUEST_TIMEOUT_SECONDS)
        super().setup()

    def _send_json(self, status, payload, headers=()):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_api_error(self, err):
        self._send_json(err.status, {"error": err.code, "message": err.message}, err.headers)

    def _send_internal_error(self, exc):
        self.log_error("internal error: %r", exc)
        self._send_json(500, {"error": "internal_error", "message": "internal error"})

    def _read_json(self):
        try:
            length = parse_content_length(self.headers.get_all("Content-Length") or [])
        except ApiError:
            self.close_connection = True
            raise
        try:
            body = self.rfile.read(length)
        except OSError as exc:
            self.close_connection = True
            raise ApiError(400, "invalid_request", "request body was not received in full") from exc
        if len(body) != length:
            self.close_connection = True
            raise ApiError(400, "invalid_request", "request body is shorter than Content-Length")
        try:
            return json.loads(body.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise ApiError(400, "invalid_request", "body must be a UTF-8 JSON object") from exc

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/items":
                raise ApiError(405, "method_not_allowed", "use GET", (("Allow", "GET"),))
            if path != "/api/reservations":
                raise ApiError(404, "not_found", "route not found")
            status, reservation = self.server.inventory.reserve(self._read_json())
        except ApiError as err:
            self._send_api_error(err)
        except Exception as exc:
            self._send_internal_error(exc)
        else:
            self._send_json(status, reservation)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            body, content = b'{"ok": true}', "application/json"
        elif path == "/api/items":
            try:
                self._send_json(200, self.server.inventory.list_items())
            except ApiError as err:
                self._send_api_error(err)
            except Exception as exc:
                self._send_internal_error(exc)
            return
        elif path == "/api/reservations":
            self._send_api_error(ApiError(405, "method_not_allowed", "use POST", (("Allow", "POST"),)))
            return
        elif path == "/":
            labels = json.loads(Path(__file__).with_name("labels.json").read_text())
            body = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Synthetic canary</title>"
                    "<style>body{font:20px system-ui;max-width:720px;margin:60px auto;padding:20px}button{padding:12px}</style>"
                    "<h1>Inventory canary</h1><p>This is synthetic test data.</p><p>Status: " + html.escape(labels["badge"]) +
                    "</p><button type='button'>" + html.escape(labels["button"]) + "</button></html>").encode()
            content = "text/html; charset=utf-8"
        else:
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", content)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18390)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    try:
        server = make_server(args.host, args.port, args.db)
    except (SchemaVersionError, sqlite3.Error) as exc:
        raise SystemExit(f"inventory database error: {exc}")
    server.serve_forever()
