#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
True Link Finder Helper
=======================
CLI deterministik untuk mengikuti rantai halaman download perantara
(contoh: neosatsu.com → linkuzu.blogspot.com/?i=... → host file akhir).

Aturan keras:
  * TANPA AI/LLM, TANPA API berbayar / key.
  * TANPA menyelesaikan / menembus CAPTCHA. Deteksi → berhenti + mode semi-manual.
  * TANPA login / kredensial.
  * Hanya resolve link, TIDAK auto-download file.

Usage:
  python3 true_link_finder.py <URL> [options]
"""

from __future__ import annotations

import argparse
import base64
import csv
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────
# Constanta
# ─────────────────────────────────────────────────────────────
VERSION = "1.0.0"

EXIT_OK = 0            # sukses: link akhir ditemukan
EXIT_URL_RESOLVED = 1  # tidak ada link akhir / rantai putus
EXIT_CAPTCHA = 2       # spaceindeteksi CAPTCHA / bot-detection
EXIT_NETWORK = 3       # error jaringan / HTTP
EXIT_USAGE = 4         # pemakaian salah (argumen, file, dll)

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_B64_TOKEN_RE = re.compile(r"[A-Za-z0-9+/_\-]{20,}={0,2}")
_JAVASCRIPT_RE = re.compile(
    r"""(?x)
    (?: location\.href|location\.replace|location\.assign|window\.open
        |top\.location|document\.location|self\.location
        |window\.location|setTimeout|setInterval )
    \s*(?:\(|\=)\s*["']([^"']+)["']
    """
)
_HTTPEQUIV_RE = re.compile(r"url\s*=\s*['\"]?([^;'\"]+)", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────
# Helpers kecil
# ─────────────────────────────────────────────────────────────
def log(msg: str, verbose: bool, level: str = "info") -> None:
    if level == "debug" and not verbose:
        return
    prefix = {"debug": "  ·", "info": "[*]", "ok": "[+]", "warn": "[!]", "err": "[x]"}.get(level, "[?]")
    print(f"{prefix} {msg}")


def host_of(url: str) -> str:
    """Kembalikan netloc (domain:port) tampa www. lowercase."""
    try:
        netloc = urllib.parse.urlparse(url).netloc
    except Exception:
        return ""
    netloc = netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def looks_like_url(s: str) -> bool:
    return bool(s) and bool(_URL_RE.match(s.strip()))


def strip_tracking(url: str) -> str:
    """Buang parameter pelacak yang umum agar link bersih & deterministik."""
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        keep = [(k, v) for k, v in query
                if k.lower() not in ("utm_source", "utm_medium", "utm_campaign",
                                     "utm_term", "utm_content", "fbclid", "ref",
                                     "source", "feature")]
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                        urllib.parse.urlencode(keep), parts.fragment))
    except Exception:
        return url


def b64_try(s: str) -> Optional[str]:
    """Coba decode base64 (standard & url-safe). Return string ter-decode atau None."""
    s = s.strip()
    if not s:
        return None
    # Buang padding yang hilang
    if len(s) % 4 != 0:
        s = s + "=" * (4 - len(s) % 4)
    for variant in (s.replace("+", "-").replace("/", "_"), s):
        try:
            raw = base64.b64decode(variant, validate=True)
        except Exception:
            continue
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def decode_layered(value: str) -> List[str]:
    """
    Decode berlapis: selang-seling URL-encode (percent) dan base64,
    berulang sampai ketemu string yang terlihat seperti URL.
    """
    out: List[str] = []
    cur = value.strip()
    if not cur:
        return out

    def _add(u: str):
        if u and looks_like_url(u) and u not in out:
            out.append(u)

    for _ in range(6):
        _add(cur)
        # layer: percent decode (hanya kalau menghasilkan perubahan)
        try:
            nxt = urllib.parse.unquote(cur)
        except Exception:
            break
        if nxt != cur:
            cur = nxt
            _add(cur)
            continue
        # layer: base64 decode
        d = b64_try(cur)
        if d and d != cur:
            cur = d
            _add(cur)
            continue
        break
    _add(cur)
    return out


# ─────────────────────────────────────────────────────────────
# Decoder obfuskasi host (pola site seperti neosatsu / linkuzu)
# ─────────────────────────────────────────────────────────────
# Pola yang ditemukan di halaman nyata: id = "<3 char>czo<3 char>v<base64 path>"
# Contoh: "Tj1czoTj1vL3d3dy5tZWRpYWZpcmUuY29tL2ZpbGUv..."
# Algoritma: ambil base64 SESUDAH "v" dari pola "czoXXXv", decode,
# lalu ambil prefiks yang terlihat seperti path URL (hentikan saat junk).
_OBS_ID_RE = re.compile(r"[A-Za-z0-9]{3}czo[A-Za-z0-9]{3}v[A-Za-z0-9+/=]+")
_URL_PATH_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:/?=&._~%-+#@!$'()*,;[]")

def decode_obfuscated_host_id(id_str: str) -> Optional[str]:
    """
    Kembalikan URL host dari id ter-obfuskasi (pola czo...), atau None.
    """
    m = re.search(r"czo.{3}v(.+)", id_str)
    if not m:
        return None
    c = m.group(1).split("=")[0]
    c += "=" * (-len(c) % 4)
    try:
        raw = base64.b64decode(c)
    except Exception:
        return None
    s = raw.decode("utf-8", "replace")
    out = []
    for ch in s:
        if ch in _URL_PATH_CHARS:
            out.append(ch)
        else:
            break
    path = "".join(out)
    if path.startswith("/"):
        return "https://" + path.lstrip("/")
    return None


def decode_gate_param(cfg: Config, url: str) -> Optional[str]:
    """
    Decode parameter gate ?i=<base64> dari URL menjadi URL host file (jika ada).
    Dipakai solver & API (hybrid) supaya konsisten.
    """
    try:
        qp = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(qp.query)
    except Exception:
        return None
    i = params.get("i") or params.get("i2")
    if not i:
        return None
    val = i[0].strip()
    for cand in decode_layered(val):
        if cfg.classify(host_of(cand)) == "file":
            return cand
    d = b64_try(val)
    if d:
        u = decode_obfuscated_host_id(d)
        if u and cfg.classify(host_of(u)) == "file":
            return u
    return None



# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
class Config:
    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(data)

    def _domains_for(self, kind: str) -> set:
        doms = set()
        for item in self.data.get("hosts", {}).get(kind, []) or []:
            for d in item.get("domains", []) or []:
                doms.add(str(d).lower().lstrip("www."))
        return doms

    @property
    def file_domains(self) -> set:
        return self._domains_for("file")

    @property
    def gate_domains(self) -> set:
        return self._domains_for("gate")

    def classify(self, domain: str) -> str:
        domain = domain.lower().lstrip("www.")
        if domain in self.file_domains:
            return "file"
        if domain in self.gate_domains:
            return "gate"
        # sebagian domain file punya subdomain / awalan; coba suffix match
        for d in self.file_domains:
            if domain.endswith("." + d):
                return "file"
        for d in self.gate_domains:
            if domain.endswith("." + d):
                return "gate"
        return "other"

    def option(self, key: str, default=None):
        return self.data.get("options", {}).get(key, default)

    def markers(self, key: str) -> List[str]:
        m = self.data.get("options", {}).get(key, []) or []
        return [str(x).lower() for x in m]


# ─────────────────────────────────────────────────────────────
# Fetch
# ─────────────────────────────────────────────────────────────
@dataclass
class Page:
    url: str              # URL yang diminta
    final_url: str        # URL setelah redirect
    html: str = ""
    status: int = 0
    effective_domain: str = ""


class StaticFetcher:
    """Fetcher statis murni (requests)."""

    def __init__(self, cfg: Config, delay: float = 0.0, verbose: bool = False):
        self.cfg = cfg
        self.delay = delay
        self.verbose = verbose
        self.session = requests.Session()
        ua = cfg.option("user_agent")
        self.session.headers.update({"User-Agent": ua,
                                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                     "Accept-Language": "en-US,en;q=0.5,id;q=0.3"})

    def fetch(self, url: str) -> Page:
        timeout = self.cfg.option("timeout", 20)
        log(f"GET {url}", self.verbose, "debug")
        try:
            r = self.session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException as e:
            raise NetworkError(f"Gagal menjangkau {url}: {e}")
        return Page(
            url=url,
            final_url=r.url,
            html=r.text or "",
            status=r.status_code,
            effective_domain=host_of(r.url),
        )


class NetworkError(Exception):
    pass


# ─────────────────────────────────────────────────────────────
# Parser / Ekstraktor (STATIS)
# ─────────────────────────────────────────────────────────────
def _clean_candidate(raw: str, base_url: str) -> Optional[str]:
    raw = raw.strip().strip('"\'').strip()
    if not raw:
        return None
    low = raw.lower()
    if low.startswith(("javascript:", "mailto:", "tel:", "data:", "about:", "file:")):
        return None
    if raw.startswith("#") or raw.startswith("//"):
        if raw.startswith("//"):
            raw = "https:" + raw
        else:
            return None
    # resolve relatif thd base
    if not looks_like_url(raw):
        try:
            raw = urllib.parse.urljoin(base_url, raw)
        except Exception:
            return None
    if not looks_like_url(raw):
        return None
    return strip_tracking(raw)


def split_candidates(text: str) -> List[str]:
    """Pisah teks yang mungkin berisi banyak URL."""
    found = []
    # cari semua URL lengkap (https://...) dalam teks
    for m in re.finditer(r"https?://[^\s'\"<>]+", text, re.IGNORECASE):
        s = m.group(0)
        s = re.sub(r"[)\]}>]+$", "", s)
        found.append(s)
    # kalau tidak ada, coba pecah spasi
    if not found:
        for tok in text.split():
            if looks_like_url(tok):
                found.append(tok)
    return found


def extract_candidates(html: str, base_url: str, cfg: Config) -> List[str]:
    """
    Ambil SEMUA kandidat URL dari HTML statis.
    Pengembalian: daftar URL (sudah dibersihkan+dedupe), urutan kemunculan.
    """
    cands: List[str] = []
    soup = BeautifulSoup(html, "html.parser")

    def consider(text: str):
        if not text:
            return
        for raw in split_candidates(text):
            u = _clean_candidate(raw, base_url)
            if u:
                cands.append(u)

    # <a href>
    for a in soup.find_all("a", href=True):
        consider(a.get("href"))
    # <iframe src>
    for i in soup.find_all("iframe", src=True):
        consider(i.get("src"))
    for i in soup.find_all("frame", src=True):
        consider(i.get("src"))
    # <meta http-equiv=refresh>
    for m in soup.find_all("meta"):
        if m.get("http-equiv", "").strip().lower() == "refresh":
            mm = _HTTPEQUIV_RE.search(m.get("content", ""))
            if mm:
                consider(mm.group(1))
    # <form action>
    for f in soup.find_all("form", action=True):
        consider(f.get("action"))
    # hidden input value yang terlihat seperti URL / base64
    for inp in soup.find_all("input", type="hidden"):
        consider(inp.get("value", ""))
    # atribut data-* di semua elemen
    for tag in soup.find_all(True):
        for k, v in tag.attrs.items():
            if k.startswith("data-"):
                consider(str(v))
    # <script>: location.href / window.open / setTimeout + base64
    for s in soup.find_all("script"):
        t = s.string or ""
        if t:
            for m in _JAVASCRIPT_RE.finditer(t):
                consider(m.group(1))
    # Cari string base64 di seluruh HTML yang ternyata URL setelah decode
    for tok in _B64_TOKEN_RE.findall(html):
        d = b64_try(tok)
        if d and looks_like_url(d):
            consider(d)
    # Pola id ter-obfuskasi (mis. neosatsu): "czo..." → decode ke URL host
    for tok in _OBS_ID_RE.findall(html):
        u = decode_obfuscated_host_id(tok)
        if u:
            consider(u)
    # string yang sudah langsung terlihat seperti URL di teks
    for t in soup.find_all(string=True):
        consider(t.strip())

    # dedupe (pertahankan urutan)
    seen = set()
    out = []
    for u in cands:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def detect_captcha(html: str, cfg: Config) -> Optional[str]:
    """Kembalikan jenis CAPTCHA yang terdeteksi, atau None."""
    low = html.lower()
    for marker in cfg.markers("captcha_markers"):
        if marker in low:
            return marker
    return None


# ─────────────────────────────────────────────────────────────
# Cek kesehatan link tujuan (anti-zonk)
# ─────────────────────────────────────────────────────────────
# Cek ini TIDAK mengunduh file. Ia hanya membuka halaman landing host,
# memeriksa status HTTP dan penanda "file not found / deleted / expired".
# URL: ("ok" | "bad" | "blocked" | "unknown", detail)
class LandingHealthChecker:
    def __init__(self, cfg: Config, fetcher):
        self.cfg = cfg
        self.fetcher = fetcher

    def check(self, url: str) -> Tuple[str, str]:
        try:
            page = self.fetcher.fetch(url)
        except NetworkError as e:
            return ("unknown", f"gagal fetch: {e}")
        st = page.status
        if st in (404, 410):
            return ("bad", f"HTTP {st} (halaman/file hilang)")
        if st == 403:
            return ("blocked", "HTTP 403 (kemungkinan bot-block)")
        if st >= 500:
            return ("unknown", f"HTTP {st}")
        body_low = page.html.lower()
        for marker in self.cfg.markers("health_bad_markers"):
            if marker in body_low:
                return ("bad", f"penanda '{marker}' di halaman landing")
        return ("ok", f"HTTP {st} tanpa penanda masalah")


# ─────────────────────────────────────────────────────────────
# Solver / pelacak rantai
# ─────────────────────────────────────────────────────────────
class Solver:
    def __init__(self, cfg: Config, fetcher, verbose: bool = False,
                 save_dir: Optional[str] = None, max_depth: Optional[int] = None,
                 delay: Optional[float] = None, check: bool = True,
                 deadline: Optional[float] = None):
        self.cfg = cfg
        self.fetcher = fetcher
        self.verbose = verbose
        self.save_dir = save_dir
        self.max_depth = max_depth if max_depth is not None else cfg.option("max_depth", 10)
        self.delay = delay if delay is not None else cfg.option("delay_seconds", 1.5)
        # cek kesehatan link tujuan (anti-zonk), bisa dimatikan dgn --no-check
        self.check = check
        self.checker = LandingHealthChecker(cfg, fetcher) if check else None
        # batas waktu total (detik). Dipakai mode web supaya tidak kena
        # hard-timeout serverless yang menghasilkan respons kosong.
        self.deadline = deadline

    def _score(self, url: str) -> int:
        cls = self.cfg.classify(host_of(url))
        if cls == "file":
            return 100
        if cls == "gate":
            return 50
        return 10

    def _is_ignored(self, url: str) -> bool:
        low = url.lower()
        for kw in self.cfg.markers("ignore_keywords"):
            if kw in low:
                return True
        return False

    def _decode_gate_param(self, url: str) -> Optional[str]:
        """
        Beberapa host gate (mis. linkuzu) menyematkan link tujuan di parameter
        query '?i=<base64>'. Decode DARI URL saja (tanpa fetch) supaya tidak
        nyasar ke rantai safelink/iklan, dan real deterministik.
        """
        return decode_gate_param(self.cfg, url)

    def resolve(self, start_url: str) -> Dict:
        """
        Ikuti rantai. Return dict:
          { url_awal, url_akhir, host, status, alasan, langkah: [url...] }
        status: 'ok' | 'no_link' | 'captcha' | 'zonk' | 'error'
        """
        visited = set()
        steps = []          # halaman yang dilewati (termasuk awal)
        current = start_url
        status = "no_link"
        reason = "Tidak ditemukan link lanjutan di akhir rantai."
        started = time.time()

        for depth in range(1, self.max_depth + 1):
            if self.deadline and (time.time() - started) > self.deadline:
                status = "timeout"
                reason = ("Batas waktu habis sebelum rantai selesai. "
                          "Coba lagi, kurangi kedalaman, atau pakai CLI lokal.")
                break

            log(f"Langkah {depth}: {current}", self.verbose, "info")

            # Pre-resolve: kalau URL gate punya parameter ?i= yang ter-decode
            # ke host file, langsung selesaikan tanpa fetch/iklan.
            direct = self._decode_gate_param(current)
            if direct:
                log(f"  → ter-decode dari parameter gate: {direct}", self.verbose, "info")
                return self._select_healthy_file(start_url, steps + [current], current, [direct])

            page = self.fetcher.fetch(current)
            cls = self.cfg.classify(page.effective_domain)

            # simpan HTML step
            if self.save_dir:
                os.makedirs(self.save_dir, exist_ok=True)
                fname = os.path.join(self.save_dir, f"step_{depth:02d}_{page.effective_domain or 'page'}.html")
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(page.html)
                log(f"Tersimpan: {fname}", self.verbose, "debug")

            # Jika sudah di host FILE → selesaikan (dengan cek kesehatan anti-zonk)
            if cls == "file":
                return self._select_healthy_file(start_url, steps + [current], current, [page.final_url])

            # Deteksi CAPTCHA / bot-detection — TIDAK pernah dilawan
            cap = detect_captcha(page.html, self.cfg)
            if cap:
                return {
                    "url_awal": start_url,
                    "url_akhir": None,
                    "host": page.effective_domain,
                    "status": "captcha",
                    "alasan": f"Terdeteksi indikator '{cap}'. Tool berhenti dan TIDAK menyelesaikan CAPTCHA.",
                    "pesan": ("Halaman ini minta verifikasi manusia. Buka manual di browser, "
                              "selesaikan, lalu tempel URL sesudahnya. Tool tidak menembus CAPTCHA."),
                    "langkah": steps + [current],
                }

            candidates = extract_candidates(page.html, page.final_url, self.cfg)
            # pilih kandidat terbaik
            best = None
            best_score = -1
            for u in candidates:
                if u in visited or u == page.final_url or u == current:
                    continue
                if self._is_ignored(u):
                    continue
                sc = self._score(u)
                if sc > best_score:
                    best_score = sc
                    best = u

            steps.append(page.final_url)
            visited.add(page.final_url)
            visited.add(current)

            if best is None:
                # Tidak ada link lanjutan
                if not candidates:
                    reason = f"Halaman {page.final_url} tidak mengandung link apa pun (mungkin JS-only/timer)."
                    log(reason, True, "warn")
                else:
                    reason = f"Tidak ada kandidat link yang dipilih dari {page.final_url}."
                    log(reason, True, "warn")
                status = "no_link"
                break

            # Kumpulkan semua kandidat host FILE (mirror) yang valid utk anti-zonk
            file_cands = []
            for u in candidates:
                if u in visited or u == page.final_url or u == current:
                    continue
                if self._is_ignored(u):
                    continue
                if self.cfg.classify(host_of(u)) == "file":
                    file_cands.append(u)

            if file_cands:
                return self._select_healthy_file(start_url, steps, current, file_cands)

            # lanjut ke gate berikutnya
            log(f"  → lanjut ke: {best} ({self.cfg.classify(host_of(best))})", self.verbose, "info")
            current = best
            time.sleep(self.delay)

        return {
            "url_awal": start_url,
            "url_akhir": None,
            "host": host_of(current),
            "status": status,
            "alasan": reason,
            "pesan": self._pesan_gagal(status, current),
            "langkah": steps,
        }

    @staticmethod
    def _pesan_gagal(status: str, current: str) -> str:
        if status == "timeout":
            return "Rantai belum selesai saat waktu habis. Coba lagi atau pakai CLI lokal."
        if status == "zonk":
            return "Link tujuan terindikasi mati. Tool tidak memaksakan link yang tidak sehat."
        if status == "captcha":
            return "Butuh interaksi manual di browser."
        return ("Tidak ada link lanjutan yang bisa diikuti dari "
                f"{host_of(current)}. Kemungkinan halaman butuh JavaScript/timer.")

    def _select_healthy_file(self, start_url: str, steps: list, current: str,
                             cands: List[str]) -> Dict:
        """
        Pilih mirror link tujuan yang SEHAT (anti-zonk). Iterasi semua kandida
        host file, cek kesehatan landing page-nya, ambil yang pertama tidak "bad".
        Jika semua bad → status 'zonk'.
        """
        bad = []
        for u in cands:
            log(f"  · mirror kandidat: {u}", self.verbose, "info")
            if not self.check:
                return self._ok_res(start_url, steps, current, u)
            time.sleep(self.delay)
            st, detail = self.checker.check(u)
            log(f"      → {st}: {detail}", self.verbose, "info")
            if st != "bad":
                return self._ok_res(start_url, steps, current, u)
            bad.append((u, detail))

        detail = "; ".join(f"{u} ({d})" for u, d in bad)
        reason = f"Semua mirror link tujuan terindikasi ZONK: {detail}"
        log(reason, True, "warn")
        return {
            "url_awal": start_url,
            "url_akhir": None,
            "host": self._host_name(host_of(current)),
            "status": "zonk",
            "alasan": reason,
            "pesan": ("Semua kandidat link tujuan terindikasi mati/dihapus. "
                      "Coba matikan cek kesehatan atau periksa manual."),
            "langkah": steps + [current],
        }

    def _ok_res(self, start_url: str, steps: list, current: str, final_url: str) -> Dict:
        sama = final_url.rstrip("/") == start_url.rstrip("/")
        return {
            "url_awal": start_url,
            "url_akhir": final_url,
            "host": self._host_name(host_of(final_url)),
            "status": "ok",
            "alasan": "",
            "sudah_akhir": sama,
            "pesan": ("URL yang kamu masukkan sudah berupa link host file. "
                      "Tidak ada rantai perantara yang perlu diurai.") if sama else "",
            "langkah": steps + [final_url],
        }

    def _host_name(self, domain: str) -> str:
        for kind in ("file", "gate"):
            for item in self.cfg.data.get("hosts", {}).get(kind, []) or []:
                if domain.lower() in [str(d).lower().lstrip("www.") for d in item.get("domains", [])]:
                    return item.get("name", domain)
        return domain


# ─────────────────────────────────────────────────────────────
# Backend browser (Fase 3, OPSIONAL) — hanya jika diminta & terpasang
# ─────────────────────────────────────────────────────────────
class BrowserFetcher:
    """Fetcher berbasis Playwright (opsional). Container ringan, lazy import."""

    def __init__(self, cfg: Config, headful: bool = False, verbose: bool = False):
        self.cfg = cfg
        self.headful = headful
        self.verbose = verbose
        self._playwright = None

    def _ensure(self):
        if self._playwright:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "Mode --browser memerlukan 'playwright'. Pasang dengan:\n"
                "  pip install playwright && playwright install chromium"
            ) from e
        self._playwright = sync_playwright().start()

    def fetch(self, url: str) -> Page:
        self._ensure()
        pw = self._playwright
        browser = pw.chromium.launch(headless=not self.headful)
        context = browser.new_context(user_agent=self.cfg.option("user_agent"))
        blocked = set(self.cfg.data.get("browser", {}).get("blocked_ad_domains", []))

        def route(request):
            h = request.url.lower()
            if any(d in h for d in blocked):
                request.abort()
            else:
                request.continue_()

        context.route("**/*", route)
        page = context.new_page()
        wait_after = self.cfg.data.get("browser", {}).get("wait_after_load", 10)

        # bongkar halaman
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # tunggu sebentar untuk timer/JS (maksimum wait_after detik)
        deadline = time.time() + wait_after
        while time.time() < deadline:
            html = page.content()
            if self._has_candidate(html):
                break
            time.sleep(1)

        final_html = page.content()
        final_url = page.url
        status_code = 200
        browser.close()
        return Page(url=url, final_url=final_url, html=final_html, status=status_code,
                    effective_domain=host_of(final_url))

    def _has_candidate(self, html: str) -> bool:
        return bool(extract_candidates(html, "", self.cfg))


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="true_link_finder",
        description="Ikuti rantai halaman download sampai ketemu link host file akhir.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", help="URL awal (atau gunakan --batch)")
    p.add_argument("--config", default=DEFAULT_CONFIG, help="Path config.yaml (default: pakai config.yaml di folder tool)")
    p.add_argument("-v", "--verbose", action="store_true", help="Mode verbosa: cetak tiap langkah + detail")
    p.add_argument("--save", metavar="DIR", default=None, help="Simpan HTML tiap langkah rantai ke DIR/step_N_<domain>.html")
    p.add_argument("--max-depth", type=int, default=None, help="Batas kedalaman rantai (default: dari config)")
    p.add_argument("--delay", type=float, default=None, help="Delay antar request, detik (default: dari config)")
    p.add_argument("--browser", action="store_true", help="Gunakan backend browser (Playwright) utk halaman JS/timer")
    p.add_argument("--headful", action="store_true", help="Mode --browser dengan jendela terlihat (utk CAPTCHA manual)")
    p.add_argument("--no-check", action="store_true", help="Nonaktifkan cek kesehatan link tujuan (anti-zonk). Default: cek ON")
    p.add_argument("--batch", metavar="FILE", default=None, help="File teks berisi banyak URL (satu per baris). Output ke results.csv")
    p.add_argument("--out", metavar="CSV", default="results.csv", help="File hasil batch (default: results.csv)")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p.parse_args(argv)


def print_chain(res: dict, verbose: bool) -> None:
    steps = res.get("langkah", [])
    print("\n" + "=" * 60)
    if res["status"] == "ok":
        print("  LINK AKHIR DITEMUKAN ✓")
    else:
        print(f"  STATUS: {res['status'].upper()}")
    print("=" * 60)
    for i, u in enumerate(steps, 1):
        print(f"  {i:2d}. {u}")
    if res["status"] == "ok":
        print("-" * 60)
        print(f"  HOST AKHIR : {res['host']}")
        print(f"  LINK AKHIR : {res['url_akhir']}")
        if res.get("pesan"):
            print(f"  CATATAN    : {res['pesan']}")
    else:
        print("-" * 60)
        print(f"  ALASAN     : {res['alasan']}")
        if res.get("pesan"):
            print(f"  SARAN      : {res['pesan']}")
        if res["status"] == "zonk":
            print("\n  Semua mirror terindikasi ZONK (mati/rusak). Coba:")
            print("    • jalankan ulang nanti (link host bisa pulih/hidup lagi),")
            print("    • atau cek lewat --browser kalau host butuh JS/klik.")
        if res["status"] == "captcha":
            print("\n  Mode semi-manual: selesaikan CAPTCHA di browser Anda, lalu")
            print("  jalankan ulang tool dengan URL *setelah* halaman itu (URL yang")
            print("  Anda dapatkan sesudah menyelesaikan verifikasi).")
    print("=" * 60 + "\n")


def run_single(args, cfg) -> int:
    if not args.url:
        print("Error: tidak ada URL diberikan. Coba: python3 true_link_finder.py <URL>")
        return EXIT_USAGE
    url = args.url.strip().strip('"\'')
    if not url:
        print("Error: tidak ada URL diberikan. Coba: python3 true_link_finder.py <URL>")
        return EXIT_USAGE
    if not looks_like_url(url):
        print(f"Error: '{url}' bukan URL yang valid (harus diawali http:// atau https://).")
        return EXIT_USAGE

    if args.browser:
        fetcher = BrowserFetcher(cfg, headful=args.headful, verbose=args.verbose)
    else:
        fetcher = StaticFetcher(cfg, delay=args.delay or 0, verbose=args.verbose)

    solver = Solver(cfg, fetcher, verbose=args.verbose, save_dir=args.save,
                    max_depth=args.max_depth, delay=args.delay,
                    check=not args.no_check)
    try:
        res = solver.resolve(url)
    except NetworkError as e:
        print(f"Error jaringan: {e}")
        return EXIT_NETWORK
    except RuntimeError as e:
        print(f"Error: {e}")
        return EXIT_USAGE

    print_chain(res, args.verbose)
    if res["status"] == "ok":
        return EXIT_OK
    if res["status"] == "captcha":
        return EXIT_CAPTCHA
    return EXIT_URL_RESOLVED


def run_batch(args, cfg) -> int:
    if not args.batch or not os.path.exists(args.batch):
        print(f"Error: file batch '{args.batch}' tidak ditemukan.")
        return EXIT_USAGE
    with open(args.batch, "r", encoding="utf-8") as f:
        urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        print("Error: file batch kosong.")
        return EXIT_USAGE

    print(f"Batch: {len(urls)} URL → {args.out}")
    rows = []
    for i, u in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] {u}")
        if not looks_like_url(u):
            rows.append([u, "", "", "error", "URL tidak valid"])
            continue
        fetcher = StaticFetcher(cfg, verbose=False)
        solver = Solver(cfg, fetcher, verbose=False, save_dir=args.save,
                        max_depth=args.max_depth, delay=args.delay,
                        check=not args.no_check)
        try:
            res = solver.resolve(u)
        except NetworkError as e:
            rows.append([u, "", "", "error", str(e)])
            continue
        rows.append([res["url_awal"], res["url_akhir"], res["host"],
                     res["status"], res["alasan"]])

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url_awal", "url_akhir", "host", "status", "alasan"])
        w.writerows(rows)

    print(f"\nSelesai. Hasil tersimpan di {args.out}")
    ok = sum(1 for r in rows if r[3] == "ok")
    print(f"Ringkasan: {ok}/{len(rows)} berhasil, {len(rows)-ok} gagal.")
    # Batch tetap dianggap sukses selama CSV berhasil ditulis: kegagalan per-URL
    # adalah DATA yang mau dilaporkan, bukan error tool. Kalau exit != 0,
    # workflow report ikut mati dan tidak pernah sempat deploy.
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        cfg = Config.load(args.config)
    except FileNotFoundError:
        print(f"Error: config '{args.config}' tidak ditemukan. Gunakan --config <path>.")
        return EXIT_USAGE
    except yaml.YAMLError as e:
        print(f"Error: config.yaml rusak: {e}")
        return EXIT_USAGE

    if args.batch:
        return run_batch(args, cfg)
    return run_single(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
