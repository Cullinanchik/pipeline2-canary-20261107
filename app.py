"""Synthetic, read-only test server; no credentials or external data."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
from pathlib import Path
from urllib.parse import urlsplit
from api import list_items

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            body, content = b'{"ok": true}', "application/json"
        elif path == "/api/items":
            body, content = json.dumps(list_items()).encode(), "application/json"
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
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
