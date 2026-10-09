/* A shared answer: what was asked, the answer, who attests to it, and the checks the
   registry ran just now. Everything shown comes from the bundle and is set as text. */
"use strict";
(() => {
  const { h, seal, when, notice, answer, checks, NUM } = window.T;
  const main = document.getElementById("main");
  const token = location.pathname.split("/").filter(Boolean).pop() || "";

  function body(j) {
    const b = j.bundle, v = j.verification, r = b.result || {};
    const big = r.groups ? null : h("div", { class: "v", text: answer(r) });
    if (big && big.textContent.length > 9) big.classList.add("sm");
    const groups = r.groups ? h("div", { class: "scrollx gap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { text: r.group_by }), h("th", { class: "num", text: "Total " + r.column }), h("th", { class: "num", text: "Cohort" }))),
      h("tbody", {}, ...Object.entries(r.groups).map(([k, x]) => h("tr", {}, h("td", { text: k }), h("td", { class: "num", text: NUM.format(x) }), h("td", { class: "num muted", text: NUM.format((r.cohorts || {})[k] || 0) + " rows" }))),
        ...(r.suppressed || []).map((s) => h("tr", {}, h("td", { text: s }), h("td", { class: "num muted", text: "withheld" }), h("td", { class: "num faint", text: "too few rows" })))))) : null;
    const cohort = r.groups ? null : (r.cohort !== undefined ? r.cohort : r.count);
    return h("section", { class: "certificate" },
      h("p", { class: "eyebrow", text: "A verified answer" }),
      h("div", { class: "tablet answer" },
        h("div", { class: "q mono", text: b.query }),
        big, groups,
        cohort !== undefined && cohort !== null ? h("div", { class: "c", text: "over " + NUM.format(cohort) + " rows" }) : null,
        h("div", { class: "row gap seal-row" }, v.ok ? seal("ok", "Proved over the published commitment") : seal("bad", "Does not verify against the published commitment"))),
      h("div", { class: "tablet gap" },
        h("h2", { text: "Who attests to it" }),
        h("dl", { class: "kv gap" },
          h("dt", { text: "Organization" }), h("dd", { text: j.org || "unknown" }),
          h("dt", { text: "Dataset" }), h("dd", { text: j.dataset ? (j.dataset.name || j.dataset.dataset_id) : "unknown" }),
          h("dt", { text: "Commitment" }), h("dd", { class: "mono", text: String(b.commitment) }),
          b.created_at ? h("dt", { text: "Proved" }) : null, b.created_at ? h("dd", { text: when(b.created_at) }) : null)),
      h("div", { class: "tablet gap" },
        h("h2", { text: "The checks, run just now" }),
        h("p", { class: "muted small", text: "The registry verified this answer's RISC Zero receipt against the commitment the organization published, without the data." }),
        checks(v),
        h("p", { class: "muted small" }, "Check it yourself: ",
          h("a", { href: "/share/" + encodeURIComponent(token), download: "tiresias-proof.json", text: "download the proof and manifest" }),
          ", then run tiresias verify.")),
      h("div", { class: "notice gap" }, h("b", { text: "What this does and does not show." }),
        "The receipt proves this is the true answer over the rows the organization committed to, and that it describes at least the dataset's minimum number of rows. It reveals nothing else about them. Proofs come from the RISC Zero zkVM; Tiresias's own guest program has not yet had an independent audit."));
  }

  (async () => {
    try {
      const r = await fetch("/share/" + encodeURIComponent(token));
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { main.replaceChildren(h("section", { class: "certificate" }, notice("bad", "This link does not open an answer.", j.error || "It may have been revoked."))); return; }
      main.replaceChildren(body(j));
      document.title = "A verified answer · Tiresias";
    } catch (e) {
      main.replaceChildren(h("section", { class: "certificate" }, notice("bad", "The answer could not be loaded.", e.message)));
    }
  })();
})();
