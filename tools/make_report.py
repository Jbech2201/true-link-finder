#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Make Report — generate file HTML statis dari results.csv (untuk GitHub Pages).

Pakai:
  python3 tools/make_report.py --input results.csv --output report/index.html
  # lalu publish folder report/ ke GitHub Pages

Server: murni statis (HTML+CSS+JS inline). Tidak perlu server/backend.
"""

import argparse
import csv
import html
import os
import statistics


BADGE = {
    "ok": ("#3fb950", "✓ SEHAT"),
    "zonk": ("#d29922", "⚠ ZONK"),
    "captcha": ("#f85149", "🚫 CAPTCHA"),
    "error": ("#f85149", "✗ ERROR"),
    "no_link": ("#8b949e", "○ TANPA LINK"),
}


def css():
    return """
  :root{--bg:#0e1117;--panel:#161b22;--line:#2d333b;--txt:#e6edf3;--muted:#8b949e}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);
    font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  header{padding:28px 20px 12px;text-align:center}
  h1{margin:0;font-size:26px} .muted{color:var(--muted)}
  main{max-width:980px;margin:0 auto;padding:16px 20px 64px}
  .cards{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0 26px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:14px 20px;flex:1;min-width:120px;text-align:center}
  .stat b{display:block;font-size:28px}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  th,td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line);font-size:13.5px}
  th{background:#1c2128;color:var(--muted);font-weight:600}
  tr:last-child td{border-bottom:0}
  td.url,td.final{font:12.5px "SFMono-Regular",Consolas,monospace;word-break:break-all;max-width:340px}
  .badge{padding:2px 8px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap;color:#0e1117}
  button.copy{background:transparent;border:1px solid var(--line);color:var(--txt);
    border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}
  button.copy:hover{border-color:var(--muted)}
  .note{color:var(--muted);font-size:12.5px;margin-top:18px}
  """


def make_table(rows):
    trs = []
    for r in rows:
        status = r.get("status", "")
        color, label = BADGE.get(status, ("#8b949e", status.upper()))
        host = html.escape(r.get("host", ""))
        alasan = html.escape(r.get("alasan", ""))
        awal = html.escape(r.get("url_awal", ""))
        akhir = html.escape(r.get("url_akhir", "") or "—")
        trs.append(
            "<tr>"
            f'<td class="url">{awal}</td>'
            f'<td class="final">{akhir}</td>'
            f"<td>{host}</td>"
            f'<td><span class="badge" style="background:{color}">{label}</span></td>'
            f"<td>{alasan}</td>"
            "</tr>"
        )
    return "\n".join(trs)


def main():
    ap = argparse.ArgumentParser(description="Generate HTML report dari results.csv")
    ap.add_argument("--input", default="results.csv")
    ap.add_argument("--output", default="report/index.html")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} tidak ditemukan. Jalankan --batch dulu.")
        raise SystemExit(1)

    with open(args.input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    counts = {}
    for r in rows:
        counts[r.get("status", "")] = counts.get(r.get("status", ""), 0) + 1
    ok = counts.get("ok", 0)
    zonk = counts.get("zonk", 0)
    dead = sum(counts.get(k, 0) for k in ("error", "captcha", "no_link"))

    stat_cards = (
        f'<div class="stat"><b style="color:{BADGE["ok"][0]}">{ok}</b><span class="muted">Sehat</span></div>'
        f'<div class="stat"><b style="color:{BADGE["zonk"][0]}">{zonk}</b><span class="muted">Zonk</span></div>'
        f'<div class="stat"><b style="color:{BADGE["error"][0]}">{dead}</b><span class="muted">Gagal/CAPTCHA</span></div>'
        f'<div class="stat"><b>{total}</b><span class="muted">Total</span></div>'
    )

    SCRIPT = """
  <script>
    document.querySelectorAll('button.copy').forEach(function(b){
      b.addEventListener('click', function(){
        var v = b.getAttribute('data-url') || b.parentElement.previousElementSibling.textContent;
        if (navigator.clipboard) navigator.clipboard.writeText(v);
      });
    });
  </script>
"""

    html_doc = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>True Link Finder — Report</title>
<style>{css()}</style>
</head>
<body>
  <header>
    <h1>🔗 True Link Finder — Laporan</h1>
    <p class="muted">Dibuat {__import__('datetime').datetime.now().strftime('%d %b %Y %H:%M')} · dari {os.path.basename(args.input)}</p>
  </header>
  <main>
    <div class="cards">{stat_cards}</div>
    <table>
      <thead><tr><th>URL awal</th><th>Link akhir</th><th>Host</th><th>Status</th><th>Catatan</th></tr></thead>
      <tbody>{make_table(rows)}</tbody>
    </table>
    <p class="note">Report statis ini bisa dibuka offline &amp; di-publish ke GitHub Pages. Hasil dihasilkan oleh CLI/API, bukan report.</p>
  </main>
  {SCRIPT}
</body>
</html>"""

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"Report tersimpan: {args.output} ({total} baris)")


if __name__ == "__main__":
    main()
