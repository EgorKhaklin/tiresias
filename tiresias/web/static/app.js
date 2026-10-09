/* Tiresias workbench. Plain JavaScript, no dependencies, no inline handlers (the page runs
   under a strict Content-Security-Policy). Every node is built with h(); nothing from a
   CSV or the engine is ever written as HTML. */
"use strict";
(() => {
  const NUM = new Intl.NumberFormat("en-US");
  const AGG = {
    sum: { label: "Total", word: "Total" },
    avg: { label: "Average", word: "Average" },
    count: { label: "Count", word: "Number of rows" },
    min: { label: "Lowest", word: "Lowest" },
    max: { label: "Highest", word: "Highest" },
  };
  const TYPES = { int: "Number", bool: "Yes / no", category: "Category" };
  // The engine's check names, in plain words.
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
  const OPS = {
    int: [["=", "is"], ["!=", "is not"], ["<", "below"], [">", "above"], ["<=", "at most"], [">=", "at least"]],
    category: [["=", "is"], ["!=", "is not"]],
    bool: [["=", "is"]],
  };

  const state = { datasets: [], bundles: [], draft: null, current: null, builder: null, busy: false, focus: null, editSql: false };

  // --- DOM -----------------------------------------------------------------
  function h(tag, attrs, ...kids) {
    const svg = tag.startsWith("svg:");
    const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else if (k === "class") el.setAttribute("class", v);
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const hex = (w) => h("svg:svg", { viewBox: "0 0 64 64", fill: "none", stroke: "currentColor", "stroke-width": w || 2, "aria-hidden": "true" },
    h("svg:path", { d: "M32 4 56.2 18v28L32 60 7.8 46V18Z", "stroke-linejoin": "round" }));
  function oracle(text) {
    const s = hex(2);
    s.append(h("svg:path", { d: "M32 18v14l12 7M32 32 20 39", "stroke-linecap": "round", opacity: ".6" }));
    const t = h("div", { class: "t", text });
    const timer = h("div", { class: "small faint", text: "0 s" });
    const start = Date.now();
    const id = setInterval(() => { if (!timer.isConnected) clearInterval(id); else timer.textContent = Math.round((Date.now() - start) / 1000) + " s"; }, 1000);
    return h("div", { class: "oracle", role: "status" }, s, t, timer);
  }
  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.id); toast.id = setTimeout(() => t.classList.remove("show"), 2200);
  }
  function copyable(text, label) {
    return h("button", { class: "copy", type: "button", title: "Copy", onclick: async () => {
      try { await navigator.clipboard.writeText(String(text)); toast((label || "Value") + " copied"); } catch { toast("Copy failed"); }
    } }, String(text));
  }
  const seal = (kind, text) => h("span", { class: "seal " + kind }, text);
  const when = (t) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const cap = (x) => (typeof x === "string" && x ? x.charAt(0).toUpperCase() + x.slice(1) : x);
  function notice(kind, title, body) { return h("div", { class: "notice " + kind, role: kind === "bad" ? "alert" : null }, h("b", { text: title }), cap(body)); }

  // --- API -----------------------------------------------------------------
  async function api(method, path, body) {
    const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    let j = {};
    try { j = await r.json(); } catch { /* not JSON */ }
    if (!r.ok) { const e = new Error(j.error || "The request failed (" + r.status + ")"); e.kind = j.kind || "error"; throw e; }
    return j;
  }
  async function refresh() {
    const s = await api("GET", "/api/state");
    state.datasets = s.datasets.sort((a, b) => b.created_at - a.created_at);
    state.bundles = s.bundles.sort((a, b) => b.created_at - a.created_at);
    if (!state.current && state.datasets.length) state.current = state.datasets[0].dataset_id;
  }
  const dataset = (id) => state.datasets.find((d) => d.dataset_id === id);

  // --- theme and routing -----------------------------------------------------
  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("tiresias-theme"); } catch { /* storage blocked */ }
    if (saved) document.documentElement.dataset.theme = saved;
    document.getElementById("theme").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("tiresias-theme", document.documentElement.dataset.theme); } catch { /* ignore */ }
    });
  }
  const route = () => (location.hash.replace(/^#\/?/, "").split("/")[0] || "datasets");
  function render() {
    const r = route();
    for (const a of document.querySelectorAll("[data-route]")) a.toggleAttribute("aria-current", a.dataset.route === r) && a.setAttribute("aria-current", "page");
    const main = document.getElementById("main");
    main.replaceChildren((VIEWS[r] || VIEWS.datasets)());
  }

  // --- Datasets ----------------------------------------------------------------
  function viewDatasets() {
    const page = h("section", {},
      h("p", { class: "eyebrow", text: "Datasets" }),
      h("h1", { text: "Commit a private dataset" }),
      h("p", { class: "lede", text: "Tiresias fingerprints your rows into a commitment. Every answer it proves later is bound to that commitment, so nobody can swap the data under a result. The rows stay on this machine." }),
      h("div", { class: "meander", "aria-hidden": "true" }));
    page.append(state.draft ? review() : dropZone());
    if (state.datasets.length) {
      page.append(h("div", { class: "meander", "aria-hidden": "true" }), h("h2", { text: "Committed in this session" }), h("div", { style: null, class: "stack", }, ...state.datasets.map(datasetCard)));
      page.lastChild.style.marginTop = "18px";
    }
    return page;
  }
  function dropZone() {
    const input = h("input", { type: "file", accept: ".csv,text/csv", class: "sr", id: "csvfile", onchange: (e) => e.target.files[0] && readFile(e.target.files[0]) });
    const icon = hex(2.2);
    icon.append(h("svg:path", { d: "M32 20v20m-8-8 8 8 8-8", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    const zone = h("label", { class: "drop", for: "csvfile" },
      icon, h("h3", { text: "Drop a CSV here" }),
      h("p", { class: "muted", text: "or choose a file. One header row; columns of numbers, yes/no values or labels." }));
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); const f = e.dataTransfer.files[0]; if (f) readFile(f); });
    return h("div", { class: "tablet" }, input, zone,
      h("div", { class: "row actions" },
        h("span", { class: "muted small", text: "No data to hand?" }),
        h("button", { class: "btn quiet small", type: "button", onclick: useSample }, "Use the sample payroll")));
  }
  async function readFile(file) {
    if (file.size > 15 * 1024 * 1024) { toast("That file is over 15 MB"); return; }
    await inspect(await file.text(), file.name.replace(/\.csv$/i, ""));
  }
  async function useSample() { const s = await api("POST", "/api/sample"); await inspect(s.csv, s.name); }
  async function inspect(csv, name) {
    try {
      const info = await api("POST", "/api/inspect", { csv });
      const types = Object.fromEntries(info.columns.map((c) => [c.name, c.guess]));
      state.draft = { csv, name, info, types, minCohort: Math.min(5, info.rows), error: null };
    } catch (e) { state.draft = null; toast(e.message); return; }
    render();
  }
  function review() {
    const d = state.draft, info = d.info;
    const err = h("div");
    const cols = info.columns.map((c) => {
      const sel = h("select", { "aria-label": "Type of " + c.name, onchange: (e) => { d.types[c.name] = e.target.value; } },
        ...Object.entries(TYPES).map(([v, l]) => h("option", { value: v, selected: d.types[c.name] === v }, l)));
      return h("div", { class: "colcard" }, h("div", { class: "row" }, h("span", { class: "name", text: c.name }), h("span", { class: "spacer" }), sel),
        h("div", { class: "hint", text: "Detected: " + c.why + "." }));
    });
    const preview = h("div", { class: "scrollx" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, ...info.headers.map((x) => h("th", { text: x })))),
      h("tbody", {}, ...info.preview.map((row) => h("tr", {}, ...row.map((v) => h("td", { text: v })))))));
    const name = h("input", { type: "text", value: d.name, maxlength: "80", oninput: (e) => { d.name = e.target.value; } });
    const floor = h("input", { type: "number", min: "1", max: String(info.rows), value: String(d.minCohort), class: "inline", style: null, oninput: (e) => { d.minCohort = Number(e.target.value); } });
    floor.style.width = "110px";
    const go = h("button", { class: "btn primary", type: "button", onclick: async () => {
      go.disabled = true; go.textContent = "Committing…"; err.replaceChildren();
      try {
        const r = await api("POST", "/api/commit", { csv: d.csv, name: d.name, types: d.types, min_cohort: d.minCohort });
        state.draft = null; state.current = r.manifest.dataset_id; await refresh();
        toast("Committed: " + r.manifest.name); location.hash = "#/ask"; render();
      } catch (e) { err.replaceChildren(notice("bad", "The dataset could not be committed.", e.message)); go.disabled = false; go.textContent = "Commit dataset"; }
    } }, "Commit dataset");
    return h("div", { class: "tablet" },
      h("div", { class: "tablet-head" }, h("h2", { text: "Review before committing" }), h("span", { class: "muted small", text: NUM.format(info.rows) + " rows · " + info.columns.length + " columns" })),
      h("div", { class: "grid two" },
        h("label", { class: "field" }, h("span", { text: "Name" }), name),
        h("label", { class: "field" }, h("span", { text: "Minimum cohort" }), floor,
          h("small", { text: "Every answer must describe at least this many rows. Smaller groups are withheld, never answered." }))),
      h("hr", { class: "soft" }),
      h("h3", { text: "Columns" }), h("p", { class: "muted small", text: "Numbers can be summed, averaged and compared; categories and yes/no columns can be filtered on and broken down by." }),
      h("div", { class: "grid three" }, ...cols),
      h("hr", { class: "soft" }),
      h("h3", { text: "Preview" }), h("p", { class: "muted small", text: "The first rows, shown only here. They are not sent anywhere." }),
      preview, err,
      h("div", { class: "row actions" }, go, h("button", { class: "btn quiet", type: "button", onclick: () => { state.draft = null; render(); } }, "Cancel")));
  }
  function datasetCard(m) {
    return h("div", { class: "tablet" },
      h("div", { class: "tablet-head" }, h("h2", { text: m.name }),
        h("button", { class: "btn small", type: "button", onclick: () => { state.current = m.dataset_id; state.builder = null; location.hash = "#/ask"; } }, "Ask a question")),
      h("dl", { class: "kv" },
        h("dt", { text: "Rows" }), h("dd", { text: NUM.format(m.row_count) }),
        h("dt", { text: "Columns" }), h("dd", { text: m.schema.map((c) => c.name + " (" + TYPES[c.type].toLowerCase() + ")").join(", ") }),
        h("dt", { text: "Minimum cohort" }), h("dd", { text: String(m.min_cohort) }),
        h("dt", { text: "Commitment" }), h("dd", {}, copyable(m.commitment, "Commitment")),
        h("dt", { text: "Dataset id" }), h("dd", {}, copyable(m.dataset_id, "Dataset id")),
        h("dt", { text: "Committed" }), h("dd", { text: when(m.created_at) })));
  }

  // --- Ask ----------------------------------------------------------------------
  function freshBuilder(m) {
    const nums = m.schema.filter((c) => c.type === "int");
    return { agg: nums.length ? "avg" : "count", column: nums[0] ? nums[0].name : "", conds: [], group: "", sql: "" };
  }
  function condValue(c, col) {
    if (col.type === "category") return "'" + String(c.val).replace(/'/g, "") + "'";
    if (col.type === "bool") return c.val === "yes" ? "1" : "0";
    return String(Math.max(0, Math.trunc(Number(c.val) || 0)));
  }
  function toSql(m, b) {
    const where = b.conds.filter((c) => c.col && c.val !== "").map((c) => c.col + " " + c.op + " " + condValue(c, m.schema.find((x) => x.name === c.col)));
    const w = where.length ? " WHERE " + where.join(" AND ") : "";
    if (b.group) return "SELECT SUM(" + b.column + ")" + w + " GROUP BY " + b.group;
    return "SELECT " + b.agg.toUpperCase() + "(" + (b.agg === "count" ? "*" : b.column) + ")" + w;
  }
  function toEnglish(m, b) {
    const opWord = (c, col) => (OPS[col.type].find((o) => o[0] === c.op) || [c.op, c.op])[1];
    const where = b.conds.filter((c) => c.col && c.val !== "").map((c) => {
      const col = m.schema.find((x) => x.name === c.col);
      return c.col + " " + opWord(c, col) + " " + (col.type === "int" ? NUM.format(Number(c.val) || 0) : c.val);
    });
    let s = b.group ? "Total " + b.column + " by " + b.group : b.agg === "count" ? "Number of rows" : AGG[b.agg].word + " " + b.column;
    if (where.length) s += " where " + where.join(" and ");
    return s;
  }
  function viewAsk() {
    const page = h("section", {}, h("p", { class: "eyebrow", text: "Ask" }), h("h1", { text: "Ask a question, get a proof" }),
      h("p", { class: "lede", text: "The answer comes back with a proof that it is the true result over the committed rows, and with the number of rows it describes." }),
      h("div", { class: "meander", "aria-hidden": "true" }));
    if (!state.datasets.length) {
      page.append(h("div", { class: "tablet empty" }, h("h3", { text: "No dataset yet" }), h("p", { text: "Commit a dataset first; questions are asked of a commitment." }),
        h("a", { class: "btn primary", href: "#/datasets" }, "Commit a dataset")));
      return page;
    }
    const m = dataset(state.current) || state.datasets[0];
    state.current = m.dataset_id;
    if (!state.builder || state.builder.dataset !== m.dataset_id) state.builder = Object.assign(freshBuilder(m), { dataset: m.dataset_id });
    const b = state.builder;
    const out = h("div", { id: "answer" });
    const sqlView = h("div", { class: "sqlbox", "aria-live": "polite" });
    const english = h("p", { class: "muted", style: null });
    const sqlEdit = h("textarea", { rows: "2", spellcheck: "false", "aria-label": "SQL" });
    const builderBox = h("div", { class: "builder" });

    const nums = m.schema.filter((c) => c.type === "int");
    const cats = m.schema.filter((c) => c.type === "category");
    function sync() {
      const sql = toSql(m, b);
      sqlView.replaceChildren(...sql.split(/(\b(?:SELECT|WHERE|AND|GROUP BY|SUM|AVG|COUNT|MIN|MAX)\b)/).map((p) => /^(SELECT|WHERE|AND|GROUP BY|SUM|AVG|COUNT|MIN|MAX)$/.test(p) ? h("b", { text: p }) : p));
      english.textContent = toEnglish(m, b) + ".";
      if (!state.editSql) sqlEdit.value = sql;
    }
    function drawBuilder() {
      const aggSel = h("select", { "aria-label": "What to compute", onchange: (e) => { b.agg = e.target.value; if (b.agg !== "sum") b.group = ""; drawBuilder(); } },
        ...Object.entries(AGG).filter(([k]) => k === "count" || nums.length).map(([k, v]) => h("option", { value: k, selected: b.agg === k }, v.label)));
      const colSel = b.agg === "count" ? h("span", { text: "rows" }) : h("select", { "aria-label": "Column", onchange: (e) => { b.column = e.target.value; sync(); } },
        ...nums.map((c) => h("option", { value: c.name, selected: b.column === c.name }, c.name)));
      const lines = [h("div", {}, "The ", aggSel, " of ", colSel)];
      b.conds.forEach((c, i) => {
        const col = m.schema.find((x) => x.name === c.col) || m.schema[0];
        const colPick = h("select", { "aria-label": "Condition column", onchange: (e) => { c.col = e.target.value; const t = m.schema.find((x) => x.name === c.col).type; c.op = "="; c.val = t === "bool" ? "yes" : t === "category" ? labelsOf(m, c.col)[0] : "0"; drawBuilder(); } },
          ...m.schema.map((x) => h("option", { value: x.name, selected: x.name === c.col }, x.name)));
        const opPick = h("select", { "aria-label": "Comparison", onchange: (e) => { c.op = e.target.value; sync(); } },
          ...OPS[col.type].map(([o, w]) => h("option", { value: o, selected: o === c.op }, w)));
        let val;
        if (col.type === "category") val = h("select", { "aria-label": "Value", onchange: (e) => { c.val = e.target.value; sync(); } }, ...labelsOf(m, c.col).map((l) => h("option", { value: l, selected: l === c.val }, l)));
        else if (col.type === "bool") val = h("select", { "aria-label": "Value", onchange: (e) => { c.val = e.target.value; sync(); } }, h("option", { value: "yes", selected: c.val === "yes" }, "yes"), h("option", { value: "no", selected: c.val === "no" }, "no"));
        else { val = h("input", { type: "number", min: "0", step: "1", value: c.val, "aria-label": "Value", oninput: (e) => { c.val = e.target.value; sync(); } }); val.style.width = "130px"; }
        lines.push(h("div", { class: "cond" }, h("span", { class: "muted", text: i ? "and" : "where" }), colPick, opPick, val,
          h("button", { class: "btn quiet small", type: "button", "aria-label": "Remove this condition", onclick: () => { b.conds.splice(i, 1); drawBuilder(); } }, "Remove")));
      });
      const add = h("button", { class: "btn quiet small", type: "button", onclick: () => {
        const c0 = cats[0] || m.schema[0];
        b.conds.push({ col: c0.name, op: "=", val: c0.type === "category" ? labelsOf(m, c0.name)[0] : c0.type === "bool" ? "yes" : "0" }); drawBuilder();
      } }, "+ Add a condition");
      const groupSel = h("select", { "aria-label": "Break down by", disabled: b.agg !== "sum" || !cats.length, onchange: (e) => { b.group = e.target.value; sync(); } },
        h("option", { value: "" }, "no breakdown"), ...cats.map((c) => h("option", { value: c.name, selected: b.group === c.name }, c.name)));
      lines.push(h("div", { class: "cond" }, add, h("span", { class: "spacer" }), h("span", { class: "muted", text: "broken down by" }), groupSel));
      if (b.agg !== "sum" && cats.length) lines.push(h("div", { class: "small faint", text: "Breakdowns are available for totals." }));
      builderBox.replaceChildren(...lines);
      sync();
    }
    drawBuilder();

    const datasetPick = state.datasets.length > 1 ? h("select", { "aria-label": "Dataset", class: "inline", onchange: (e) => { state.current = e.target.value; state.builder = null; render(); } },
      ...state.datasets.map((d) => h("option", { value: d.dataset_id, selected: d.dataset_id === m.dataset_id }, d.name))) : h("b", { text: m.name });
    const editToggle = h("button", { class: "btn quiet small", type: "button", onclick: () => {
      state.editSql = !state.editSql; sqlEdit.hidden = !state.editSql; sqlView.hidden = state.editSql; builderBox.hidden = state.editSql; english.hidden = state.editSql;
      editToggle.textContent = state.editSql ? "Use the builder" : "Write SQL instead"; if (!state.editSql) sync();
    } }, state.editSql ? "Use the builder" : "Write SQL instead");
    sqlEdit.hidden = !state.editSql; sqlView.hidden = state.editSql; builderBox.hidden = state.editSql; english.hidden = state.editSql;
    const run = h("button", { class: "btn primary", type: "button", onclick: () => ask(m, state.editSql ? sqlEdit.value : toSql(m, b), state.editSql ? sqlEdit.value : toEnglish(m, b), out, run) }, "Prove the answer");

    page.append(h("div", { class: "tablet" },
      h("div", { class: "tablet-head" }, h("div", { class: "row" }, h("span", { class: "muted", text: "Asking" }), datasetPick,
        h("span", { class: "faint small", text: "· floor " + m.min_cohort + " rows" })), editToggle),
      builderBox, sqlEdit, h("div", { class: "stack actions" }, english, sqlView),
      h("div", { class: "row actions" }, run, h("span", { class: "muted small", text: "Proving runs on this machine and takes about a minute." }))), out);
    if (state.focus) { renderAnswer(out, state.focus.bundle, state.focus.english); }
    return page;
  }
  function labelsOf(m, name) {
    const c = m.schema.find((x) => x.name === name);
    return c && c.categories ? Object.keys(c.categories) : [];
  }
  async function ask(m, sql, english, out, run) {
    run.disabled = true;
    out.replaceChildren(h("div", { class: "tablet", style: null }, oracle("Proving in the zkVM over the committed rows. About a minute…")));
    out.firstChild.style.marginTop = "18px";
    try {
      const r = await api("POST", "/api/query", { dataset_id: m.dataset_id, sql });
      r.bundle.receipt_bytes = r.receipt_bytes;
      state.focus = { bundle: r.bundle, english };
      await refresh();
      renderAnswer(out, r.bundle, english);
    } catch (e) {
      const box = e.kind === "refused" ? notice("warn", "Tiresias declined to answer.", e.message)
        : e.kind === "invalid" ? notice("bad", "That question could not be read.", e.message) : notice("bad", "Something went wrong while proving.", e.message);
      out.replaceChildren(h("div", { style: null }, box)); out.firstChild.style.marginTop = "18px";
    } finally { run.disabled = false; }
  }

  function answerCard(bundle, english) {
    const r = bundle.result;
    const card = h("div", { class: "tablet answer" });
    card.append(h("div", { class: "q", text: english }));
    if (r.groups) {
      const rows = Object.entries(r.groups).map(([k, v]) => h("tr", {}, h("td", { text: k }), h("td", { class: "num", text: NUM.format(v) }), h("td", { class: "num muted", text: NUM.format(r.cohorts[k]) + " rows" })));
      for (const s of r.suppressed || []) rows.push(h("tr", {}, h("td", { text: s }), h("td", { class: "num muted", text: "withheld" }), h("td", { class: "num faint", text: "too few rows" })));
      card.append(h("div", { class: "scrollx", style: null }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", { text: r.group_by }), h("th", { class: "num", text: "Total " + r.column }), h("th", { class: "num", text: "Cohort" }))), h("tbody", {}, ...rows))));
      card.lastChild.style.marginTop = "18px"; card.lastChild.style.textAlign = "left";
      if ((r.suppressed || []).length) card.append(h("p", { class: "small muted", text: "Withheld groups describe fewer rows than the dataset's floor; Tiresias never answers about them." }));
    } else {
      const v = r.avg !== undefined ? r.avg : r.value !== undefined ? r.value : r.sum;
      const big = h("div", { class: "v", text: NUM.format(v) });
      if (String(v).length > 9) big.classList.add("sm");
      card.append(big);
      const parts = ["over " + NUM.format(r.cohort !== undefined ? r.cohort : r.count) + " rows"];
      if (r.avg !== undefined) parts.push("total " + NUM.format(r.sum) + ", rounded down to a whole number");
      card.append(h("div", { class: "c", text: parts.join(" · ") }));
    }
    card.append(h("div", { class: "row", style: null }, seal("ok", "Proved"),
      h("span", { class: "small muted" }, "over commitment ", h("span", { class: "mono", text: String(bundle.commitment).slice(0, 16) + "…" }))));
    card.lastChild.style.justifyContent = "center"; card.lastChild.style.marginTop = "18px";
    return card;
  }
  function renderAnswer(out, bundle, english) {
    const verify = h("div");
    const again = h("button", { class: "btn small", type: "button", onclick: () => runVerify(bundle, verify, again) }, "Verify again");
    const tamper = h("button", { class: "btn quiet small", type: "button", onclick: () => runTamper(bundle, verify, tamper) }, "Tamper test");
    out.replaceChildren(h("div", {}, answerCard(bundle, english)),
      h("div", { class: "tablet gap" },
        h("div", { class: "tablet-head" }, h("h2", { text: "Verification" }),
          h("div", { class: "row" }, again, tamper,
            h("a", { class: "btn small", href: "/api/bundles/" + encodeURIComponent(bundle.bundle_id) + ".json", download: "" }, "Download proof"))),
        verify));
    out.firstChild.style.marginTop = "18px";
    runVerify(bundle, verify, null);
  }
  async function runVerify(bundle, box, btn) {
    if (btn) btn.disabled = true;
    box.replaceChildren(oracle("Verifying the receipt…"));
    try {
      const r = (await api("POST", "/api/verify", { bundle_id: bundle.bundle_id })).result;
      box.replaceChildren(checks(r));
    } catch (e) { box.replaceChildren(notice("bad", "Verification could not run.", e.message)); }
    finally { if (btn) btn.disabled = false; }
  }
  function checks(r, forgery) {
    const head = forgery ? h("p", { class: "small muted", text: "What the verifier found in the forged bundle:" })
      : h("div", { class: "row" }, r.ok ? seal("ok", "Verified") : seal("bad", "Failed"), h("span", { class: "muted small", text: "checked from the receipt and the manifest, without the data" }));
    return h("div", {}, head,
      h("ul", { class: "checks" }, ...r.checks.map((c) => h("li", {},
        h("span", { class: "mark " + (c.passed ? "ok" : "bad"), "aria-label": c.passed ? "passed" : "failed", text: c.passed ? "✓" : "✕" }),
        h("div", {}, h("div", { text: CHECK[c.name] || c.name }), c.detail ? h("div", { class: "detail", text: c.detail }) : null)))),
      r.note ? h("p", { class: "small muted", text: r.note }) : null,
      forgery ? null : h("p", { class: "small muted", text: "Anyone holding the downloaded proof and the manifest can run this check: tiresias verify." }));
  }
  async function runTamper(bundle, box, btn) {
    btn.disabled = true;
    box.replaceChildren(oracle("Forging the answer and verifying the forgery…"));
    try {
      const t = await api("POST", "/api/tamper", { bundle_id: bundle.bundle_id });
      box.replaceChildren(h("div", {},
        h("div", { class: "row" }, t.result.ok ? seal("bad", "The forgery passed") : seal("ok", "Forgery rejected"),
          h("span", { class: "muted small", text: "The answer was changed from " + NUM.format(t.original) + " to " + NUM.format(t.forged) + " and verified again." })),
        checks(t.result, true)));
    } catch (e) { box.replaceChildren(notice("bad", "The tamper test could not run.", e.message)); }
    finally { btn.disabled = false; }
  }

  // --- Proofs ---------------------------------------------------------------------
  function summary(r) {
    if (r.groups) return Object.keys(r.groups).length + " groups" + ((r.suppressed || []).length ? ", " + r.suppressed.length + " withheld" : "");
    const v = r.avg !== undefined ? r.avg : r.value !== undefined ? r.value : r.sum;
    return NUM.format(v);
  }
  function viewProofs() {
    const page = h("section", {}, h("p", { class: "eyebrow", text: "Proofs" }), h("h1", { text: "Proofs from this session" }),
      h("p", { class: "lede", text: "Each proof is a bundle you can download and hand to anyone: the question, the answer, its cohort, and the receipt that proves them over the commitment. Never a row." }),
      h("div", { class: "meander", "aria-hidden": "true" }));
    if (!state.bundles.length) {
      page.append(h("div", { class: "tablet empty" }, h("h3", { text: "No proofs yet" }), h("p", { text: "Ask a question and its proof appears here." }), h("a", { class: "btn primary", href: "#/ask" }, "Ask a question")));
      return page;
    }
    const detail = h("div");
    const rows = state.bundles.map((b) => {
      const tr = h("tr", { class: "click", tabindex: "0" },
        h("td", {}, h("span", { class: "mono small", text: b.query })),
        h("td", { class: "num", text: summary(b.result) }),
        h("td", { text: (dataset(b.dataset_id) || { name: "?" }).name }),
        h("td", { class: "muted small", text: when(b.created_at) }),
        h("td", {}, seal("ok", "Proved")));
      const open = () => { renderAnswer(detail, b, b.query); detail.scrollIntoView({ behavior: "smooth", block: "start" }); };
      tr.addEventListener("click", open); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      return tr;
    });
    page.append(h("div", { class: "scrollx" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { text: "Question" }), h("th", { class: "num", text: "Answer" }), h("th", { text: "Dataset" }), h("th", { text: "When" }), h("th", { text: "Status" }))),
      h("tbody", {}, ...rows))), detail);
    return page;
  }

  // --- How it works -------------------------------------------------------------------
  function viewAbout() {
    return h("section", {}, h("p", { class: "eyebrow", text: "How it works" }), h("h1", { text: "Answers you can check, data nobody sees" }),
      h("p", { class: "lede", text: "Tiresias, the seer of Thebes, answered truly without seeing. The workbench answers questions about rows it keeps to itself, and attaches a proof that the answer is honest." }),
      h("div", { class: "meander", "aria-hidden": "true" }),
      h("div", { class: "steps" },
        h("div", {}, h("h3", { text: "Commit" }), h("p", { class: "muted", text: "The rows are sealed into a salted SHA-256 commitment and published as a manifest: the schema, the row count and the minimum cohort. No row is in it, and the commitment reveals nothing about them." })),
        h("div", {}, h("h3", { text: "Ask" }), h("p", { class: "muted", text: "A question is proved where the data lives, in the RISC Zero zkVM: a program reads the rows, checks them against the commitment, answers, and refuses any answer about fewer rows than the floor." })),
        h("div", {}, h("h3", { text: "Verify" }), h("p", { class: "muted", text: "Anyone with the proof and the manifest checks the receipt in milliseconds, without the data. A changed answer, query or commitment fails." }))),
      h("div", { class: "meander", "aria-hidden": "true" }),
      h("h2", { text: "What a proof guarantees" }),
      h("div", { class: "tablet gap" },
        h("table", { class: "table" },
          h("thead", {}, h("tr", {}, h("th", { text: "Property" }), h("th", { text: "Rests on" }))),
          h("tbody", {},
            h("tr", {}, h("td", { text: "The answer is the true answer over the committed rows" }), h("td", { text: "the RISC Zero zkVM's soundness (audited by Hexens and Veridise)" })),
            h("tr", {}, h("td", { text: "The proof reveals nothing about the rows beyond the answer" }), h("td", { text: "RISC Zero's zero-knowledge receipts and the salted commitment" })),
            h("tr", {}, h("td", { text: "No answer singles out a few people" }), h("td", { text: "the cohort floor, enforced inside the proof" }))))),
      h("p", { class: "small muted", text: "Tiresias's own guest program and integration have not yet had an independent audit; SECURITY.md says what is and is not covered." }));
  }

  const VIEWS = { datasets: viewDatasets, ask: viewAsk, proofs: viewProofs, about: viewAbout };

  // --- start ------------------------------------------------------------------------
  initTheme();
  window.addEventListener("hashchange", () => { if (route() !== "ask") state.focus = null; render(); document.getElementById("main").focus({ preventScroll: true }); });
  refresh().catch(() => {}).finally(render);
})();
