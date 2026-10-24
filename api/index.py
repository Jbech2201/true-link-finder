#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vercel Serverless Function — True Link Finder API (live resolve)
Endpoint: POST /api/resolve   body: {"url":"...", "max_depth":6, "delay":0.25}

Vercel's Python runtime looks for a WSGI callable named `app` (or `application`),
not an AWS-Lambda-style `handler(event, context)`. Ini WSGI murni tanpa Flask.

Keterbatasan mode web (gratis):
  - Timeout serverless ~10s → depth dibatasi & delay dikecilkan.
  - Sebagian situs memblokir IP datacenter → bisa gagal meski jalan lokal.
  - CAPTCHA TIDAK diselesaikan (aturan keras).
"""

import json
import os
import sys
import time

# supaya bisa import modul utama di root proyek
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from true_link_finder import Config, Solver, StaticFetcher, looks_like_url  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.yaml")

WEB_MAX_DEPTH = 6
WEB_DELAY = 0.25

HEADERS = [
    ("Content-Type", "application/json; charset=utf-8"),
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Headers", "Content-Type"),
    ("Access-Control-Allow-Methods", "POST, OPTIONS"),
]

STATUS = {
    200: "200 OK",
    400: "400 Bad Request",
    405: "405 Method Not Allowed",
    500: "500 Internal Server Error",
}


def _balas(start_response, data, code=200):
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    start_response(STATUS.get(code, f"{code} Error"), HEADERS)
    return [payload]


def app(environ, start_response):
    """WSGI entry point yang dikenali Vercel."""
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if method == "OPTIONS":
        start_response("204 No Content", HEADERS)
        return [b""]
    if method != "POST":
        return _balas(start_response, {"error": "Gunakan POST."}, 405)

    try:
        panjang = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        panjang = 0
    mentah = environ["wsgi.input"].read(panjang) if panjang else b""

    start = time.time()
    try:
        body = json.loads(mentah.decode("utf-8") or "{}")
    except Exception:
        return _balas(start_response, {"error": "JSON tidak valid"}, 400)

    url = (body.get("url") or "").strip()
    if not url:
        return _balas(start_response, {"error": "Parameter 'url' wajib diisi."}, 400)
    if not looks_like_url(url):
        return _balas(start_response, {"error": "URL tidak valid (harus http(s)://)."}, 400)

    max_depth = int(body.get("max_depth") or WEB_MAX_DEPTH)
    delay = float(body.get("delay") or WEB_DELAY)
    # jaga-jaga agar tetap dalam budget timeout
    max_depth = min(max_depth, 10)
    delay = max(delay, 0)

    try:
        cfg = Config.load(CONFIG)
    except Exception as e:
        return _balas(start_response, {"error": f"Gagal memuat config: {e}"}, 500)

    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    solver = Solver(cfg, fetcher, max_depth=max_depth, delay=delay, check=True)

    try:
        hasil = solver.resolve(url)
    except Exception as e:
        return _balas(start_response, {"error": f"Gagal resolve: {e}"}, 500)

    hasil["lama_detik"] = round(time.time() - start, 2)
    hasil["mode"] = "web"
    return _balas(start_response, hasil, 200)
