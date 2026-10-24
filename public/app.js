/* True Link Finder — frontend logic */
"use strict";

const btn = document.getElementById("run");
const ta = document.getElementById("urls");
const chk = document.getElementById("check");
const results = document.getElementById("results");

const STATUS_LABEL = {
  ok: "✓ SEHAT",
  zonk: "⚠ ZONK / SEMUA MATI",
  captcha: "🚫 CAPTCHA",
  error: "✗ ERROR",
  no_link: "○ TANPA LINK",
};

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function copyToClipboard(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text);
  } else {
    const el = document.createElement("textarea");
    el.value = text;
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    el.remove();
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

  const top = document.createElement("div");
  top.className = "top";
  top.innerHTML = `<span class="u">${esc(url)}</span>`;

  const label = res.error ? "error" : res.status || "unknown";
  const badge = document.createElement("span");
  badge.className = "badge " + badgeClass(label);
  badge.textContent = STATUS_LABEL[label] || label.toUpperCase();
  top.appendChild(badge);
  card.appendChild(top);

  if (res.error) {
    const e = document.createElement("div");
    e.className = "err";
    e.textContent = res.error;
    card.appendChild(e);
    return card;
  }

  const detail = document.createElement("div");
  detail.className = "detail";
  detail.textContent =
    (res.host ? "Host akhir: " + res.host : "") +
    (res.lama_detik ? " · " + res.lama_detik + " dtk" : "") +
    (res.alasan ? " · " + res.alasan : "");
  card.appendChild(detail);

  const chain = document.createElement("div");
  chain.className = "chain";
  (res.langkah || []).forEach((s, i) => {
    const step = document.createElement("div");
    step.className = "step" + (i === res.langkah.length - 1 ? " final" : "");
    step.textContent = (i + 1) + ". " + s;
    chain.appendChild(step);
  });
  card.appendChild(chain);

  if (res.url_akhir && label !== "error") {
    const fb = document.createElement("div");
    fb.className = "finalbox";
    const input = document.createElement("input");
    input.readOnly = true;
    input.value = res.url_akhir;
    const cp = document.createElement("button");
    cp.className = "copy";
    cp.textContent = "Copy";
    cp.addEventListener("click", () => {
      copyToClipboard(res.url_akhir);
      cp.textContent = "Copied ✓";
      setTimeout(() => (cp.textContent = "Copy"), 1200);
    });
    fb.appendChild(input);
    fb.appendChild(cp);
    card.appendChild(fb);
  }

  return card;
}

async function resolveOne(url) {
  const r = await fetch("/api/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, check: chk.checked }),
  });
  return r.json();
}

async function run() {
  const urls = ta.value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!urls.length) return;

  btn.disabled = true;
  results.innerHTML = "";

  // sequential biar adil/throttle
  for (const u of urls) {
    const pending = document.createElement("div");
    pending.className = "card";
    pending.innerHTML =
      `<div class="top"><span class="u">${esc(u)}</span></div>` +
      `<div class="detail"><span class="spin"></span>Menyelesaikan rantai…</div>`;
    results.appendChild(pending);

    let res;
    try {
      res = await resolveOne(u);
    } catch (e) {
      res = { error: "Gagal terhubung ke API: " + e.message };
    }
    pending.replaceWith(resultCard(u, res));
  }

  btn.disabled = false;
}

btn.addEventListener("click", run);
