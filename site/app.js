/* IHSG Dividend Hunter: renders data/scan.json. No build step, no libraries. */
(() => {
  "use strict";

  const app = document.getElementById("app");
  const state = { scan: null, sort: { key: "rank", dir: 1 }, filter: loadFilter() };
  const SECTOR_COLORS = ["#0f766e", "#2563eb", "#a16207", "#be185d", "#7c3aed", "#15803d", "#c2410c", "#0e7490", "#4d7c0f", "#9f1239", "#475569"];

  // ---------- helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const pct = (v, d = 1) => (v === null || v === undefined ? "–" : num(v, d) + "%");
  const signed = (v, d = 1) => (v === null || v === undefined ? "–" : `<span class="${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "+" : ""}${num(v, d)}%</span>`);
  const idr = (v) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: v < 100 ? 1 : 0 }));
  const tierBadge = (c) => c.verdict.passed ? `<span class="tier ${c.verdict.tier}">${c.verdict.tier}</span>` : `<span class="tier F">✕</span>`;
  const get = (o, path) => path.split(".").reduce((x, k) => (x == null ? x : x[k]), o);

  function loadFilter() {
    const def = { q: "", tier: "all", sector: "", show: "passed", opp: false };
    try { return Object.assign(def, JSON.parse(localStorage.getItem("dh-filter") || "{}")); } catch { return def; }
  }
  function saveFilter() { try { localStorage.setItem("dh-filter", JSON.stringify(state.filter)); } catch { /* private mode */ } }

  const COLS = [
    { key: "rank", label: "#", num: true, val: (c) => c.rank ?? null, fmt: (c) => c.rank ?? "" },
    { key: "ticker", label: "Stock", val: (c) => c.ticker, fmt: (c) => `<span class="tk">${esc(c.ticker)}</span><span class="nm">${esc(c.name)}</span>` },
    { key: "tier", label: "Tier", val: (c) => c.verdict.passed ? c.verdict.tier : "Z", fmt: (c) => tierBadge(c) + (c.verdict.opportunity ? ' <span class="pill opp">Opportunity</span>' : "") },
    { key: "sharpe", label: "Div. Sharpe", num: true, val: (c) => get(c, "risk.sharpe"), fmt: (c) => num(get(c, "risk.sharpe"), 2), tip: "(forward yield after tax − SBN 10Y) ÷ volatility" },
    { key: "fwd", label: "Fwd yield (net)", num: true, val: (c) => get(c, "projection.forward_yield_after_tax"), fmt: (c) => pct(get(c, "projection.forward_yield_after_tax")), tip: "Projected next-year dividend ÷ price, after 10% tax" },
    { key: "req", label: "Required", num: true, val: (c) => get(c, "risk.required_yield"), fmt: (c) => pct(get(c, "risk.required_yield")), tip: "Forward yield after tax must beat this (SBN 10Y + k × volatility; k is set in config)" },
    { key: "ttm", label: "Trailing yield", num: true, val: (c) => c.trailing_yield, fmt: (c) => pct(c.trailing_yield), tip: "Dividends of the last 12 months ÷ price, before tax" },
    { key: "payout", label: "Payout", num: true, val: (c) => c.payout, fmt: (c) => pct(c.payout, 0) },
    { key: "beta", label: "Beta", num: true, val: (c) => get(c, "risk.beta"), fmt: (c) => num(get(c, "risk.beta"), 2), tip: "vs IHSG, 3 years of daily prices" },
    { key: "vol", label: "Volatility", num: true, val: (c) => get(c, "risk.volatility"), fmt: (c) => pct(get(c, "risk.volatility"), 0) },
    { key: "mdd", label: "Max drawdown", num: true, val: (c) => get(c, "risk.max_drawdown"), fmt: (c) => pct(get(c, "risk.max_drawdown"), 0) },
    { key: "why", label: "Flags / reason", val: (c) => (c.verdict.passed ? c.verdict.flags.length : 99), fmt: (c) => reason(c), cls: "why" },
  ];

  function reason(c) {
    if (!c.verdict.passed) {
      const f = c.verdict.failed;
      return `<span title="${esc(f.detail)}">Failed${f.id === "data" ? "" : " gate " + esc(f.id)}: ${esc(f.name)}</span>`;
    }
    if (!c.verdict.flags.length) return "No flags";
    return c.verdict.flags.map((f) => esc(f.name)).join(" · ");
  }

  // ---------- views
  function viewRanking() {
    const s = state.scan, f = state.filter;
    const passed = s.stocks.filter((c) => c.verdict.passed);
    const sectors = [...new Set(s.stocks.filter((c) => c.stage >= 2).map((c) => c.sector))].sort();
    const SHOW = {
      passed: (c) => c.verdict.passed,
      failed: (c) => c.verdict.passed || c.stage >= 2,
      all: () => true,
    };
    let rows = s.stocks.filter(SHOW[f.show] || SHOW.passed);
    if (f.tier !== "all") rows = rows.filter((c) => c.verdict.tier === f.tier);
    if (f.sector) rows = rows.filter((c) => c.sector === f.sector);
    if (f.opp) rows = rows.filter((c) => c.verdict.opportunity);
    if (f.q) {
      const q = f.q.toLowerCase();
      rows = rows.filter((c) => c.ticker.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q));
    }
    const col = COLS.find((x) => x.key === state.sort.key) || COLS[0];
    rows.sort((a, b) => {
      const x = col.val(a), y = col.val(b);
      if (x == null && y == null) return a.ticker.localeCompare(b.ticker);
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * state.sort.dir;
    });

    const mix = {};
    passed.forEach((c) => (mix[c.sector] = (mix[c.sector] || 0) + 1));
    const mixList = Object.entries(mix).sort((a, b) => b[1] - a[1]);
    const ct = s.counts;
    const mk = s.settings.market;

    app.innerHTML = `
      ${s.demo ? '<div class="demo-banner">Demo data: these companies and numbers are made up, for previewing the site only.</div>' : ""}
      <h1 style="margin-top:12px">Dividend ranking</h1>
      <p class="muted">Scan of ${ct.universe.toLocaleString()} IDX stocks, prices as of <b>${esc(s.asof)}</b>.
        Stocks that pass every gate are grouped into tiers by how many warning flags they carry, then ranked by dividend Sharpe.
        Yield on its own never decides the order.</p>

      <div class="funnel" aria-label="Scan funnel">
        <div class="step"><div class="n">${ct.universe}</div><div class="t">IDX stocks scanned</div></div>
        <div class="step"><div class="n">${ct.with_prices}</div><div class="t">with price data${ct.missing_prices ? ` (${ct.missing_prices} missing)` : ""}</div></div>
        <div class="step"><div class="n">${ct.filter1}</div><div class="t">paid recently (filter 1)</div></div>
        <div class="step"><div class="n">${ct.filter2_data}</div><div class="t">statements read (filter 2)</div></div>
        <div class="step"><div class="n">${ct.passed}</div><div class="t">passed every gate</div></div>
        <div class="step"><div class="n tiers"><span><span class="tier A">A</span> ${ct.tiers.A}</span><span><span class="tier B">B</span> ${ct.tiers.B}</span><span><span class="tier C">C</span> ${ct.tiers.C}</span></div><div class="t">tiers by flags: 0, 1–2, 3+</div></div>
      </div>

      <div class="grid cols-2" style="margin-top:12px">
        <div class="panel">
          <h3>Sector mix of the stocks that passed</h3>
          ${mixList.length ? `<div class="mix">${mixList.map(([k, v], i) => `<span title="${esc(k)}: ${v}" style="width:${(v / passed.length) * 100}%;background:${SECTOR_COLORS[i % SECTOR_COLORS.length]}"></span>`).join("")}</div>
          <div class="legend">${mixList.map(([k, v], i) => `<span><i style="background:${SECTOR_COLORS[i % SECTOR_COLORS.length]}"></i>${esc(k)} ${v}</span>`).join("")}</div>` : '<p class="muted">No stock passed every gate in this scan.</p>'}
        </div>
        <div class="panel">
          <h3>Benchmarks used</h3>
          <dl class="kv">
            <dt>SBN 10-year yield</dt><dd>${pct(mk.sbn_10y, 2)}</dd>
            <dt>Required yield</dt><dd>${s.settings.filter3.k ? `SBN + ${s.settings.filter3.k} × volatility` : "beat SBN 10Y"}</dd>
            <dt>Dividend tax</dt><dd>${s.settings.tax.dividend}%</dd>
            <dt>Benchmark rates as of</dt><dd>${esc(mk.as_of)}</dd>
          </dl>
        </div>
      </div>

      <div class="controls">
        <input type="search" id="q" placeholder="Search ticker or name" value="${esc(f.q)}" aria-label="Search">
        <div class="seg" role="group" aria-label="Tier">
          ${["all", "A", "B", "C"].map((t) => `<button data-tier="${t}" class="${f.tier === t ? "on" : ""}">${t === "all" ? "All tiers" : "Tier " + t}</button>`).join("")}
        </div>
        <select id="sector" aria-label="Sector"><option value="">All sectors</option>${sectors.map((x) => `<option ${x === f.sector ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <label><input type="checkbox" id="opp" ${f.opp ? "checked" : ""}> Opportunity only</label>
        <select id="show" aria-label="Which stocks to show">
          <option value="passed" ${f.show === "passed" ? "selected" : ""}>Passed every gate</option>
          <option value="failed" ${f.show === "failed" ? "selected" : ""}>+ dividend payers that failed a gate</option>
          <option value="all" ${f.show === "all" ? "selected" : ""}>Every IDX stock scanned</option>
        </select>
      </div>

      <div class="table-wrap">
        <table>
          <thead><tr>${COLS.map((c) => `<th data-key="${c.key}" class="${c.num ? "num" : ""}" ${c.tip ? `title="${esc(c.tip)}"` : ""}>${c.label}${state.sort.key === c.key ? ` <span class="arrow">${state.sort.dir > 0 ? "▲" : "▼"}</span>` : ""}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((c) => `<tr data-t="${esc(c.ticker)}">${COLS.map((col) => `<td class="${col.num ? "num" : ""} ${col.cls || ""}">${col.fmt(c)}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${COLS.length}" class="muted">No stocks match these filters.</td></tr>`}</tbody>
        </table>
      </div>
      <p class="muted" style="font-size:13px">${rows.length} shown. Click a row for the full stock card. Use the “Passed every gate” menu to also see the stocks that failed, and why.</p>
    `;

    const q = app.querySelector("#q");
    q.addEventListener("input", () => { state.filter.q = q.value; saveFilter(); rerenderKeepFocus(); });
    app.querySelectorAll("[data-tier]").forEach((b) => b.addEventListener("click", () => { state.filter.tier = b.dataset.tier; saveFilter(); viewRanking(); }));
    app.querySelector("#sector").addEventListener("change", (e) => { state.filter.sector = e.target.value; saveFilter(); viewRanking(); });
    app.querySelector("#opp").addEventListener("change", (e) => { state.filter.opp = e.target.checked; saveFilter(); viewRanking(); });
    app.querySelector("#show").addEventListener("change", (e) => { state.filter.show = e.target.value; saveFilter(); viewRanking(); });
    app.querySelectorAll("th[data-key]").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.key;
      state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (["sharpe", "fwd", "ttm"].includes(k) ? -1 : 1) };
      viewRanking();
    }));
    app.querySelectorAll("tbody tr[data-t]").forEach((tr) => tr.addEventListener("click", () => (location.hash = "#/stock/" + tr.dataset.t)));
  }

  function rerenderKeepFocus() {
    const pos = app.querySelector("#q").selectionStart;
    viewRanking();
    const q = app.querySelector("#q");
    q.focus();
    q.setSelectionRange(pos, pos);
  }

  const ICON = { pass: "✓", ok: "✓", fail: "✕", flag: "!", nodata: "?", skip: "–", info: "i" };
  const KIND = { gate: "gate", flag: "flag", info: "info" };

  function checkList(checks) {
    if (!checks.length) return '<p class="muted">Not reached: the stock stopped at an earlier filter.</p>';
    return `<ul class="checks">${checks.map((c) => {
      const st = c.flag ? "flag" : c.status;
      return `<li><span class="ic ${st}" title="${esc(st)}">${ICON[st] || "·"}</span>
        <div><span class="nm">${esc(c.id)}. ${esc(c.name)}</span><span class="kind">${KIND[c.kind] || ""}${c.status === "nodata" ? " · no data" : c.status === "skip" ? " · skipped" : ""}</span>
        <div class="dt">${esc(c.detail)}</div></div></li>`;
    }).join("")}</ul>`;
  }

  function priceChart(points, divs) {
    if (!points || points.length < 2) return '<p class="muted">No price history.</p>';
    const W = 640, H = 200, P = 52;
    const xs = points.map((p) => +new Date(p[0])), ys = points.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys) * 0.95, y1 = Math.max(...ys) * 1.03;
    const X = (x) => P + ((x - x0) / (x1 - x0)) * (W - P - 6), Y = (y) => 8 + (1 - (y - y0) / (y1 - y0)) * (H - 30);
    const d = points.map((p, i) => `${i ? "L" : "M"}${X(xs[i]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    const area = `${d}L${X(x1).toFixed(1)},${H - 22}L${X(x0).toFixed(1)},${H - 22}Z`;
    const ticks = [y0, (y0 + y1) / 2, y1].map((v) => `<line class="ax" x1="${P}" x2="${W - 6}" y1="${Y(v)}" y2="${Y(v)}"/><text x="2" y="${Y(v) + 4}">${idr(v)}</text>`).join("");
    const years = [...new Set(points.map((p) => p[0].slice(0, 4)))].map((y) => {
      const t = +new Date(y + "-01-01");
      return t >= x0 && t <= x1 ? `<text x="${X(t)}" y="${H - 6}" text-anchor="middle">${y}</text>` : "";
    }).join("");
    const exs = (divs || []).filter((dv) => +new Date(dv[0]) >= x0).map((dv) => {
      const t = +new Date(dv[0]);
      const near = points.reduce((a, p) => (Math.abs(+new Date(p[0]) - t) < Math.abs(+new Date(a[0]) - t) ? p : a));
      return `<circle class="ex" cx="${X(t)}" cy="${Y(near[1])}" r="3.5"><title>Ex-date ${dv[0]}: ${idr(dv[1])} per share</title></circle>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly closing price, 3 years">${ticks}<path class="ar" d="${area}"/><path class="ln" d="${d}"/>${exs}${years}</svg>
      <p class="muted" style="font-size:12.5px;margin:4px 0 0">Weekly close, 3 years. Dots mark ex-dividend dates.</p>`;
  }

  function dividendBars(byYear) {
    const ys = Object.keys(byYear || {}).sort();
    if (!ys.length) return "";
    const max = Math.max(...ys.map((y) => byYear[y]), 1e-9);
    return `<div class="bars">${ys.map((y) => `<div class="${byYear[y] ? "" : "zero"}" style="height:${Math.max(2, (byYear[y] / max) * 100)}%" title="${y}: ${idr(byYear[y])} per share"></div>`).join("")}</div>
      <div class="bar-labels">${ys.map((y) => `<span>${"'" + y.slice(2)}</span>`).join("")}</div>`;
  }

  function viewStock(ticker) {
    const c = state.scan.stocks.find((x) => x.ticker === ticker);
    if (!c) { app.innerHTML = `<a class="back" href="#/">← Ranking</a><p>${esc(ticker)} is not in the latest scan.</p>`; return; }
    const v = c.verdict, r = c.risk || {}, p = c.projection || {};
    const rec = (c.checks.find((x) => x.id === "2") || {}).value || {};
    const groups = (g) => c.checks.filter((x) => x.group === g && x.id !== "2");
    const verdictHtml = v.passed
      ? `<div class="verdict pass"><div class="big">Tier ${v.tier}${c.rank ? ` · rank ${c.rank}` : ""}${v.opportunity ? ' · <span class="pill opp">Opportunity</span>' : ""}</div>
          <div>${v.flags.length ? `${v.flags.length} flag${v.flags.length > 1 ? "s" : ""}: ${v.flags.map((f) => esc(f.name)).join(", ")}` : "Passed every gate with no flags."}</div>
          ${v.opportunity ? '<div class="muted" style="margin-top:4px">Opportunity: profit is up on the same period last year and confirmed by cash flow, but the price is more than 20% below its 1-year high. Read the latest MD&amp;A and news for a reason the numbers miss.</div>' : ""}</div>`
      : `<div class="verdict fail"><div class="big">Failed ${v.failed.id === "data" ? "" : "gate " + esc(v.failed.id) + ": "}${esc(v.failed.name)}</div><div>${esc(v.failed.detail)}</div></div>`;

    app.innerHTML = `
      ${state.scan.demo ? '<div class="demo-banner">Demo data: made up, for previewing the site only.</div>' : ""}
      <a class="back" href="#/">← Ranking</a>
      <div class="card-head"><h1>${esc(c.ticker)}</h1><span class="muted">${esc(c.name)}</span><span class="pill">${esc(c.sector || "Sector unknown")}${c.is_bank ? " · bank track" : ""}</span></div>
      <p class="muted" style="margin:4px 0 0">${c.price == null ? "No price data" : `Price ${idr(c.price)} IDR on ${esc(c.price_date)}`}${c.financial_currency && c.financial_currency !== "IDR" ? ` · reports in ${esc(c.financial_currency)}, converted at today's rate` : ""}</p>
      ${verdictHtml}

      <div class="grid cols-2">
        <div class="panel chart">${priceChart(c.chart, c.dividends)}</div>
        <div class="panel">
          <h3>Key numbers</h3>
          <dl class="kv">
            <dt>Dividend Sharpe</dt><dd>${num(r.sharpe, 2)}</dd>
            <dt>Forward yield after tax</dt><dd>${pct(p.forward_yield_after_tax)}</dd>
            <dt>Required yield</dt><dd>${pct(r.required_yield)}</dd>
            <dt>Projected dividend / share</dt><dd>${idr(p.dps)}${p.payout_basis ? ` <span class="muted">(${esc(p.payout_basis)} ${pct(p.payout_used, 0)})</span>` : ""}</dd>
            <dt>Trailing yield (before / after tax)</dt><dd>${pct(c.trailing_yield)} / ${pct(c.trailing_yield_after_tax)}</dd>
            <dt>Current yield (before / after tax)</dt><dd>${pct(c.current_yield)} / ${pct(c.current_yield_after_tax)}</dd>
            <dt>Beta vs IHSG / sector</dt><dd>${num(r.beta, 2)} / ${num(r.beta_sector, 2)}</dd>
            <dt>Volatility · max drawdown (3y)</dt><dd>${pct(r.volatility, 0)} · ${pct(r.max_drawdown, 0)}</dd>
            <dt>Total return after tax (3y, a year)</dt><dd>${pct(r.total_return_3y)}</dd>
            <dt>From 1-year high</dt><dd>${r.drop_from_high == null ? "–" : signed(r.drop_from_high, 0)}</dd>
            <dt>Bond ladder rung beaten</dt><dd>${esc(r.ladder ? r.ladder.highest : "–")}</dd>
          </dl>
        </div>
      </div>

      <h2>1. Does it pay?</h2>
      <div class="grid cols-2">
        <div class="panel">${checkList(groups("pays"))}</div>
        <div class="panel">
          <h3>Dividend per share by year (ex-date year)</h3>
          ${dividendBars(rec.by_year)}
          <dl class="kv" style="margin-top:10px">
            <dt>Years paid</dt><dd>${rec.years_paid ?? "–"} of ${rec.years_checked ?? 10}</dd>
            <dt>Trend</dt><dd>${esc(rec.trend || "–")}</dd>
            <dt>Average yield (10y)</dt><dd>${pct(rec.avg_yield)}</dd>
            <dt>2015–16 vs 2014</dt><dd>${rec.stress_2015_16 == null ? "–" : signed(rec.stress_2015_16, 0)}</dd>
            <dt>2020 vs 2019</dt><dd>${rec.stress_2020 == null ? "–" : signed(rec.stress_2020, 0)}</dd>
          </dl>
        </div>
      </div>

      <h2>2. Can it keep paying?</h2>
      <div class="panel">${checkList(groups("keep"))}</div>

      <h2>3. Is it worth the risk?</h2>
      <div class="grid cols-2">
        <div class="panel">${checkList(groups("risk"))}</div>
        <div class="panel">
          <h3>Ex-date recovery (last payouts)</h3>
          ${r.recovery && r.recovery.events.length ? `<table><thead><tr><th>Ex-date</th><th class="num">Trading days</th><th>Recovered</th></tr></thead><tbody>
            ${r.recovery.events.map((e) => `<tr><td class="mono">${esc(e.ex_date)}</td><td class="num">${e.days}</td><td>${e.recovered ? "Yes" : '<span class="neg">Not yet</span>'}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">No ex-dates to measure.</p>'}
          ${r.ladder ? `<h3 style="margin-top:14px">Bond ladder, after tax</h3><dl class="kv">${r.ladder.rungs.map((x) => `<dt>${esc(x.name)}</dt><dd>${pct(x.after_tax, 2)} ${(p.forward_yield_after_tax ?? -1) > x.after_tax ? '<span class="pos">beaten</span>' : '<span class="muted">not beaten</span>'}</dd>`).join("")}</dl>` : ""}
        </div>
      </div>
      <p class="muted" style="font-size:13px;margin-top:16px">Opportunity notes (MD&amp;A and news summaries) are not automated yet.</p>
    `;
    window.scrollTo(0, 0);
  }

  async function viewHistory() {
    app.innerHTML = '<h1>Monthly history</h1><p class="muted">Loading…</p>';
    let months = [];
    try { months = await (await fetch("data/history/index.json", { cache: "no-cache" })).json(); } catch { /* none yet */ }
    if (!months.length) {
      app.innerHTML = '<h1>Monthly history</h1><p class="muted">The site keeps one snapshot of the ranking per month. The first one appears after the first live scan.</p>';
      return;
    }
    const snaps = await Promise.all(months.slice(-12).reverse().map((m) => fetch(`data/history/${m}.json`).then((r) => r.json()).then((d) => [m, d]).catch(() => [m, null])));
    app.innerHTML = `<h1>Monthly history</h1>
      <p class="muted">The top 5 of the ranking at the last scan of each month. Use this to see whether a stock keeps its place or only shows up once.</p>
      <div class="table-wrap"><table><thead><tr><th>Month</th><th class="num">SBN 10Y</th><th>1st</th><th>2nd</th><th>3rd</th><th>4th</th><th>5th</th></tr></thead><tbody>
      ${snaps.filter(([, d]) => d).map(([m, d]) => {
        const top = d.stocks.filter((x) => x.rank).sort((a, b) => a.rank - b.rank).slice(0, 5);
        return `<tr><td class="mono">${esc(m)}</td><td class="num">${pct(d.sbn_10y, 2)}</td>${[0, 1, 2, 3, 4].map((i) => top[i] ? `<td><a href="#/stock/${esc(top[i].ticker)}" class="mono">${esc(top[i].ticker)}</a> <span class="tier ${top[i].tier}">${top[i].tier}</span> <span class="muted">${pct(top[i].forward_yield_after_tax)}</span></td>` : "<td></td>").join("")}</tr>`;
      }).join("")}
      </tbody></table></div>`;
  }

  function viewMethod() {
    const s = state.scan.settings;
    const f2 = s.filter2, b = s.bank, f3 = s.filter3, mk = s.market;
    app.innerHTML = `<div class="prose">
      <h1>How the scan works</h1>
      <p>The scanner looks for IDX stocks whose dividend is likely to keep coming for years, and only then asks whether the yield pays enough for the price risk.
        It was built after a painful lesson: a 13% yield on a payout ratio above 160%, followed by a large capital loss. High yield is often a symptom of a falling price.</p>
      <p>Every check is one of three types. A <b>gate</b> removes the stock. A <b>flag</b> keeps it but attaches a named warning. <b>Info</b> is shown and never judges.
        A gate that cannot be checked because data is missing does not remove the stock, but it counts as a flag, so a stock with gaps cannot reach tier A.</p>

      <h2>Filter 1: does it pay?</h2>
      <p>Gate: a dividend within the last ${s.filter1.latest_window_months} months, and in at least ${s.filter1.min_years_of_last_3} of the last 3 years.
        Shown for information: the 10-year record, the trend, and behaviour in the 2015–16 commodity slump and 2020.</p>

      <h2>Filter 2: can it keep paying?</h2>
      <div class="table-wrap"><table><thead><tr><th>#</th><th>Check</th><th>Type</th><th>Rule</th></tr></thead><tbody>
        <tr><td>4</td><td>Payout ratio</td><td>Gate + flag</td><td>Over ${f2.payout_fail}% fails; ${f2.payout_flag}–${f2.payout_fail}% flagged (last 12 months)</td></tr>
        <tr><td>5</td><td>Free cash flow cover</td><td>Gate</td><td>Free cash flow of the last 12 months at least the dividend paid</td></tr>
        <tr><td>6</td><td>Earnings trend</td><td>Gate</td><td>Year-to-date profit not more than ${f2.earnings_drop_max}% below the same period last year</td></tr>
        <tr><td>7</td><td>Earnings quality</td><td>Flag</td><td>Net profit up while operating profit or operating cash flow is down</td></tr>
        <tr><td>8</td><td>Net debt / EBITDA</td><td>Flag</td><td>Above ${f2.net_debt_ebitda_flag}x</td></tr>
        <tr><td>9</td><td>Interest coverage</td><td>Flag</td><td>Below ${f2.interest_cover_flag}x</td></tr>
        <tr><td>10</td><td>Debt/equity and current ratio</td><td>Flag</td><td>Worse than the sector median</td></tr>
        <tr><td>11</td><td>Dividend policy</td><td>Flag</td><td>Last payout broke the stated policy (entered by hand)</td></tr>
        <tr><td>12</td><td>Dividend growth</td><td>Flag</td><td>5-year dividend growth below ${mk.inflation}% inflation, or gross margin falling 3 years running</td></tr>
        <tr><td>13</td><td>Payout vs own history</td><td>Flag</td><td>Current payout above ${f2.payout_vs_history_flag}x its own average</td></tr>
        <tr><td>14</td><td>Bond rating</td><td>Flag</td><td>Downgrade or negative outlook in the last 12 months (entered by hand)</td></tr>
      </tbody></table></div>

      <h3 style="margin-top:16px">Banks</h3>
      <p>Free cash flow and debt ratios do not describe a bank, so banks skip checks 5, 8, 9 and 10 and take these instead:
        CAR below ${b.car_min}% fails (gate); gross NPL above ${b.npl_max}% or up more than ${b.npl_rise_max} points in a year, NPL coverage below ${b.coverage_min}%,
        loan-to-deposit ratio above ${b.ldr_max}%, and ROE below ${b.roe_min}% are flags. CAR, NPL, coverage and LDR come from each bank's quarterly published report and are entered by hand.</p>

      <h2>Filter 3: is the yield worth the volatility?</h2>
      <p>The price is judged against the dividend expected next, not the one already paid:</p>
      <ul>
        <li><b>Projected dividend</b> = profit of the last 4 quarters ÷ shares × payout (the stated policy, else the company's own recent average, capped at 100%).</li>
        <li><b>Forward yield</b> = projected dividend ÷ price, after ${s.tax.dividend}% dividend tax.</li>
        <li><b>Required yield</b> = ${f3.k ? `SBN 10Y (${mk.sbn_10y}%) + ${f3.k} × ${f3.lookback_years}-year annualised volatility` : `the SBN 10Y yield (${mk.sbn_10y}%)`}. Gate: forward yield after tax must beat it.${f3.k ? "" : " Volatility does not change the gate; it lowers a stock's dividend Sharpe, which sets the order."}</li>
        <li><b>Dividend Sharpe</b> = (forward yield after tax − SBN 10Y) ÷ volatility. This is the ranking number.</li>
      </ul>
      <p>Also shown: beta against IHSG and against an equal-weighted index of sector peers, maximum drawdown, the bond rung beaten after tax,
        and a return check (flag) when the 3-year total return after tax is below SBN or the ex-date drop takes more than ${f3.recovery_days_flag} trading days to recover (median of the last 5).</p>

      <h2>Tiers</h2>
      <p>Stocks that pass every gate: <span class="tier A">A</span> no flags, <span class="tier B">B</span> 1–2 flags, <span class="tier C">C</span> 3 or more.
        Tiers come first, so a shaky stock with a big yield can never outrank a clean one. Inside a tier, stocks are sorted by dividend Sharpe.</p>
      <p><span class="pill opp">Opportunity</span> marks a stock that passed, whose profit is at or above the same period last year and confirmed by cash flow, but whose price is more than ${s.opportunity.drop_from_high}% below its 1-year high.</p>

      <h2>Benchmarks</h2>
      <div class="table-wrap"><table><thead><tr><th>Rung</th><th class="num">Before tax</th><th class="num">After tax</th></tr></thead><tbody>
        ${[["Deposit", mk.deposit_rate, s.tax.deposit], ["SBN 10Y", mk.sbn_10y, s.tax.bond], ["AAA bond", mk.corp_aaa, s.tax.bond], ["A bond", mk.corp_a, s.tax.bond], ["BBB bond", mk.corp_bbb, s.tax.bond]]
          .map(([n, y, t]) => `<tr><td>${n}</td><td class="num">${pct(y, 2)}</td><td class="num">${pct(y * (1 - t / 100), 2)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted">Rates as of ${esc(mk.as_of)}, set by hand.</p>

      <h2>Data and limits</h2>
      <ul>
        <li>Prices, dividends and financial statements: Yahoo Finance, refreshed every trading day after the IDX close. Statements are cached for a week.</li>
        <li>Yahoo usually gives 4 years of annual and 5 quarters of quarterly statements, so "own history" checks use what is there, not 10 years.</li>
        <li>Sector names are Yahoo's classification, not IDX-IC, unless corrected by hand.</li>
        <li>Fiscal years are assumed to end in December. Companies reporting in USD are converted at the current rate.</li>
        <li>Thresholds are first proposals and have not yet been tested across the whole market.</li>
      </ul>
      <p><b>This site is a screener, not investment advice.</b> It does not recommend buying or selling any security. Past dividends do not guarantee future ones.</p>
    </div>`;
  }

  // ---------- routing
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#/" + h.split("/")[0]));
    if (h.startsWith("stock/")) return viewStock(decodeURIComponent(h.slice(6)).toUpperCase());
    if (h === "history") return viewHistory();
    if (h === "method") return viewMethod();
    return viewRanking();
  }

  fetch("data/scan.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((scan) => {
      state.scan = scan;
      document.getElementById("foot-meta").textContent =
        `Last scan ${scan.generated_at.replace("T", " ").replace("Z", " UTC")} · prices as of ${scan.asof} · ${scan.counts.universe} tickers from ${scan.universe_source}`;
      window.addEventListener("hashchange", route);
      route();
    })
    .catch((e) => { app.innerHTML = `<p>The scan data could not be loaded (${esc(e.message)}). The first scan may still be running; try again in a few minutes.</p>`; });
})();
