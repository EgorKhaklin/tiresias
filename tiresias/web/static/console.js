/* The registry console: an organization's datasets, proofs, activity and keys.
   The API key lives in sessionStorage only, so it is gone when the tab closes. */
"use strict";
(() => {
  const { h, toast, copyable, seal, when, notice, answer, checks, NUM } = window.T;
  const main = document.getElementById("main");
  let key = "";
  try { key = sessionStorage.getItem("tiresias-key") || ""; } catch { /* storage blocked */ }

  async function api(path, method, body) {
    const r = await fetch(path, { method: method || "GET", headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    let j = {};
    try { j = await r.json(); } catch { /* not JSON */ }
    if (!r.ok) throw new Error(j.error || "The request failed (" + r.status + ")");
    return j;
  }

  function signIn(error) {
    const input = h("input", { type: "password", autocomplete: "off", spellcheck: "false", placeholder: "tk_…", "aria-label": "API key" });
    const err = h("div", {}, error ? notice("bad", "Could not connect.", error) : null);
    const go = h("button", { class: "btn primary", type: "submit" }, "Connect");
    const form = h("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault();
      key = input.value.trim();
      if (!key) return;
      go.disabled = true; go.textContent = "Connecting…";
      try { await load(); try { sessionStorage.setItem("tiresias-key", key); } catch { /* ignore */ } }
      catch (x) { key = ""; signIn(x.message); }
    } }, h("label", { class: "field" }, h("span", { text: "API key" }), input,
      h("small", { text: "Your organization's key. It is kept for this tab only and sent only to this registry." })), err, h("div", { class: "row" }, go));
    main.replaceChildren(h("section", {},
      h("p", { class: "eyebrow", text: "Console" }), h("h1", { text: "Your organization's proofs" }),
      h("p", { class: "lede", text: "Datasets your organization has committed, the proofs published against them, and who can see each one." }),
      h("div", { class: "meander", "aria-hidden": "true" }),
      h("div", { class: "tablet", style: null }, form)));
    input.focus();
  }

  async function load() {
    const [who, stats, ms, bs, audit, keys] = await Promise.all([
      api("/api/whoami"), api("/api/stats"), api("/api/manifests"), api("/api/bundles"), api("/api/audit"), api("/api/keys")]);
    const names = Object.fromEntries(ms.manifests.map((m) => [m.dataset_id, m.name || m.dataset_id]));
    const out = h("section", {},
      h("div", { class: "row" }, h("div", {}, h("p", { class: "eyebrow", text: "Console" }), h("h1", { text: who.org_name })),
        h("span", { class: "spacer" }),
        h("button", { class: "btn small", type: "button", onclick: () => load().catch((e) => toast(e.message)) }, "Refresh"),
        h("button", { class: "btn quiet small", type: "button", onclick: () => { key = ""; try { sessionStorage.removeItem("tiresias-key"); } catch { /* ignore */ } signIn(); } }, "Disconnect")),
      h("div", { class: "tiles gap" },
        tile(stats.datasets, "datasets committed"), tile(stats.bundles, "proofs published"), tile(stats.verified_bundles, "bound to their commitment")),
      h("div", { class: "meander", "aria-hidden": "true" }),
      section("Datasets", ms.manifests.length ? datasets(ms.manifests) : empty("No datasets yet", "Commit one from the data holder's machine:", "tiresias remote-commit data.csv")),
      section("Proofs", bs.bundles.length ? proofs(bs.bundles, names) : empty("No proofs yet", "Prove an answer against a committed dataset:", 'tiresias remote-query <dataset> "SELECT COUNT(*)" --data data.csv')),
      section("Activity", audit.audit.length ? activity(audit.audit) : empty("No activity yet", "", "")),
      section("API keys", keysTable(keys.keys)));
    main.replaceChildren(out);
  }
  const tile = (n, label) => h("div", { class: "tile" }, h("div", { class: "n", text: NUM.format(n || 0) }), h("div", { class: "l", text: label }));
  const section = (title, body) => h("div", { class: "gap" }, h("h2", { text: title }), h("div", { class: "gap" }, body));
  const empty = (title, line, cmd) => h("div", { class: "tablet empty" }, h("h3", { text: title }), line ? h("p", { text: line }) : null, cmd ? h("div", { class: "code", text: cmd }) : null);

  function datasets(list) {
    return h("div", { class: "scrollx" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { text: "Name" }), h("th", { class: "num", text: "Rows" }), h("th", { class: "num", text: "Floor" }), h("th", { text: "Commitment" }), h("th", { text: "Dataset id" }))),
      h("tbody", {}, ...list.map((m) => h("tr", {},
        h("td", { text: m.name || "untitled" }), h("td", { class: "num", text: NUM.format(m.row_count || 0) }), h("td", { class: "num", text: String(m.min_cohort || "") }),
        h("td", {}, copyable(m.commitment, "Commitment")), h("td", {}, copyable(m.dataset_id, "Dataset id")))))));
  }

  function proofs(list, names) {
    return h("div", { class: "stack" }, ...list.map((b) => {
      const panel = h("div");
      const verify = h("button", { class: "btn small", type: "button", onclick: async () => {
        verify.disabled = true; panel.replaceChildren(h("p", { class: "muted small", text: "Verifying the receipt…" }));
        try {
          const v = (await api("/api/bundles/" + encodeURIComponent(b.bundle_id) + "/verify", "POST")).verification;
          panel.replaceChildren(h("div", { class: "row gap" }, v.ok ? seal("ok", "Verified") : seal("bad", "Does not verify"), h("span", { class: "muted small", text: "checked just now, without the data" })), checks(v));
        } catch (e) { panel.replaceChildren(notice("bad", "Verification could not run.", e.message)); }
        finally { verify.disabled = false; }
      } }, "Verify");
      const share = h("button", { class: "btn small", type: "button", onclick: async () => {
        share.disabled = true;
        try {
          const r = await api("/api/bundles/" + encodeURIComponent(b.bundle_id) + "/share", "POST");
          const url = location.origin + r.view_path;
          panel.replaceChildren(h("div", { class: "gap" }, h("p", { class: "small muted", text: "Anyone with this link can see the answer, its checks, and download the proof to verify it themselves. It shows no rows." }),
            h("div", { class: "share" }, h("input", { type: "text", readonly: true, value: url, "aria-label": "Share link", onfocus: (e) => e.target.select() }),
              h("button", { class: "btn small", type: "button", onclick: async () => { try { await navigator.clipboard.writeText(url); toast("Link copied"); } catch { toast("Copy failed"); } } }, "Copy"),
              h("a", { class: "btn small", href: url, target: "_blank", rel: "noopener" }, "Open"))));
          toast("Share link created");
        } catch (e) { panel.replaceChildren(notice("bad", "The link could not be created.", e.message)); }
        finally { share.disabled = false; }
      } }, "Share");
      return h("div", { class: "tablet" },
        h("div", { class: "row" }, h("span", { class: "mono small", text: b.query }), h("span", { class: "spacer" }),
          b._verified ? seal("ok", "Verified") : seal("bad", "Does not verify")),
        h("div", { class: "row gap" },
          h("div", {}, h("div", { class: "answer-inline", text: answer(b.result) }),
            h("div", { class: "small muted", text: (names[b.dataset_id] || b.dataset_id) + (b.created_at ? " · " + when(b.created_at) : "") })),
          h("span", { class: "spacer" }), verify, share),
        panel);
    }));
  }

  function activity(list) {
    return h("div", { class: "scrollx" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { text: "When" }), h("th", { text: "Action" }), h("th", { text: "Detail" }))),
      h("tbody", {}, ...list.slice(0, 50).map((a) => h("tr", {}, h("td", { class: "muted small", text: when(a.ts) }), h("td", { class: "mono small", text: a.action }), h("td", { class: "muted small", text: a.detail || "" }))))));
  }

  function keysTable(list) {
    return h("div", { class: "scrollx" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { text: "Key" }), h("th", { text: "Label" }), h("th", { text: "Created" }), h("th", { text: "Status" }), h("th", { text: "" }))),
      h("tbody", {}, ...list.map((k) => h("tr", {},
        h("td", { class: "mono small", text: k.key_id }), h("td", { text: k.label || "" }), h("td", { class: "muted small", text: k.created_at ? when(k.created_at) : "" }),
        h("td", {}, k.revoked ? seal("idle", "Revoked") : seal("ok", "Active")),
        h("td", { class: "num" }, k.revoked ? null : h("button", { class: "btn quiet small", type: "button", onclick: async (e) => {
          if (!confirm("Revoke key " + k.key_id + "? Anything using it stops working.")) return;
          e.target.disabled = true;
          try { await api("/api/keys/" + encodeURIComponent(k.key_id), "DELETE"); toast("Key revoked"); await load(); }
          catch (x) { toast(x.message); e.target.disabled = false; }
        } }, "Revoke")))))));
  }

  if (key) load().catch((e) => { key = ""; signIn(e.message); }); else signIn();
})();
