#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vercel Serverless Function — True Link Finder API (mode hybrid)

Endpoint:
  POST /api/probe    {url}        → parse SATU halaman (cepat)
  POST /api/check    {url}        → cek kesehatan landing host (anti-zonk)
  POST /api/resolve  {url}        → solver penuh (untuk CLI/kompatibilitas)

Strategi hybrid (anti-timeout):
  Server hanya kerja per-halaman; BROWSER yang mengorkestrasi rantai.
  Jadi satu request tidak pernah menggantung lama.

Catatan penting: Vercel's Python runtime hanya mengenali WSGI callable
`app`/`application` (atau class BaseHTTPRequestHandler). `handler(event, context)`
gaya AWS Lambda TIDAK dikenali dan bikin build gagal.
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import parse_qs

# supaya bisa import modul utama di root proyek
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

WEB_MAX_DEPTH = 8
WEB_DELAY = 0.15
WEB_TIMEOUT = 6      # per-request; situs lambat jangan makan seluruh budget
WEB_DEADLINE = 45    # total; di bawah maxDuration 60 di vercel.json

HEADERS = [
    ("Content-Type", "application/json; charset=utf-8"),
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Headers", "Content-Type"),
    ("Access-Control-Allow-Methods", "POST, OPTIONS"),
]

STATUS = {
    200: "200 OK",
    400: "400 Bad Request",
    404: "404 Not Found",
    405: "405 Method Not Allowed",
    500: "500 Internal Server Error",
}


def respond(data, code=200):
    """Kompatibilitas bentuk lama (dipakai test/CLI lain bila ada)."""
    return {"statusCode": code, "headers": dict(HEADERS),
            "body": json.dumps(data, ensure_ascii=False)}


def _balas(start_response, data, code=200):
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    start_response(STATUS.get(code, f"{code} Error"), HEADERS)
    return [payload]


def load_cfg() -> Config:
    cfg = Config.load(CONFIG)
    # mode web: jangan pernah menggantung 20 detik per request
    cfg.data.setdefault("options", {})["timeout"] = WEB_TIMEOUT
    return cfg


def _ignored(cfg: Config, url: str) -> bool:
    low = url.lower()
    return any(kw in low for kw in cfg.markers("ignore_keywords"))


def probe_page(cfg: Config, url: str) -> dict:
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
        "direct": direct,
        "files": files,
        "next": nxt,
    }


def handle_probe(cfg: Config, body: dict):
    url = (body.get("url") or "").strip()
    if not url or not looks_like_url(url):
        return {"error": "parameter 'url' tidak valid"}, 400
    try:
        return probe_page(cfg, url), 200
    except Exception as e:  # noqa: BLE001
        return {"error": f"gagal probe: {e}"}, 500


def handle_check(cfg: Config, body: dict):
    url = (body.get("url") or "").strip()
    if not url or not looks_like_url(url):
        return {"error": "parameter 'url' tidak valid"}, 400
    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    checker = LandingHealthChecker(cfg, fetcher)
    try:
        status, detail = checker.check(url)
        return {"url": url, "status": status, "detail": detail}, 200
    except Exception as e:  # noqa: BLE001
        return {"error": f"gagal cek: {e}"}, 500


def _as_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off")
    return bool(value)


def handle_resolve(cfg: Config, body: dict):
    url = (body.get("url") or "").strip()
    if not url or not looks_like_url(url):
        return {"error": "parameter 'url' tidak valid"}, 400

    mulai = time.time()
    max_depth = min(int(body.get("max_depth") or WEB_MAX_DEPTH), 10)
    delay = max(float(body.get("delay") or WEB_DELAY), 0)
    check = _as_bool(body.get("check"), True)

    fetcher = StaticFetcher(cfg, delay=0, verbose=False)
    solver = Solver(cfg, fetcher, max_depth=max_depth, delay=delay,
                    check=check, deadline=WEB_DEADLINE)
    try:
        res = solver.resolve(url)
    except Exception as e:  # noqa: BLE001
        return {"error": f"gagal resolve: {e}"}, 500

    res["lama_detik"] = round(time.time() - mulai, 2)
    res["mode"] = "web-full"
    return res, 200


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

    try:
        body = json.loads(mentah.decode("utf-8") or "{}")
    except Exception:
        return _balas(start_response, {"error": "JSON tidak valid"}, 400)

    path = environ.get("PATH_INFO", "") or ""
    # sebagian deployment mengirim query di PATH_INFO
    if "?" in path:
        path = path.split("?", 1)[0]

    try:
        cfg = load_cfg()
    except Exception as e:  # noqa: BLE001
        return _balas(start_response, {"error": f"gagal memuat config: {e}"}, 500)

    if path.endswith("/probe"):
        data, code = handle_probe(cfg, body)
    elif path.endswith("/check"):
        data, code = handle_check(cfg, body)
    elif path.endswith("/resolve"):
        data, code = handle_resolve(cfg, body)
    else:
        data, code = {"error": "Endpoint tidak dikenal"}, 404

    return _balas(start_response, data, code)
