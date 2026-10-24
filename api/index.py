#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vercel Serverless Function — True Link Finder API (live resolve)
Endpoint: POST /api/resolve   body: {"url":"...", "max_depth":6, "delay":0.25}

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


def respond(data, code=200):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(data, ensure_ascii=False),
    }


def handler(event, context):
    start = time.time()
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return respond({"error": "JSON tidak valid"}, 400)

    url = (body.get("url") or "").strip()
    if not url:
        return respond({"error": "Parameter 'url' wajib diisi."}, 400)
    if not looks_like_url(url):
        return respond({"error": "URL tidak valid (harus http(s)://)."}, 400)

    max_depth = int(body.get("max_depth") or WEB_MAX_DEPTH)
    delay = float(body.get("delay") or WEB_DELAY)
    # jaga-jaga agar tetap dalam budget timeout
    if max_depth > 10:
        max_depth = 10
    if delay < 0:
        delay = 0

    try:
        cfg = Config.load(CONFIG)
    except Exception as e:
        return respond({"error": f"Gagal memuat config: {e}"}, 500)

    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    solver = Solver(cfg, fetcher, max_depth=max_depth, delay=delay, check=True)

    try:
        res = solver.resolve(url)
    except Exception as e:
        return respond({"error": f"Gagal resolve: {e}"}, 500)

    res["lama_detik"] = round(time.time() - start, 2)
    res["mode"] = "web"
    return respond(res, 200)
