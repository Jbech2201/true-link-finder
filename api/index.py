#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vercel Serverless Function — True Link Finder API (mode hybrid)

Endpoint:
  POST /api/probe    {url}        → parse SATU halaman (cepat, <10s)
  POST /api/check    {url}        → cek kesehatan landing host (anti-zonk)
  POST /api/resolve  {url}        → solver penuh (untuk CLI/kompatibilitas)

Strategi hybrid (anti-timeout):
  Server hanya kerja per-halaman; BROWSER yang mengorkestrasi rantai
  (delay/loop di sisi klien), jadi session server tak pernah lama.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from true_link_finder import (  # noqa: E402
    Config,
    Solver,
    StaticFetcher,
    LandingHealthChecker,
    decode_gate_param,
    detect_captcha,
    extract_candidates,
    host_of,
    looks_like_url,
)

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


def load_cfg():
    return Config.load(CONFIG)


def _ignored(cfg, url):
    low = url.lower()
    return any(kw in low for kw in cfg.markers("ignore_keywords"))


def probe_page(cfg, url):
    """Fetch satu halaman + ekstraksi statis. Cepat: satu request."""
    # Short-circuit: kalau URL gate ter-decode langsung ke host file,
    # jangan fetch halaman (hindari rantai safelink/iklan & hemat waktu).
    direct = decode_gate_param(cfg, url)
    if direct:
        return {
            "url": url,
            "final_url": url,
            "cls": "gate",
            "host": host_of(url),
            "captcha": None,
            "direct": direct,
            "files": [],
            "next": None,
        }

    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    page = fetcher.fetch(url)
    cls = cfg.classify(page.effective_domain)
    cap = detect_captcha(page.html, cfg)
    cands = extract_candidates(page.html, page.final_url, cfg)

    files, gates, others = [], [], []
    seen = set()
    for u in cands:
        if u in seen or _ignored(cfg, u):
            continue
        seen.add(u)
        k = cfg.classify(host_of(u))
        if k == "file":
            files.append(u)
        elif k == "gate":
            gates.append(u)
        else:
            others.append(u)

    nxt = next(iter(gates + others), None)  # gate dulu, baru lain
    return {
        "url": url,
        "final_url": page.final_url,
        "cls": cls,
        "host": page.effective_domain,
        "captcha": cap,
        "direct": decode_gate_param(cfg, url),
        "files": files,
        "next": nxt,
    }


def handle_probe(cfg, body):
    url = (body.get("url") or "").strip()
    if not url or not looks_like_url(url):
        return respond({"error": "parameter 'url' tidak valid"}, 400)
    try:
        return respond(probe_page(cfg, url), 200)
    except Exception as e:  # noqa: BLE001
        return respond({"error": f"gagal probe: {e}"}, 500)


def handle_check(cfg, body):
    url = (body.get("url") or "").strip()
    if not url or not looks_like_url(url):
        return respond({"error": "parameter 'url' tidak valid"}, 400)
    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    checker = LandingHealthChecker(cfg, fetcher)
    try:
        status, detail = checker.check(url)
        return respond({"url": url, "status": status, "detail": detail}, 200)
    except Exception as e:  # noqa: BLE001
        return respond({"error": f"gagal cek: {e}"}, 500)


def handle_resolve(cfg, body):
    url = (body.get("url") or "").strip()
    if not url or not looks_like_url(url):
        return respond({"error": "parameter 'url' tidak valid"}, 400)
    max_depth = min(int(body.get("max_depth") or WEB_MAX_DEPTH), 10)
    delay = max(float(body.get("delay") or WEB_DELAY), 0)
    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    solver = Solver(cfg, fetcher, max_depth=max_depth, delay=delay, check=True)
    try:
        res = solver.resolve(url)
        res["lama_detik"] = round(time.time(), 2)
        res["mode"] = "web-full"
        return respond(res, 200)
    except Exception as e:  # noqa: BLE001
        return respond({"error": f"gagal resolve: {e}"}, 500)


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return respond({"error": "JSON tidak valid"}, 400)

    path = (event.get("path") or "").split("?")[0]
    try:
        cfg = load_cfg()
    except Exception as e:
        return respond({"error": f"gagal memuat config: {e}"}, 500)

    if path == "/api/probe":
        return handle_probe(cfg, body)
    if path == "/api/check":
        return handle_check(cfg, body)
    if path == "/api/resolve":
        return handle_resolve(cfg, body)
    return respond({"error": "Endpoint tidak dikenal"}, 404)
