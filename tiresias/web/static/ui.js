/* Shared helpers for the registry pages (landing, console, shared answers). Every node is
   built with h(); text from a tenant or a bundle is only ever set as text, never as HTML. */
"use strict";
window.T = (() => {
  const NUM = new Intl.NumberFormat("en-US");
  function h(tag, attrs, ...kids) {
    const svg = tag.startsWith("svg:");
    const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }
  function toast(msg) {
    let t = document.getElementById("toast");
    if (!t) { t = h("div", { id: "toast", class: "toast", role: "status", "aria-live": "polite" }); document.body.append(t); }
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.id); toast.id = setTimeout(() => t.classList.remove("show"), 2200);
  }
  const copyable = (text, label) => h("button", { class: "copy", type: "button", title: "Copy", onclick: async () => {
    try { await navigator.clipboard.writeText(String(text)); toast((label || "Value") + " copied"); } catch { toast("Copy failed"); }
  } }, String(text));
  const seal = (kind, text) => h("span", { class: "seal " + kind }, text);
  const when = (t) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const cap = (x) => (typeof x === "string" && x ? x.charAt(0).toUpperCase() + x.slice(1) : x);
  const notice = (kind, title, body) => h("div", { class: "notice " + kind }, h("b", { text: title }), cap(body));
  function answer(r) {
    if (!r || typeof r !== "object") return "";
    if (r.groups) return Object.entries(r.groups).map(([k, v]) => k + ": " + NUM.format(v)).join(" · ") + ((r.suppressed || []).length ? " · " + r.suppressed.length + " withheld" : "");
    const v = r.avg !== undefined ? r.avg : r.value !== undefined ? r.value : r.sum;
    return typeof v === "number" ? NUM.format(v) : String(v);
  }
  const CHECK = {
    "dataset id matches manifest": "The proof names this dataset",
    "the query is a Tiresias query over this dataset": "The question is one this dataset can answer",
    "the receipt verifies": "The RISC Zero receipt verifies",
    "proved over the published commitment": "It was proved over the published commitment",
    "proved under the published schema": "It was proved under the published schema",
    "proved this query, under this dataset's cohort floor": "It proves this question, under this dataset's floor",
    "the stated answer is the proved answer": "The answer shown is the answer proved",
    "every answer describes at least min_cohort rows": "Every answer describes at least the minimum cohort",
  };
  function checks(v) {
    return h("ul", { class: "checks" }, ...(v.checks || []).map((c) => h("li", {},
      h("span", { class: "mark " + (c.passed ? "ok" : "bad"), "aria-label": c.passed ? "passed" : "failed", text: c.passed ? "✓" : "✕" }),
      h("div", {}, h("div", { text: CHECK[c.name] || c.name }), c.detail ? h("div", { class: "detail", text: c.detail }) : null))));
  }
  function theme() {
    let saved = null;
    try { saved = localStorage.getItem("tiresias-theme"); } catch { /* storage blocked */ }
    if (saved) document.documentElement.dataset.theme = saved;
    const btn = document.getElementById("theme");
    if (btn) btn.addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("tiresias-theme", document.documentElement.dataset.theme); } catch { /* ignore */ }
    });
  }
  theme();
  return { h, toast, copyable, seal, when, cap, notice, answer, checks, NUM };
})();
