/* SentinelPay shared shell: header, footer, toasts, modals, formatting, polling. */
(function () {
  const SP = (window.SP = {});
  const LS = {
    get(k, d) { try { const v = localStorage.getItem("sp." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("sp." + k, JSON.stringify(v)); } catch (e) {} },
  };
  SP.store = LS;
  SP.status = null;

  // ------------------------------------------------------------------ formatting
  SP.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  SP.inr = (n) => "₹" + Math.round(Number(n) || 0).toLocaleString("en-IN");
  SP.lakh = (n) => {
    n = Number(n) || 0;
    if (n >= 1e7) return "₹" + (n / 1e7).toFixed(2) + " Cr";
    if (n >= 1e5) return "₹" + (n / 1e5).toFixed(1) + " Lakh";
    return SP.inr(n);
  };
  SP.dur = (s) => {
    if (s === null || s === undefined) return "—";
    s = Math.max(0, Math.round(s));
    if (s < 60) return s + "s";
    const m = Math.floor(s / 60), r = s % 60;
    if (m < 60) return m + "m " + String(r).padStart(2, "0") + "s";
    return Math.floor(m / 60) + "h " + String(m % 60).padStart(2, "0") + "m";
  };
  SP.mss = (s) => (s === null || s === undefined) ? "—" : Math.floor(s / 60) + ":" + String(Math.round(s % 60)).padStart(2, "0");
  SP.clock = (sec) => {
    const neg = sec < 0; sec = Math.abs(Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (neg ? "-" : "") + [h, m, s].map((x) => String(x).padStart(2, "0")).join(":");
  };
  SP.ms = (v) => (v === null || v === undefined) ? "—" : (v >= 1000 ? (v / 1000).toFixed(2) + " s" : v + " ms");
  SP.date = (ts) => (ts ? new Date(ts) : null);
  SP.ist = (ts, withDate) => {
    if (!ts) return "—";
    const d = new Date(ts);
    const t = d.toLocaleTimeString("en-IN", { hour12: false, timeZone: "Asia/Kolkata" });
    return withDate ? d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "Asia/Kolkata" }) + " " + t : t;
  };
  SP.ago = (ts) => {
    if (!ts) return "never";
    const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000);
    if (s < 5) return "just now";
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  };
  SP.stepLabel = (s) => ({ login: "Login", open_transfer: "Open transfer form", submit_transfer: "Submit transfer",
    gateway_pay: "Gateway payment", verify_receipt: "Verify receipt", "real transactions": "Real customer transactions" }[s] || s);
  SP.layerIcon = (l) => ({ gateway: "hub", server: "dns", receiver_bank: "account_balance", customer_network: "wifi" }[l] || "layers");
  SP.sevPill = (sev) => {
    const m = { critical: "bg-error text-on-error", major: "bg-error-container/60 text-error", warning: "bg-warn/20 text-warn" };
    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-label-sm font-semibold uppercase ${m[sev] || "bg-surface-container-high text-on-surface-variant"}">${SP.esc(sev)}</span>`;
  };
  SP.statusPill = (st) => {
    const m = { open: "bg-error/15 text-error", recovering: "bg-primary/15 text-primary", resolved: "bg-secondary-container/20 text-secondary" };
    const ic = { open: "radar", recovering: "autorenew", resolved: "task_alt" }[st] || "info";
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-label-sm font-semibold uppercase ${m[st] || ""}"><span class="material-symbols-outlined text-[12px] ${st === "recovering" ? "sp-spin" : ""}">${ic}</span>${SP.esc(st)}</span>`;
  };
  SP.operator = () => LS.get("operator", "Ops Manager");
  // Re-render only when data changed, so buttons are not replaced under the user's cursor.
  const _last = {};
  SP.changed = (key, obj) => { const j = JSON.stringify(obj); if (_last[key] === j) return false; _last[key] = j; return true; };

  // ------------------------------------------------------------------ http
  SP.api = async (path, opts = {}) => {
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
    const r = await fetch(path, init);
    const ct = r.headers.get("content-type") || "";
    const data = ct.includes("json") ? await r.json() : await r.text();
    if (!r.ok) {
      const msg = (data && (data.message || data.detail)) || ("HTTP " + r.status);
      const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = r.status; throw err;
    }
    return data;
  };
  SP.post = (path, body) => SP.api(path, { method: "POST", body: body || {} });

  // ------------------------------------------------------------------ toasts
  function toastHost() {
    let h = document.getElementById("sp-toasts");
    if (!h) {
      h = document.createElement("div");
      h.id = "sp-toasts";
      h.className = "fixed right-4 bottom-12 z-[70] flex flex-col gap-2 w-[340px] max-w-[calc(100vw-2rem)]";
      document.body.appendChild(h);
    }
    return h;
  }
  SP.toast = (title, msg, kind = "info", sub = "") => {
    const colors = { info: "border-primary", crit: "border-error", ok: "border-secondary", warn: "border-warn" };
    const icons = { info: "info", crit: "crisis_alert", ok: "task_alt", warn: "warning" };
    const tc = { info: "text-primary", crit: "text-error", ok: "text-secondary", warn: "text-warn" };
    const el = document.createElement("div");
    el.className = `sp-toast bg-surface-container-high/95 backdrop-blur border-l-2 ${colors[kind] || colors.info} rounded-lg shadow-[0_8px_32px_-4px_rgba(0,0,0,0.6)] p-3 flex gap-2`;
    el.innerHTML = `<span class="material-symbols-outlined text-[18px] ${tc[kind] || tc.info}">${icons[kind] || "info"}</span>
      <div class="min-w-0 flex-1"><div class="text-body-sm font-semibold text-on-surface">${SP.esc(title)}</div>
      <div class="text-body-sm text-on-surface-variant mt-0.5 break-words">${SP.esc(msg)}</div>
      ${sub ? `<div class="text-[10px] font-mono text-outline mt-1">${SP.esc(sub)}</div>` : ""}</div>
      <button class="text-outline hover:text-on-surface self-start" aria-label="Close"><span class="material-symbols-outlined text-[16px]">close</span></button>`;
    el.querySelector("button").onclick = () => el.remove();
    toastHost().appendChild(el);
    setTimeout(() => el.remove(), 7000);
  };

  // ------------------------------------------------------------------ modal
  SP.modal = ({ title, body, actions = [], wide = false, icon = "info", iconClass = "text-primary" }) => new Promise((resolve) => {
    const wrap = document.createElement("div");
    wrap.className = "fixed inset-0 z-[80] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 sp-fade";
    wrap.innerHTML = `<div class="bg-surface-container w-full ${wide ? "max-w-4xl" : "max-w-lg"} rounded-xl shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05),0_8px_32px_-4px_rgba(0,0,0,0.6)] max-h-[88vh] flex flex-col">
      <div class="flex items-center justify-between px-5 py-3 border-b border-surface-variant">
        <div class="flex items-center gap-2"><span class="material-symbols-outlined ${iconClass}">${icon}</span><span class="font-headline-sm text-headline-sm text-on-surface">${SP.esc(title)}</span></div>
        <button data-x class="text-outline hover:text-on-surface" aria-label="Close"><span class="material-symbols-outlined">close</span></button></div>
      <div class="px-5 py-4 overflow-auto text-body-md text-on-surface-variant" data-body></div>
      <div class="px-5 py-3 border-t border-surface-variant flex justify-end gap-2" data-actions></div></div>`;
    const b = wrap.querySelector("[data-body]");
    if (typeof body === "string") b.innerHTML = body; else if (body) b.appendChild(body);
    const close = (v) => { wrap.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(null); });
    wrap.querySelector("[data-x]").onclick = () => close(null);
    const acts = wrap.querySelector("[data-actions]");
    if (!actions.length) actions = [{ label: "Close", value: null }];
    actions.forEach((a) => {
      const btn = document.createElement("button");
      btn.className = a.primary
        ? "px-4 py-2 rounded-lg bg-primary-container hover:bg-primary text-on-primary-container font-semibold text-body-md shadow-[0_0_12px_rgba(6,182,212,0.35)]"
        : a.danger ? "px-4 py-2 rounded-lg bg-error/10 border border-error text-error hover:bg-error hover:text-on-error text-body-md"
        : "px-4 py-2 rounded-lg bg-surface-container-high hover:bg-surface-variant text-on-surface text-body-md";
      btn.innerHTML = (a.icon ? `<span class="material-symbols-outlined text-[16px] align-middle mr-1">${a.icon}</span>` : "") + SP.esc(a.label);
      btn.onclick = () => close(a.value === undefined ? true : a.value);
      acts.appendChild(btn);
    });
    document.body.appendChild(wrap);
  });
  SP.confirm = (title, html, okLabel = "Confirm", opts = {}) =>
    SP.modal({ title, body: html, icon: opts.icon || "verified_user", iconClass: opts.iconClass || "text-warn",
      actions: [{ label: "Cancel", value: false }, { label: okLabel, value: true, primary: true, icon: opts.okIcon }] });

  SP.mdToHtml = (md) => {
    const lines = SP.esc(md).split("\n"); let html = "", inList = false;
    const inline = (t) => t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/_(.+?)_/g, "<em>$1</em>");
    for (const raw of lines) {
      const l = raw.replace(/\s+$/, "");
      if (l.startsWith("- ")) { if (!inList) { html += "<ul>"; inList = true; } html += "<li>" + inline(l.slice(2)) + "</li>"; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      if (l.startsWith("# ")) html += "<h1>" + inline(l.slice(2)) + "</h1>";
      else if (l.startsWith("## ")) html += "<h2>" + inline(l.slice(3)) + "</h2>";
      else if (l === "---") html += "<hr>";
      else if (l.trim()) html += "<p>" + inline(l) + "</p>";
    }
    return html + (inList ? "</ul>" : "");
  };
  SP.download = (url) => { const a = document.createElement("a"); a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); };
  SP.showReport = async (id) => {
    try {
      const md = await SP.api(`/api/incidents/${id}/report`);
      const r = await SP.modal({ title: `Incident #${id} – report`, icon: "description", wide: true,
        body: `<div class="md-view">${SP.mdToHtml(md)}</div>`,
        actions: [{ label: "Close", value: null }, { label: "Download .md", value: "dl", primary: true, icon: "download" }] });
      if (r === "dl") SP.download(`/api/incidents/${id}/report?download=1`);
    } catch (e) { SP.toast("Report unavailable", e.message, "crit"); }
  };
  SP.showImage = (src, title) => SP.modal({ title: title || "Evidence screenshot", icon: "image", wide: true,
    body: `<img src="${SP.esc(src)}" class="w-full rounded-lg border border-surface-variant" alt="Probe failure screenshot">`,
    actions: [{ label: "Close", value: null }] }).then((v) => v);

  // ------------------------------------------------------------------ header / footer
  const NAV = [
    { path: "/", label: "Overview & Journeys", icon: "monitor_heart" },
    { path: "/incidents", label: "Active Incidents", icon: "crisis_alert", id: "nav-incidents" },
    { path: "/chaos", label: "Chaos Control Deck", icon: "pest_control" },
    { path: "/tests", label: "Auto-Generated Tests", icon: "smart_toy" },
    { path: "/watchdog", label: "RBI Watchdog", icon: "gavel" },
  ];
  function activePath() { const p = location.pathname; return p === "/incident" ? "/incidents" : p; }

  function renderHeader() {
    const host = document.getElementById("sp-header");
    if (!host) return;
    const act = activePath();
    const link = (n, mobile) => {
      const on = n.path === act;
      const cls = on ? "bg-primary-container text-on-primary-container rounded-lg font-medium shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                     : "rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface";
      return `<a ${on ? 'aria-current="page"' : ""} ${n.id ? `data-nav="${n.id}"` : ""} class="${mobile ? "flex items-center gap-2 px-3 py-2" : "px-space-md py-1.5 whitespace-nowrap"} ${cls} font-body-sm text-body-sm transition-all" href="${n.path}">${mobile ? `<span class="material-symbols-outlined text-[18px]">${n.icon}</span>` : ""}<span data-label>${n.label}</span></a>`;
    };
    host.innerHTML = `<header class="fixed top-0 w-full z-50 bg-surface-container-lowest/95 backdrop-blur-md shadow-[0_1px_8px_rgba(0,0,0,0.5)]">
      <div class="h-16 w-full px-space-lg flex items-center justify-between gap-space-md">
        <div class="flex items-center gap-space-md shrink-0">
          <button id="sp-menu" class="lg:hidden w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center text-on-surface-variant" aria-label="Menu"><span class="material-symbols-outlined text-[18px]">menu</span></button>
          <a href="/" class="flex items-center gap-space-sm">
            <span class="w-8 h-8 rounded-lg bg-primary-container/20 flex items-center justify-center text-primary shadow-[0_0_12px_rgba(6,182,212,0.25)]"><span class="material-symbols-outlined icon-fill text-[20px]">shield</span></span>
            <span class="font-headline-sm text-headline-sm text-on-surface tracking-tight uppercase">SentinelPay</span>
            <span class="hidden sm:inline font-label-sm text-label-sm text-primary tracking-widest uppercase bg-surface-container-high px-space-xs py-0.5 rounded">CORE-NOC</span>
          </a>
          <div class="h-5 w-px bg-surface-container-high mx-space-xs hidden 2xl:block"></div>
          <div class="hidden 2xl:flex items-center gap-space-xs">
            <div class="flex items-center gap-1.5 px-space-xs py-0.5 rounded-full bg-secondary-container/20"><span id="sp-live-dot" class="w-2 h-2 rounded-full bg-secondary animate-pulse"></span><span class="font-label-sm text-label-sm text-secondary font-medium tracking-wide uppercase">Live</span></div>
            <span id="sp-updated" class="font-label-sm text-label-sm text-on-surface-variant font-mono">Connecting…</span>
          </div>
        </div>
        <nav class="hidden lg:flex items-center gap-space-xs">${NAV.map((n) => link(n)).join("")}</nav>
        <div class="flex items-center gap-space-md shrink-0">
          <div class="hidden 2xl:flex flex-col items-end">
            <span id="sp-env" class="font-label-sm text-label-sm text-secondary tracking-wide uppercase flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-secondary"></span>Mock bank · 8001</span>
            <span id="sp-env-sub" class="font-label-sm text-label-sm text-on-surface-variant">—</span>
          </div>
          <div class="flex items-center gap-space-xs relative">
            <button id="sp-crit" class="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center text-on-surface-variant hover:bg-surface-container transition-colors relative" title="Open incidents"><span class="material-symbols-outlined text-[18px]">warning</span><span id="sp-crit-ping" class="hidden absolute top-1 right-1 w-2 h-2 rounded-full bg-error animate-ping"></span></button>
            <button id="sp-bell" class="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors relative" title="Alerts"><span class="material-symbols-outlined text-[18px]">notifications</span><span id="sp-bell-badge" class="hidden absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-error text-on-error text-[10px] font-mono leading-4 text-center">0</span></button>
            <div id="sp-bell-panel" class="hidden absolute right-0 top-10 w-[360px] max-w-[calc(100vw-2rem)] bg-surface-container rounded-xl shadow-[0_8px_32px_-4px_rgba(0,0,0,0.6)] z-[60]">
              <div class="flex items-center justify-between px-3 py-2 border-b border-surface-variant"><span class="font-label-md text-label-md text-on-surface uppercase tracking-wider">Alert feed</span><span id="sp-bell-channel" class="font-label-sm text-label-sm text-outline"></span></div>
              <div id="sp-bell-list" class="max-h-[360px] overflow-auto divide-y divide-surface-variant/50"></div>
            </div>
          </div>
          <div class="relative">
            <button id="sp-user" class="flex items-center gap-space-xs pl-space-xs" title="Operator">
              <span class="w-8 h-8 rounded-full bg-primary flex items-center justify-center"><span class="material-symbols-outlined text-on-primary text-[18px]">person</span></span>
              <span class="hidden 2xl:flex flex-col text-left"><span id="sp-user-name" class="font-label-sm text-label-sm text-on-surface font-medium leading-none"></span><span class="font-label-sm text-on-surface-variant text-[10px] leading-tight">Approver</span></span>
            </button>
            <div id="sp-user-panel" class="hidden absolute right-0 top-10 w-72 bg-surface-container rounded-xl shadow-[0_8px_32px_-4px_rgba(0,0,0,0.6)] z-[60] p-3">
              <label class="block font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">Approver name (recorded on approvals)</label>
              <input id="sp-user-input" class="mt-1 w-full bg-surface-container-lowest border border-surface-variant rounded px-2 py-1.5 text-body-md text-on-surface focus:outline-none focus:border-primary-container">
              <button id="sp-user-save" class="mt-2 w-full py-1.5 rounded-lg bg-primary-container text-on-primary-container font-semibold text-body-sm">Save</button>
              <div class="mt-3 pt-3 border-t border-surface-variant flex flex-col gap-1 text-body-sm">
                <a class="flex items-center gap-2 text-on-surface-variant hover:text-primary" target="_blank" rel="noopener" data-bank-link="/"><span class="material-symbols-outlined text-[16px]">account_balance</span>Open mock bank (demo / demo123)</a>
                <a class="flex items-center gap-2 text-on-surface-variant hover:text-primary" target="_blank" rel="noopener" href="/docs"><span class="material-symbols-outlined text-[16px]">api</span>Monitor API docs</a>
              </div>
            </div>
          </div>
        </div>
      </div>
      <nav id="sp-mobile-nav" class="hidden lg:hidden px-space-lg pb-3 flex-col gap-1">${NAV.map((n) => link(n, true)).join("")}</nav>
    </header>`;
    const bankBase = `${location.protocol}//${location.hostname}:8001`;
    host.querySelectorAll("[data-bank-link]").forEach((a) => (a.href = bankBase + a.dataset.bankLink));
    const toggle = (id) => { ["sp-bell-panel", "sp-user-panel"].forEach((p) => { const el = document.getElementById(p); if (p === id) el.classList.toggle("hidden"); else el.classList.add("hidden"); }); };
    document.getElementById("sp-menu").onclick = () => { const m = document.getElementById("sp-mobile-nav"); m.classList.toggle("hidden"); m.classList.toggle("flex"); };
    document.getElementById("sp-bell").onclick = (e) => { e.stopPropagation(); toggle("sp-bell-panel"); unread = 0; paintBadge(); loadBell(); };
    document.getElementById("sp-user").onclick = (e) => { e.stopPropagation(); toggle("sp-user-panel"); document.getElementById("sp-user-input").value = SP.operator(); };
    document.getElementById("sp-bell-panel").onclick = (e) => e.stopPropagation();
    document.getElementById("sp-user-panel").onclick = (e) => e.stopPropagation();
    document.addEventListener("click", () => toggle(null));
    document.getElementById("sp-user-save").onclick = () => {
      const v = document.getElementById("sp-user-input").value.trim() || "Ops Manager";
      LS.set("operator", v); paintUser(); toggle(null); SP.toast("Approver updated", `Approvals will be recorded as "${v}"`, "ok");
    };
    document.getElementById("sp-crit").onclick = () => {
      const top = SP.status && SP.status.top_incident;
      if (top) location.href = "/incident?id=" + top.id; else { location.href = "/incidents"; }
    };
    paintUser();
  }
  function paintUser() { const el = document.getElementById("sp-user-name"); if (el) el.textContent = SP.operator(); }

  function renderFooter() {
    const host = document.getElementById("sp-footer");
    if (!host) return;
    host.innerHTML = `<footer class="fixed bottom-0 left-0 w-full z-40 bg-surface-container-lowest/90 backdrop-blur-md shadow-[0_-1px_6px_rgba(0,0,0,0.4)]">
      <div class="h-8 w-full px-space-lg flex items-center justify-between text-on-surface-variant font-label-sm text-label-sm gap-3">
        <div class="flex items-center gap-space-md min-w-0">
          <div class="flex items-center gap-1.5 text-secondary"><span id="sp-f-dot" class="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse"></span><span id="sp-f-uptime">PROBE PASS RATE (1H): —</span></div>
          <span class="text-outline-variant hidden sm:inline">|</span>
          <div class="hidden sm:flex items-center gap-1.5"><span>PROBE HEARTBEAT:</span><span id="sp-f-hb" class="text-primary font-mono">—</span></div>
          <span class="text-outline-variant hidden md:inline">|</span>
          <div class="hidden md:flex items-center gap-1.5"><span>CUSTOMER TRAFFIC:</span><span id="sp-f-tps" class="text-on-surface font-mono">—</span></div>
        </div>
        <div class="flex items-center gap-space-md">
          <a href="/watchdog" class="hidden md:flex items-center gap-1 hover:text-on-surface"><span class="material-symbols-outlined text-[14px] text-secondary">shield</span><span id="sp-f-rbi">RBI WATCHDOG: —</span></a>
          <span id="sp-f-clock" class="font-mono">--:--:-- IST</span>
        </div>
      </div></footer>`;
    setInterval(() => { const c = document.getElementById("sp-f-clock"); if (c) c.textContent = SP.ist(new Date().toISOString()) + " IST"; }, 1000);
  }

  function paintShell(s) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.innerHTML = v; };
    const p = s.probe, k = s.kpis;
    set("sp-updated", p.running ? "Probe running…" : `Probe ${SP.ago(p.last_cycle_at)} · next in ${p.next_cycle_in ?? "—"}s`);
    const hbPct = p.heartbeat_total ? (100 * p.heartbeat_ok / p.heartbeat_total).toFixed(2) : "—";
    set("sp-f-uptime", `PROBE PASS RATE (1H): ${hbPct}%`);
    set("sp-f-hb", `${s.bank_reachable ? "STABLE" : "BANK UNREACHABLE"} (${(p.heartbeat_ok || 0).toLocaleString("en-IN")}/${(p.heartbeat_total || 0).toLocaleString("en-IN")} OK)`);
    set("sp-f-tps", `${s.traffic.tps} TPS · ${s.traffic.success_rate ?? "—"}% success`);
    set("sp-f-rbi", `RBI WATCHDOG: ${k.pending_reversals} PENDING · ${SP.lakh(k.pending_reversal_value)}`);
    const env = document.getElementById("sp-env");
    if (env) {
      env.className = `font-label-sm text-label-sm tracking-wide uppercase flex items-center gap-1 ${s.bank_reachable ? "text-secondary" : "text-error"}`;
      env.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${s.bank_reachable ? "bg-secondary" : "bg-error animate-ping"}"></span>${s.bank_reachable ? "Mock bank online" : "Mock bank offline"} · chaos: ${SP.esc((s.chaos && s.chaos.mode) || "?")}`;
    }
    set("sp-env-sub", `Slack ${s.config.slack ? "on" : "off"} · AI RCA ${s.config.gemini ? "Gemini" : "rule-based"}`);
    const crit = document.getElementById("sp-crit");
    if (crit) {
      crit.className = `w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center ${k.open_incidents ? "text-error" : "text-on-surface-variant"} hover:bg-surface-container transition-colors relative`;
      crit.title = k.open_incidents ? `${k.open_incidents} open incident(s) – open the most recent` : "No open incidents";
      document.getElementById("sp-crit-ping").classList.toggle("hidden", !k.critical_open);
    }
    document.querySelectorAll('[data-nav="nav-incidents"] [data-label]').forEach((el) => {
      el.textContent = k.open_incidents ? `Active Incidents (${k.critical_open ? k.critical_open + " Critical" : k.open_incidents + " Open"})` : "Active Incidents";
    });
    const dot = document.getElementById("sp-live-dot");
    if (dot) dot.className = `w-2 h-2 rounded-full ${s.bank_reachable ? "bg-secondary" : "bg-error"} animate-pulse`;
  }

  // ------------------------------------------------------------------ alerts → toasts + bell
  let lastAlert = null, unread = 0;
  const alertKind = (k) => ({ incident: "crit", resolved: "ok", approved: "ok", pattern: "warn", test_created: "info", watchdog: "warn", notice: "info", fix_failed: "crit" }[k] || "info");
  function paintBadge() {
    const b = document.getElementById("sp-bell-badge");
    if (!b) return; b.textContent = unread > 99 ? "99+" : unread; b.classList.toggle("hidden", !unread);
  }
  async function loadBell() {
    const list = document.getElementById("sp-bell-list");
    if (!list) return;
    try {
      const rows = await SP.api("/api/alerts?limit=30");
      document.getElementById("sp-bell-channel").textContent = SP.status && SP.status.config.slack ? "Slack + in-app" : "In-app (Slack not configured)";
      list.innerHTML = rows.length ? rows.map((a) => `<a ${a.incident_id ? `href="/incident?id=${a.incident_id}"` : ""} class="block px-3 py-2 hover:bg-surface-container-high ${a.incident_id ? "cursor-pointer" : ""}">
        <div class="flex items-center justify-between gap-2"><span class="text-body-sm font-semibold text-on-surface truncate">${SP.esc(a.title || a.kind)}</span><span class="text-[10px] font-mono text-outline shrink-0">${SP.ago(a.ts)}</span></div>
        <div class="text-body-sm text-on-surface-variant line-clamp-2">${SP.esc(a.message)}</div></a>`).join("")
        : `<div class="px-3 py-6 text-center text-body-sm text-outline">No alerts yet</div>`;
    } catch (e) { list.innerHTML = `<div class="px-3 py-4 text-body-sm text-error">${SP.esc(e.message)}</div>`; }
  }
  async function pollAlerts() {
    try {
      if (lastAlert === null) {
        const rows = await SP.api("/api/alerts?limit=1");
        lastAlert = rows.length ? rows[0].id : 0;
        return;
      }
      const rows = await SP.api(`/api/alerts?since=${lastAlert}`);
      for (const a of rows) {
        lastAlert = Math.max(lastAlert, a.id); unread++;
        const sub = a.channel === "slack" ? "Slack alert sent" : "Alert logged (Slack not configured)";
        SP.toast(a.title || a.kind, a.message, alertKind(a.kind), sub);
      }
      paintBadge();
      if (rows.length) document.dispatchEvent(new CustomEvent("sp:alerts", { detail: rows }));
    } catch (e) { /* monitor restarting */ }
  }

  // ------------------------------------------------------------------ polling
  SP.autoSync = () => LS.get("autosync", true);
  SP.setAutoSync = (v) => { LS.set("autosync", !!v); document.dispatchEvent(new CustomEvent("sp:autosync", { detail: !!v })); };
  const pollers = [];
  SP.poll = (fn, ms = 3000) => {
    const p = { fn, ms, t: null, busy: false };
    const run = async (force) => {
      if (p.busy) return;
      if (!force && !SP.autoSync()) return;
      p.busy = true;
      try { await fn(); } catch (e) { console.warn(e); } finally { p.busy = false; }
    };
    p.run = run;
    pollers.push(p);
    run(true);
    p.t = setInterval(() => run(false), ms);
    return p;
  };
  SP.refresh = () => pollers.forEach((p) => p.run(true));
  // Relative timestamps tick in place: <span data-ago="ISO"></span>
  setInterval(() => document.querySelectorAll("[data-ago]").forEach((el) => (el.textContent = SP.ago(el.dataset.ago || null))), 1000);

  SP.runProbe = async (btn) => {
    try {
      if (btn) { btn.disabled = true; btn.querySelector(".material-symbols-outlined")?.classList.add("sp-spin"); }
      await SP.post("/api/probe/run");
      SP.toast("Probe cycle triggered", "Synthetic journeys are running now against the mock bank.", "info");
      setTimeout(SP.refresh, 2500); setTimeout(SP.refresh, 6000);
    } catch (e) { SP.toast("Could not trigger probe", e.message, "crit"); }
    finally { if (btn) setTimeout(() => { btn.disabled = false; btn.querySelector(".material-symbols-outlined")?.classList.remove("sp-spin"); }, 2500); }
  };

  async function pollStatus() {
    try {
      const s = await SP.api("/api/status");
      SP.status = s; paintShell(s);
      document.dispatchEvent(new CustomEvent("sp:status", { detail: s }));
    } catch (e) {
      const el = document.getElementById("sp-updated"); if (el) el.textContent = "Monitor unreachable – retrying…";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderHeader(); renderFooter();
    pollStatus(); setInterval(pollStatus, 3000);
    pollAlerts(); setInterval(pollAlerts, 3000);
  });
})();
