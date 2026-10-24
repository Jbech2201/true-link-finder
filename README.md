# True Link Finder Helper

CLI Python deterministik untuk mengikuti **rantai halaman download perantara** —
misalnya `neosatsu.com` → `linkuzu.blogspot.com/?i=...` → host file akhir
(Google Drive, Mega, Mediafire, Pixeldrain, GoFile, Terabox, dll).

Tool **hanya resolve link** dan mencetak hasil. Ia **tidak** mengunduh file,
tidak memakai AI/LLM, tidak memakai API berbayar/key, dan **tidak pernah**
menyelesaikan atau menembus CAPTCHA.

---

## Instalasi

```bash
cd true-link-finder
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Tanpa `--browser`, cukup 3 pustaka ringan
(`requests`, `beautifulsoup4`, `pyyaml`).

---

## Pakai (single URL)

```bash
python3 true_link_finder.py "https://neosatsu.com/postingan" -v --save debug
```

- `-v / --verbose` — cetak tiap langkah rantai.
- `--save DIR` — simpan HTML tiap halaman ke `DIR/step_N_<domain>.html`.
- `--max-depth N` — batas kedalaman (default: dari config, 10).
- `--delay DETIK` — delay antar request (default: 1.5 dtk).
- `--browser` — gunakan backend Playwright untuk halaman yang link-nya baru
  muncul setelah JS / timer / klik (opsional, Fase 3).
- `--headful` — pakai bersama `--browser`, buka jendela terlihat agar Anda
  bisa menyelesaikan CAPTCHA manual (tool lalu melanjutkan otomatis dari URL
  sesudahnya).

### Contoh keluaran

```
[*] Langkah 1: https://neosatsu.com/postingan
[*]   → lanjut ke: https://linkuzu.blogspot.com/?i=... (gate)
[*] Langkah 2: https://linkuzu.blogspot.com/?i=...

============================================================
  LINK AKHIR DITEMUKAN ✓
============================================================
   1. https://neosatsu.com/postingan
   2. https://linkuzu.blogspot.com/?i=...
   3. https://www.mediafire.com/?d09123456789
------------------------------------------------------------
  HOST AKHIR : mediafire
  LINK AKHIR : https://www.mediafire.com/?d09123456789
============================================================
```

---

## Pakai (batch)

File teks berisi banyak URL, satu per baris (baris `#` diabaikan):

```bash
python3 true_link_finder.py --batch daftar.txt --out results.csv
```

`results.csv` berisi kolom: `url_awal, url_akhir, host, status, alasan`.

---

## Exit code

| Kode | Arti |
|------|------|
| 0 | Sukses — link akhir ditemukan |
| 1 | Tidak ada link akhir / semua mirror ZONK / rantai putus |
| 2 | Terdeteksi CAPTCHA / bot-detection |
| 3 | Error jaringan / HTTP |
| 4 | Pemakaian salah (argumen / file / config) |

---

## Cara kerja

1. **Fetch** halaman (statis via `requests`, atau via Playwright jika `--browser`).
2. **Klasifikasi host** dari `config.yaml`: `file` (berhenti) vs `gate` (lanjut).
3. **Ekstraksi kandidat link** dari HTML statis:
   - `<a href>`, `<iframe src>`, `<meta http-equiv=refresh>`, `<form action>`
   - `input type=hidden`
   - atribut `data-*`
   - pola JS umum: `location.href=...`, `window.open(...)`, `setTimeout` lalu `location`
   - **decode base64 & URL-encode berlapis** (parameter `?i=...`, nilai atribut, dll.)
   - **id ter-obfuskasi pola `czo`** (dipakai mis. neosatsu): `<3 char>czo<3 char>v<base64 path>` → didecode ke URL host
   - **parameter gate `?i=`** (dipakai mis. linkuzu): didecode dari URL *tanpa fetch*,
     sehingga tidak nyasar ke rantai safelink/iklan
4. **Pilih kandidat** secara deterministik: host `file` menang, lalu host `gate`,
   lalu lainnya; elemen iklan/tracker diabaikan (daftar di `config.yaml`).
6. **Deteksi CAPTCHA** (Turnstile / hCaptcha / reCAPTCHA / Cloudflare challenge).
   Jika terdeteksi → berhenti dengan pesan jelas (exit 2), tawarkan mode semi-manual.
7. **Cek kesehatan link tujuan (anti-zonk)** — untuk link host file, tool membuka
   halaman landing host, memeriksa status HTTP + penanda `file not found / deleted /
   expired`. Jika mirror pertama ZONK, otomatis coba mirror berikutnya
   (kualitas/host lain) sampai ketemu yang sehat. Jika semua ZONK → status `zonk`.
   (`--no-check` untuk mematikannya)
8. Ulangi sampai ketemu host file sehat, kedalaman maksimum, atau tidak ada link lanjutan.

---

## Batasan

- **CAPTCHA tidak pernah dilawan.** Tool berhenti dan menyarankan semi-manual:
  selesaikan verifikasi di browser Anda, lalu jalankan ulang dengan URL *setelah*
  halaman itu.
- **Cek kesehatan anti-zonk bersifat "landing page", bukan verifikasi byte penuh.**
  Tool tidak mengunduh isi file. Ia hanya memeriksa status HTTP dan penanda
  "file not found / deleted / expired" di halaman landing host. File yang
  "ada tapi rusak di tengah byte-nya" tidak dapat dideteksi tanpa unduh — itu
  di luar lingkup (dan aturan "tanpa auto-download").
- Halaman yang link-nya **hanya** muncul setelah JS/timer/klik tidak akan terlihat
  oleh parser statis → gunakan `--browser` (atau beri tahu agar tool merekomendasikan
  mode itu).
- Rantai yang berubah-ubah didukung lewat mengedit `config.yaml` tanpa menyentuh kode.
- Tidak ada login/kredensial apa pun.

---

## Struktur

```
true-link-finder/
  true_link_finder.py    # CLI utama
  config.yaml             # aturan host & pola (edit di sini)
  requirements.txt
  tests/                  # unit test OFFLINE (fixture HTML simpanan)
  debug/                  # hasil --save
  results.csv             # hasil batch
```

---

## Mode Web (opsional) & Report Statis

Tool inti tetap CLI lokal. Tapi ada dua lapisan UI tambahan yang gratis:

**1. Web live di Vercel (free)**
- `api/index.py` = serverless function Python (`POST /api/resolve`).
- `public/` = frontend (input URL, daftar hasil, badge status, tombol copy).
- Deploy: import repo ini ke Vercel (file `vercel.json` sudah disiapkan).
- Batasan free tier: timeout ±10 dtk → `max_depth` dibatasi (default 6) dan delay
  dikecilkan. Sebagian situs memblokir IP datacenter → bisa gagal padahal jalan
  lokal; kalau begitu, pakai CLI lokal.

**2. Report HTML statis untuk GitHub Pages**
```bash
python3 true_link_finder.py --batch daftar.txt --out results.csv
python3 tools/make_report.py --input results.csv --output report/index.html
# publish folder report/ ke GitHub Pages (murni statis, tanpa server)
```
Report menampilkan ringkasan (Sehat/Zonk/Gagal) + tabel URL awal → link akhir →
host → status, siap dibagikan.

---

## Tes

```bash
python3 -m unittest discover -s tests -v
```

Semua tes berjalan **offline** memakai fixture HTML simpanan (tanpa akses jaringan).
