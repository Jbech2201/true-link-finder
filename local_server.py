#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local server murni Python (stdlib) untuk True Link Finder.
- Sajikan frontend dari folder public/
- Endpoint POST /api/resolve  → jalankan solver yang SAMA dgn CLI/API

Pakai:
  python3 local_server.py --port 8080
Lalu buka: http://localhost:8080
"""

import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# pastikan bisa import modul utama di root
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from true_link_finder import Config, Solver, StaticFetcher, looks_like_url  # noqa: E402

CONFIG = os.path.join(ROOT, "config.yaml")
PUBLIC = os.path.join(ROOT, "public")

LOCAL_MAX_DEPTH = 8
LOCAL_DELAY = 1.5


def resolve_one(url: str) -> dict:
    cfg = Config.load(CONFIG)
    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    solver = Solver(cfg, fetcher, max_depth=LOCAL_MAX_DEPTH,
                    delay=LOCAL_DELAY, check=True)
    return solver.resolve(url)


class Handler(BaseHTTPRequestHandler):
    server_version = "TrueLinkFinderLocal/1.0"

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(PUBLIC, rel))
        # anti path traversal
        if not full.startswith(os.path.abspath(PUBLIC)) or not os.path.isfile(full):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/resolve":
            self._json({"error": "Endpoint tidak dikenal"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._json({"error": "JSON tidak valid"}, 400)
            return

        url = (body.get("url") or "").strip()
        if not url:
            self._json({"error": "Parameter 'url' wajib diisi."}, 400)
            return
        if not looks_like_url(url):
            self._json({"error": "URL tidak valid (harus http(s)://)."}, 400)
            return

        try:
            res = resolve_one(url)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"Gagal resolve: {e}"}, 500)
            return
        self._json(res, 200)

    def log_message(self, fmt, *args):
        sys.stderr.write("[local] %s\n" % (fmt % args))


def main():
    ap = argparse.ArgumentParser(description="Local server True Link Finder")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"True Link Finder local server aktif: http://{args.host}:{args.port}")
    print("Tekan Ctrl+C untuk berhenti.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")
        httpd.server_close()


if __name__ == "__main__":
    main()
