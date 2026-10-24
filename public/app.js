/* True Link Finder — frontend (mode hybrid: browser orkestrasi) */
"use strict";

const MAX_DEPTH = 8;
const HOP_DELAY = 400; // ms antar hop (di sisi klien, bukan server)

const btn = document.getElementById("run");
const ta = document.getElementById("urls");
const results = document.getElementById("results");

const STATUS_LABEL = {
  ok: "✓ SEHAT",
  zonk: "⚠ ZONK / SEMUA MATI",
  captcha: "🚫 CAPTCHA",
  timeout: "⏱ WAKTU HABIS",
  error: "✗ ERROR",
  no_link: "○ TANPA LINK",
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; };
const hostOf = (u) => { try { return (new URL(u)).hostname.replace(/^www\./, ""); } catch { return ""; } };

async function api(path, payload) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const text = await r.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    return {
      error:
        `API ${path} membalas HTTP ${r.status} tanpa JSON ` +
        `(kemungkinan timeout server). Coba lagi.`,
    };
  }
}
const probe = (url) => api("/api/probe", { url });
const checkHealth = (url) => api("/api/check", { url });

async function resolveOne(url) {
  const steps = [];
  let current = url;

  for (let depth = 0; depth < MAX_DEPTH; depth++) {
    let p;
    try { p = await probe(current); }
    catch (e) { return { status: "error", error: "Gagal terhubung ke API: " + e.message, url_awal: url, langkah: steps }; }

    if (!steps.includes(p.final_url)) steps.push(p.final_url);

    if (p.error) return { status: "error", error: p.error, url_awal: url, langkah: steps };

    if (p.captcha) {
      return {
        status: "captcha", host: p.host, url_akhir: null, langkah: steps,
        alasan: "Indikator '" + p.captcha + "' — tool tidak menyelesaikan CAPTCHA.",
        pesan: "Buka halaman ini manual di browser, selesaikan verifikasi, lalu tempel URL sesudahnya.",
      };
    }

    // Jika halaman ini sudah host file, anggap sebagai kandidat
    const candidates = [];
    if (p.direct) candidates.push(p.direct);
    if (p.cls === "file") candidates.push(p.final_url);
    (p.files || []).forEach((u) => { if (!candidates.includes(u)) candidates.push(u); });

    if (candidates.length) {
      let allBad = true;
      for (const u of candidates) {
        let h;
        try { h = await checkHealth(u); } catch { h = { status: "unknown" }; }
        if (h.status !== "bad") {
          return {
            status: "ok", host: hostOf(u), url_akhir: u,
            langkah: steps.concat([u]), alasan: (h.detail || ""),
            sudah_akhir: u === url,
            pesan: u === url
              ? "URL yang kamu masukkan sudah berupa link host file. Tidak ada rantai perantara."
              : "",
          };
        }
      }
      return {
        status: "zonk", host: hostOf(current), url_akhir: null, langkah: steps,
        alasan: "Semua mirror terindikasi ZONK (mati/hapus).",
        pesan: "Coba matikan cek kesehatan, atau periksa link manual.",
      };
    }

    if (!p.next || steps.includes(p.next)) {
      return {
        status: "no_link", host: p.host, url_akhir: null, langkah: steps,
        alasan: "Tidak ada link lanjutan (mungkin JS-only/timer).",
        pesan: "Halaman ini butuh JavaScript/timer. Coba buka manual, atau pakai CLI dengan --browser.",
      };
    }

    steps.push(p.next);  // catat hop
    current = p.next;
    await sleep(HOP_DELAY);
  }

  return {
    status: "no_link", host: hostOf(current), url_akhir: null, langkah: steps,
    alasan: "Batas kedalaman (" + MAX_DEPTH + ") tercapai.",
    pesan: "Rantai terlalu panjang atau berputar. Coba mulai dari URL gate yang lebih dekat.",
  };
}

function copyToClipboard(text) {
  if (navigator.clipboard) navigator.clipboard.writeText(text);
  else {
    const el = document.createElement("textarea"); el.value = text;
    document.body.appendChild(el); el.select(); document.execCommand("copy"); el.remove();
  }
}

function badgeClass(status) {
  if (status === "ok") return "ok";
  if (status === "zonk") return "zonk";
  if (status === "captcha" || status === "error") return "captcha";
  return "zonk";
}

function resultCard(url, res) {
  const card = document.createElement("div");
  card.className = "card";

  const label = res.error ? "error" : res.status || "unknown";
  const top = document.createElement("div");
  top.className = "top";
  top.innerHTML = `<span class="u">${esc(url)}</span>`;
  const badge = document.createElement("span");
  badge.className = "badge " + badgeClass(label);
  badge.textContent = STATUS_LABEL[label] || label.toUpperCase();
  top.appendChild(badge);
  card.appendChild(top);

  if (res.error) {
    const e = document.createElement("div"); e.className = "err"; e.textContent = res.error;
    card.appendChild(e); return card;
  }

  const detail = document.createElement("div");
  detail.className = "detail";
  detail.textContent = (res.host ? "Host akhir: " + res.host : "") + (res.alasan ? " · " + res.alasan : "");
  card.appendChild(detail);

  if (res.pesan) {
    const note = document.createElement("div");
    note.className = "detail";
    note.textContent = res.pesan;
    card.appendChild(note);
  }

  const chain = document.createElement("div");
  chain.className = "chain";
  (res.langkah || []).forEach((s, i) => {
    const step = document.createElement("div");
    step.className = "step" + (i === res.langkah.length - 1 ? " final" : "");
    step.textContent = (i + 1) + ". " + s;
    chain.appendChild(step);
  });
  card.appendChild(chain);

  if (res.url_akhir && label === "ok") {
    const fb = document.createElement("div"); fb.className = "finalbox";
    const input = document.createElement("input"); input.readOnly = true; input.value = res.url_akhir;
    const cp = document.createElement("button"); cp.className = "copy"; cp.textContent = "Copy";
    cp.addEventListener("click", () => {
      copyToClipboard(res.url_akhir);
      cp.textContent = "Copied ✓"; setTimeout(() => (cp.textContent = "Copy"), 1200);
    });
    fb.appendChild(input); fb.appendChild(cp); card.appendChild(fb);
  }

  return card;
}

async function run() {
  const urls = ta.value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!urls.length) return;
  btn.disabled = true;
  results.innerHTML = "";

  for (const u of urls) {
    const pending = document.createElement("div");
    pending.className = "card";
    pending.innerHTML =
      `<div class="top"><span class="u">${esc(u)}</span></div>` +
      `<div class="detail"><span class="spin"></span>Menyelesaikan rantai…</div>`;
    results.appendChild(pending);

    let res;
    try { res = await resolveOne(u); }
    catch (e) { res = { error: "Gagal: " + e.message }; }
    pending.replaceWith(resultCard(u, res));
  }

  btn.disabled = false;
}

btn.addEventListener("click", run);
