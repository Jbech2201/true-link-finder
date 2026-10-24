#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit test OFFLINE untuk True Link Finder.
Tidak menyentuh jaringan sama sekali: hanya memakai fixture HTML simpanan
dan fetcher palsu yang mengembalikan HTML dari file fixture.
"""

import os
import sys
import unittest

# pastikan modul utama bisa diimpor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from true_link_finder import (  # noqa: E402
    Config,
    Solver,
    StaticFetcher,
    Page,
    NetworkError,
    b64_try,
    decode_layered,
    decode_obfuscated_host_id,
    detect_captcha,
    extract_candidates,
    host_of,
    looks_like_url,
    split_candidates,
    strip_tracking,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


def read_fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


class FakeFetcher:
    """Fetcher palsu yang memetakan URL -> HTML fixture.
    Nilai mapping boleh berupa string (HTML, status 200) atau tuple (HTML, status).
    """

    def __init__(self, mapping):
        self.mapping = mapping
        self.requests = []

    def fetch(self, url):
        self.requests.append(url)
        if url not in self.mapping:
            raise NetworkError(f"no fixture for {url}")
        val = self.mapping[url]
        if isinstance(val, tuple):
            html, status = val
        else:
            html, status = val, 200
        return Page(url=url, final_url=url, html=html, status=status,
                    effective_domain=host_of(url))


class TestHelpers(unittest.TestCase):
    def test_host_of(self):
        self.assertEqual(host_of("https://www.MediaFire.com/x"), "mediafire.com")
        self.assertEqual(host_of("https://linkuzu.blogspot.com/?i=1"), "linkuzu.blogspot.com")

    def test_looks_like_url(self):
        self.assertTrue(looks_like_url("https://a.b/c"))
        self.assertFalse(looks_like_url("not a url"))
        self.assertFalse(looks_like_url(""))

    def test_strip_tracking(self):
        self.assertEqual(
            strip_tracking("https://x.com/dl?file=1&utm_source=tw"),
            "https://x.com/dl?file=1")

    def test_b64_try(self):
        self.assertEqual(b64_try("aHR0cHM6Ly9tZWRpYWZpcmUuY29tLz9kMDkxMjM0NTY3ODk="),
                         "https://mediafire.com/?d09123456789")

    def test_decode_layered(self):
        # base64 berlapis → decode url
        enc = "aHR0cHM6Ly9tZWRpYWZpcmUuY29tLz9kMDkxMjM0NTY3ODk="
        out = decode_layered(enc)
        self.assertIn("https://mediafire.com/?d09123456789", out)

    def test_split_candidates(self):
        self.assertIn("https://a.com/x", split_candidates('lihat https://a.com/x dan https://b.com/y'))

    def test_decode_obfuscated_host_id(self):
        self.assertEqual(
            decode_obfuscated_host_id("nX1czonX1vL2dvZmlsZS5pby9kLzdLU0JobnJwljI"),
            "https://gofile.io/d/7KSBhnrp")
        self.assertEqual(
            decode_obfuscated_host_id("Tj1czoTj1vL3d3dy5tZWRpYWZpcmUuY29tL2ZpbGUvcmp6amdxZGNnb2xxN3pl1XZ"),
            "https://www.mediafire.com/file/rjzjgqdcgolq7ze")
        self.assertIsNone(decode_obfuscated_host_id("tidak-czo-valid"))


class TestClassify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.load(CONFIG)

    def test_file_hosts(self):
        self.assertEqual(self.cfg.classify("drive.google.com"), "file")
        self.assertEqual(self.cfg.classify("mega.nz"), "file")
        self.assertEqual(self.cfg.classify("mediafire.com"), "file")
        self.assertEqual(self.cfg.classify("pixeldrain.com"), "file")

    def test_gate_hosts(self):
        self.assertEqual(self.cfg.classify("linkuzu.blogspot.com"), "gate")
        self.assertEqual(self.cfg.classify("neosatsu.com"), "gate")

    def test_other(self):
        self.assertEqual(self.cfg.classify("example.com"), "other")


class TestExtract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.load(CONFIG)

    def test_anchor_gate_neosatsu(self):
        html = read_fixture("gate_neosatsu.html")
        cands = extract_candidates(html, "https://neosatsu.com/lihat", self.cfg)
        self.assertTrue(any("linkuzu.blogspot.com" in c for c in cands))

    def test_meta_refresh(self):
        html = read_fixture("gate_linkuzu_meta.html")
        cands = extract_candidates(html, "https://linkuzu.blogspot.com/?i=x", self.cfg)
        self.assertTrue(any("mediafire.com" in c for c in cands))

    def test_form_hidden_input(self):
        html = read_fixture("gate_form_hidden.html")
        cands = extract_candidates(html, "https://linkuzu.blogspot.com/", self.cfg)
        self.assertTrue(any("drive.google.com" in c for c in cands))

    def test_js_timer(self):
        html = read_fixture("gate_js_timer.html")
        cands = extract_candidates(html, "https://gate.example/", self.cfg)
        self.assertTrue(any("pixeldrain.com" in c for c in cands))

    def test_data_b64_attribute(self):
        html = read_fixture("gate_data_b64.html")
        cands = extract_candidates(html, "https://gate.example/", self.cfg)
        self.assertTrue(any("gofile.io" in c for c in cands))

    def test_czo_obfuscated_id(self):
        html = read_fixture("gate_czo_data.html")
        cands = extract_candidates(html, "https://neosatsu.com/lihat", self.cfg)
        self.assertTrue(any("gofile.io" in c for c in cands))
        self.assertTrue(any("pixeldrain.com" in c for c in cands))

    def test_no_junk(self):
        html = read_fixture("gate_neosatsu.html")
        cands = extract_candidates(html, "https://neosatsu.com/lihat", self.cfg)
        for c in cands:
            self.assertFalse(c.lower().startswith("javascript:"))
            self.assertFalse(c.lower().startswith("mailto:"))


class TestCaptchaDetect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.load(CONFIG)

    def test_detect_turnstile(self):
        html = read_fixture("gate_captcha_turnstile.html")
        marker = detect_captcha(html, self.cfg)
        self.assertIsNotNone(marker)

    def test_no_captcha_clean(self):
        html = read_fixture("gate_neosatsu.html")
        self.assertIsNone(detect_captcha(html, self.cfg))


class TestSolverOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.load(CONFIG)

    def test_direct_resolve_from_embedded_b64(self):
        # neosatsu menyematkan base64 URL final -> resolve langsung tanpa lewat gate
        neosatsu = read_fixture("gate_neosatsu.html")
        mapping = {"https://neosatsu.com/lihat": neosatsu}
        solver = Solver(self.cfg, FakeFetcher(mapping), max_depth=10, delay=0)
        res = solver.resolve("https://neosatsu.com/lihat")
        self.assertEqual(res["status"], "ok")
        self.assertIn("mediafire.com", res["url_akhir"])
        self.assertEqual(len(res["langkah"]), 2)

    def test_full_chain_multihop(self):
        # neosatsu (gate) -> linkuzu (gate) -> mediafire (file)
        neosatsu = read_fixture("gate_neosatsu_plain.html")
        linkuzu = read_fixture("gate_linkuzu_meta.html")
        mapping = {
            "https://neosatsu.com/lihat": neosatsu,
            "https://linkuzu.blogspot.com/?i=next": linkuzu,
        }
        solver = Solver(self.cfg, FakeFetcher(mapping), max_depth=10, delay=0)
        res = solver.resolve("https://neosatsu.com/lihat")
        self.assertEqual(res["status"], "ok")
        self.assertIn("mediafire.com", res["url_akhir"])
        self.assertEqual(len(res["langkah"]), 3)

    def test_captcha_stops(self):
        captcha_html = read_fixture("gate_captcha_turnstile.html")
        solver = Solver(self.cfg, FakeFetcher({"https://linkuzu.blogspot.com/c": captcha_html}),
                        max_depth=10, delay=0)
        res = solver.resolve("https://linkuzu.blogspot.com/c")
        self.assertEqual(res["status"], "captcha")

    def test_no_link_report(self):
        html = "<html><body><h1>kosong</h1></body></html>"
        solver = Solver(self.cfg, FakeFetcher({"https://gate.example/": html}),
                        max_depth=5, delay=0)
        res = solver.resolve("https://gate.example/")
        self.assertEqual(res["status"], "no_link")

    def test_gate_param_decode(self):
        # linkuzu ?i=<b64> -> decode ke obs id -> host gofile (tanpa fetch)
        solver = Solver(self.cfg, FakeFetcher({}), max_depth=5, delay=0)
        u = solver._decode_gate_param(
            "https://linkuzu.blogspot.com/?i=blgxY3pvblgxdkwyZHZabWxzWlM1cGJ5OWtMemRMVTBKb2JuSndsakk=")
        self.assertEqual(u, "https://gofile.io/d/7KSBhnrp")

    def test_fallback_skip_zonk_mirror(self):
        # Mirror pertama (mediafire) ZONK -> otomatis coba mirror kedua (pixeldrain)
        gate = read_fixture("gate_two_mirrors.html")
        bad = (read_fixture("bad_landing.html"), 200)
        good = read_fixture("good_landing.html")
        mapping = {
            "https://linkuzu.blogspot.com/x": gate,
            "https://www.mediafire.com/file/deadbeefdeadbeef": bad,
            "https://pixeldrain.com/u/GOODCODE123": good,
        }
        fetcher = FakeFetcher(mapping)
        solver = Solver(self.cfg, fetcher, max_depth=5, delay=0)
        res = solver.resolve("https://linkuzu.blogspot.com/x")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["url_akhir"], "https://pixeldrain.com/u/GOODCODE123")
        # yakinkan mirror yang bad memang di-skip (fetch ke mediafire terjadi)
        self.assertIn("https://www.mediafire.com/file/deadbeefdeadbeef", fetcher.requests)

    def test_all_mirrors_zonk(self):
        gate = read_fixture("gate_two_mirrors.html")
        bad = (read_fixture("bad_landing.html"), 404)
        mapping = {
            "https://linkuzu.blogspot.com/x": gate,
            "https://www.mediafire.com/file/deadbeefdeadbeef": bad,
            "https://pixeldrain.com/u/GOODCODE123": bad,
        }
        solver = Solver(self.cfg, FakeFetcher(mapping), max_depth=5, delay=0)
        res = solver.resolve("https://linkuzu.blogspot.com/x")
        self.assertEqual(res["status"], "zonk")
        self.assertIn("ZONK", res["alasan"])

    def test_url_akhir_none_saat_gagal(self):
        # Jangan pernah mengembalikan URL input sebagai "link akhir" saat gagal.
        html = "<html><body><h1>kosong</h1></body></html>"
        solver = Solver(self.cfg, FakeFetcher({"https://gate.example/": html}),
                        max_depth=5, delay=0)
        res = solver.resolve("https://gate.example/")
        self.assertEqual(res["status"], "no_link")
        self.assertIsNone(res["url_akhir"])
        self.assertTrue(res["pesan"])

    def test_link_file_langsung_ditandai_sudah_akhir(self):
        url = "https://gofile.io/d/CwxOktYI"
        mapping = {url: ("<html><body>file</body></html>", 200)}
        solver = Solver(self.cfg, FakeFetcher(mapping), max_depth=3, delay=0)
        res = solver.resolve(url)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["sudah_akhir"])
        self.assertEqual(res["url_akhir"], url)

    def test_deadline_berhenti_dengan_status_timeout(self):
        solver = Solver(self.cfg, FakeFetcher({}), max_depth=5, delay=0, deadline=-1)
        res = solver.resolve("https://gate.example/")
        self.assertEqual(res["status"], "timeout")
        self.assertIsNone(res["url_akhir"])


if __name__ == "__main__":
    unittest.main()
