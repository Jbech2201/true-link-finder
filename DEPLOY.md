# Deploy — True Link Finder (Vercel + GitHub Pages)

Tool inti: CLI lokal. Di bawah ini cara men-deploy dua lapisan UI gratis.

---

## 1. Web live di Vercel (free)

Prasyarat:
- Repo GitHub berisi proyek ini (file `vercel.json`, `api/index.py`, `public/`,
  `requirements.txt`, `config.yaml`, `true_link_finder.py`).
- Akun Vercel + login CLI.

Langkah:

```bash
# (a) dari folder proyek
npm i -g vercel            # atau: npx vercel
vercel login                # login sekali

# (b) deploy preview / production
vercel                      # ikuti wizard: pilih repo, folder root = ./
#  atau deploy langsung tanpa interaksi:
vercel --prod
```

Vercel otomatis mendeteksi `vercel.json`:
- `api/index.py` → serverless function Python
- `public/` → file statis (frontend)
- routing: `/api/resolve` → function, sisanya → frontend

Setelah deploy, buka URL production. Frontend di `public/index.html` akan
memanggil `/api/resolve`.

> Batasan free tier: timeout ±10 dtk → `max_depth` default 6, delay kecil.
> Sebagian situs memblokir IP datacenter → kalau gagal, pakai CLI lokal.

### Test cepat API setelah deploy
```bash
curl -X POST https://<proyek>.vercel.app/api/resolve \
  -H "Content-Type: application/json" \
  -d '{"url":"https://linkuzu.blogspot.com/?i=blgxY3pvblgxdkwyZHZabWxzWlM1cGJ5OWtMemRMVTBKb2JuSndsakk="}'
```

---

## 2. Report HTML statis → GitHub Pages

Cara manual:

```bash
python3 true_link_finder.py --batch daftar.txt --out results.csv
python3 tools/make_report.py --input results.csv --output report/index.html

# publish folder report/ (mis. via branch gh-pages)
```

**Otomatis lewat GitHub Actions** (`.github/workflows/report.yml`):
1. Push repo ke GitHub.
2. GitHub → Settings → Pages → Source: **GitHub Actions**.
3. Tab **Actions** → “Generate Report → GitHub Pages” → **Run workflow**.
4. Isi `urls_file` (mis. `daftar.txt`, berisi URL per baris, harus ada di repo).
5. Workflow: resolve batch → `results.csv` → `report/index.html` → deploy ke gh-pages.

Report bisa dilihat di `https://<user>.github.io/<repo>/`.

---

## Troubleshooting

| Gejala | Solusi |
|--------|--------|
| `/api/resolve` timeout | Turunkan `--max-depth`, atau pakai CLI lokal |
| Function 500 | Cek `requirements.txt` ter-deploy (Vercel baca dari root) |
| CORS di frontend | Sudah ditangani header `Access-Control-Allow-Origin: *` |
| Situs blokir IP server | Gunakan CLI lokal (IP rumahan) |
| GitHub Actions zonk | Pastikan URL di `daftar.txt` valid & situs tidak blokir runner |
