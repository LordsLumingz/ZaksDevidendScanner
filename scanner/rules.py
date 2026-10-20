"""The Dividend Scanner Framework as code.

Each check returns a dict with:
  id      the number from the framework rulebook ("4", "B1", ...)
  name    what is checked
  group   "pays", "keep" or "risk" (the three questions on the stock card)
  kind    "gate", "flag" or "info"
  status  "pass", "fail" (gates), "flag", "ok" (flags), "info", or "nodata"
  value   the number shown, already rounded
  detail  one line of plain text explaining the result

A gate with no data does not fail the stock, but it counts as a flag so a
stock with gaps cannot reach tier A.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import metrics as m
from .providers import Fundamentals, PriceData


def check(id, name, group, kind, status, value=None, detail=""):
    return {"id": id, "name": name, "group": group, "kind": kind,
            "status": status, "value": value, "detail": detail}


def r(x, n=1):
    return None if x is None else round(float(x), n)


@dataclass
class Context:
    cfg: dict
    asof: pd.Timestamp
    market_returns: pd.Series
    banks: dict           # ticker -> row from data/manual/banks.csv
    policies: dict
    ratings: dict
    sector_medians: dict | None = None   # sector -> {"de": x, "cr": y}
    sector_returns: dict | None = None   # sector -> {ticker: daily returns}


# ------------------------------------------------------------- filter 1

def filter1(prices: PriceData, ctx: Context) -> list[dict]:
    c1 = ctx.cfg["filter1"]
    divs = prices.dividends
    by_year = m.dividends_by_year(divs)
    asof = ctx.asof
    recent_cut = asof - pd.DateOffset(months=c1["latest_window_months"])
    latest_paid = divs is not None and not divs[divs.index > recent_cut].empty
    last3 = [asof.year - 1, asof.year - 2, asof.year - 3]
    # The current year counts too, so a stock that already paid this year
    # is not penalised for a quiet year three years back.
    years_paid = sum(1 for y in last3 if by_year.get(y, 0) > 0)
    if by_year.get(asof.year, 0) > 0 and by_year.get(asof.year - 1, 0) == 0:
        years_paid += 1
    years_paid = min(years_paid, 3)
    ok = latest_paid and years_paid >= c1["min_years_of_last_3"]
    if ok:
        detail = f"Paid within the last {c1['latest_window_months']} months and in {years_paid} of the last 3 years"
    elif not latest_paid:
        detail = f"No dividend in the last {c1['latest_window_months']} months"
    else:
        detail = f"Paid in only {years_paid} of the last 3 years"

    close = prices.close
    year_end = close.groupby(close.index.year).last() if not close.empty else None
    record = m.dividend_record(divs, asof, year_end)
    out = [check("1", "Paid recently", "pays", "gate", "pass" if ok else "fail", years_paid, detail)]
    rec_detail = (f"{record['years_paid']} of {record['years_checked']} years paid; trend {record['trend']}")
    if record["stress_2015_16"] is not None:
        rec_detail += f"; 2015-16 vs 2014: {record['stress_2015_16']:+.0f}%"
    if record["stress_2020"] is not None:
        rec_detail += f"; 2020 vs 2019: {record['stress_2020']:+.0f}%"
    out.append(check("2", "10-year dividend record", "pays", "info", "info", record, rec_detail))
    return out


def yields(prices: PriceData, ctx: Context) -> dict:
    tax = ctx.cfg["tax"]["dividend"] / 100
    price = float(prices.close.iloc[-1]) if not prices.close.empty else None
    asof = ctx.asof
    ttm_dps = m.trailing_dps(prices.dividends, asof)
    year_ago = prices.dividends[prices.dividends.index > asof - pd.DateOffset(months=12)]
    current_dps = float(prices.dividends.iloc[-1]) * max(1, len(year_ago)) if len(prices.dividends) else 0.0
    if not price:
        return {"price": price}
    return {
        "price": price,
        "ttm_dps": ttm_dps,
        "trailing_yield": ttm_dps / price * 100,
        "trailing_yield_after_tax": ttm_dps / price * 100 * (1 - tax),
        "current_yield": current_dps / price * 100,
        "current_yield_after_tax": current_dps / price * 100 * (1 - tax),
    }


# ------------------------------------------------------------- filter 2

def statement_numbers(f: Fundamentals) -> dict:
    """Pull the line items the checks need, in the report currency."""
    ni_q = m.row(f.q_income, "Net Income Common Stockholders", "Net Income")
    ni_a = m.row(f.a_income, "Net Income Common Stockholders", "Net Income")
    op_q = m.row(f.q_income, "Operating Income", "EBIT")
    op_a = m.row(f.a_income, "Operating Income", "EBIT")
    ebitda_q = m.row(f.q_income, "EBITDA", "Normalized EBITDA")
    int_q = m.row(f.q_income, "Interest Expense", "Interest Expense Non Operating")
    gp_a = m.row(f.a_income, "Gross Profit")
    rev_a = m.row(f.a_income, "Total Revenue", "Operating Revenue")
    fcf_q = m.row(f.q_cash, "Free Cash Flow")
    fcf_a = m.row(f.a_cash, "Free Cash Flow")
    ocf_a = m.row(f.a_cash, "Operating Cash Flow")
    div_q = m.row(f.q_cash, "Cash Dividends Paid", "Common Stock Dividend Paid")
    div_a = m.row(f.a_cash, "Cash Dividends Paid", "Common Stock Dividend Paid")
    bal = f.q_balance if f.q_balance is not None and not f.q_balance.empty else f.a_balance
    debt = m.latest(m.row(bal, "Total Debt"))
    cash = m.latest(m.row(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"))
    net_debt = m.latest(m.row(bal, "Net Debt"))
    if net_debt is None and debt is not None:
        net_debt = debt - (cash or 0)
    n = {
        "ni_ttm": m.ttm(ni_q) if m.ttm(ni_q) is not None else m.latest(ni_a),
        "ni_q": ni_q, "ni_a": ni_a, "op_a": op_a, "ocf_a": ocf_a, "op_q": op_q,
        "ebitda_ttm": m.ttm(ebitda_q) if m.ttm(ebitda_q) is not None else m.latest(m.row(f.a_income, "EBITDA", "Normalized EBITDA")),
        "ebit_ttm": m.ttm(op_q) if m.ttm(op_q) is not None else m.latest(op_a),
        "interest_ttm": m.ttm(int_q) if m.ttm(int_q) is not None else m.latest(m.row(f.a_income, "Interest Expense")),
        "fcf_ttm": m.ttm(fcf_q) if m.ttm(fcf_q) is not None else m.latest(fcf_a),
        "div_paid_ttm": abs(m.ttm(div_q)) if m.ttm(div_q) is not None else (abs(m.latest(div_a)) if m.latest(div_a) is not None else None),
        "div_a": div_a.abs() if div_a is not None else None,
        "gross_margin_a": (gp_a / rev_a * 100).dropna() if gp_a is not None and rev_a is not None else None,
        "debt": debt, "net_debt": net_debt,
        "equity": m.latest(m.row(bal, "Stockholders Equity", "Common Stock Equity")),
        "current_assets": m.latest(m.row(bal, "Current Assets")),
        "current_liabilities": m.latest(m.row(bal, "Current Liabilities")),
    }
    return n


def payout_history(n: dict) -> list[float]:
    """Yearly payout ratios (dividends paid / net income), newest first."""
    if n["div_a"] is None or n["ni_a"] is None:
        return []
    joined = pd.concat([n["div_a"], n["ni_a"]], axis=1, join="inner").dropna()
    return [float(d / ni * 100) for d, ni in joined.sort_index(ascending=False).values if ni > 0]


def filter2(f: Fundamentals, prices: PriceData, ticker: str, ctx: Context) -> tuple[list[dict], dict]:
    c2, cb = ctx.cfg["filter2"], ctx.cfg["bank"]
    n = statement_numbers(f)
    out: list[dict] = []
    bank = f.is_bank

    # 4. payout ratio
    payout = None
    if n["div_paid_ttm"] is not None and n["ni_ttm"] is not None:
        payout = float("inf") if n["ni_ttm"] <= 0 and n["div_paid_ttm"] > 0 else (
            n["div_paid_ttm"] / n["ni_ttm"] * 100 if n["ni_ttm"] else None)
    if payout is None:
        out.append(check("4", "Payout ratio", "keep", "gate", "nodata", None, "Dividends paid or net profit not reported"))
    elif payout > c2["payout_fail"]:
        txt = "net profit is zero or negative" if payout == float("inf") else f"{payout:.0f}% of net profit paid out"
        out.append(check("4", "Payout ratio", "keep", "gate", "fail", None if payout == float("inf") else r(payout, 0),
                         f"Payout over {c2['payout_fail']}%: {txt}"))
    elif payout >= c2["payout_flag"]:
        out.append(check("4", "Payout ratio", "keep", "gate", "pass", r(payout, 0),
                         f"Flag: payout {payout:.0f}% is between {c2['payout_flag']}% and {c2['payout_fail']}%"))
        out[-1]["flag"] = True
    else:
        out.append(check("4", "Payout ratio", "keep", "gate", "pass", r(payout, 0), f"{payout:.0f}% of the last 12 months' profit"))

    # 5. FCF cover (not for banks)
    if bank:
        out.append(check("5", "Free cash flow cover", "keep", "gate", "skip", None, "Not used for banks"))
    elif n["fcf_ttm"] is None or n["div_paid_ttm"] is None:
        out.append(check("5", "Free cash flow cover", "keep", "gate", "nodata", None, "Free cash flow not reported"))
    else:
        cover = n["fcf_ttm"] / n["div_paid_ttm"] if n["div_paid_ttm"] else None
        ok = n["fcf_ttm"] >= n["div_paid_ttm"]
        out.append(check("5", "Free cash flow cover", "keep", "gate", "pass" if ok else "fail", r(cover, 2),
                         f"FCF covers the dividend {cover:.1f}x" if cover is not None and ok else
                         ("Free cash flow is below the dividend paid" if cover is not None else "No dividend paid in the last 12 months")))

    # 6. earnings trend
    ytd = m.year_to_date_change(n["ni_q"], n["ni_a"])
    if ytd is None or ytd["pct"] is None:
        out.append(check("6", "Earnings trend", "keep", "gate", "nodata", None, "Not enough quarterly profit data"))
    else:
        ok = ytd["pct"] >= -c2["earnings_drop_max"]
        out.append(check("6", "Earnings trend", "keep", "gate", "pass" if ok else "fail", ytd["pct"],
                         f"Net profit {ytd['pct']:+.0f}% ({ytd['basis']})"))

    # 7. earnings quality
    ni_ch = m.year_to_date_change(None, n["ni_a"])
    op_ch = m.year_to_date_change(None, n["op_a"])
    ocf_ch = m.year_to_date_change(None, n["ocf_a"])
    if ni_ch is None or ni_ch["pct"] is None or (op_ch is None and ocf_ch is None):
        out.append(check("7", "Earnings quality", "keep", "flag", "nodata", None, "Not enough yearly data"))
    else:
        weak = [lbl for lbl, ch in (("operating profit", op_ch), ("operating cash flow", ocf_ch))
                if ch and ch["pct"] is not None and ch["pct"] < 0]
        bad = ni_ch["pct"] > 0 and bool(weak)
        out.append(check("7", "Earnings quality", "keep", "flag", "flag" if bad else "ok", None,
                         f"Net profit up {ni_ch['pct']:.0f}% but {' and '.join(weak)} down ({ni_ch['basis']})" if bad
                         else f"Operating profit and cash flow move with net profit ({ni_ch['basis']})"))

    if bank:
        out += bank_track(ticker, n, ctx)
    else:
        # 8. net debt / EBITDA
        if n["net_debt"] is None or not n["ebitda_ttm"]:
            out.append(check("8", "Net debt / EBITDA", "keep", "flag", "nodata", None, "Debt or EBITDA not reported"))
        else:
            v = n["net_debt"] / n["ebitda_ttm"] if n["ebitda_ttm"] > 0 else float("inf")
            bad = v > c2["net_debt_ebitda_flag"]
            out.append(check("8", "Net debt / EBITDA", "keep", "flag", "flag" if bad else "ok",
                             None if v == float("inf") else r(v, 1),
                             "Net cash (more cash than debt)" if v < 0 else
                             (f"{v:.1f}x, above {c2['net_debt_ebitda_flag']}x" if bad else f"{v:.1f}x")))
        # 9. interest coverage
        if not n["interest_ttm"] or n["ebit_ttm"] is None:
            out.append(check("9", "Interest coverage", "keep", "flag", "ok" if n["interest_ttm"] == 0 else "nodata", None,
                             "No interest expense" if n["interest_ttm"] == 0 else "Interest expense not reported"))
        else:
            v = n["ebit_ttm"] / abs(n["interest_ttm"])
            bad = v < c2["interest_cover_flag"]
            out.append(check("9", "Interest coverage", "keep", "flag", "flag" if bad else "ok", r(v, 1),
                             f"Operating profit covers interest {v:.1f}x" + (f", below {c2['interest_cover_flag']}x" if bad else "")))
        # 10. D/E and current ratio vs sector median
        out.append(sector_compare(f, n, ctx))

    # 11. dividend policy (hand-entered)
    pol = ctx.policies.get(ticker)
    if not pol or not pol.get("payout_policy_pct"):
        out.append(check("11", "Dividend policy", "keep", "flag", "nodata", None, "No policy recorded yet"))
    else:
        broke = str(pol.get("last_payout_kept_policy", "")).strip().lower() == "no"
        out.append(check("11", "Dividend policy", "keep", "flag", "flag" if broke else "ok", float(pol["payout_policy_pct"]),
                         f"Stated policy {pol['payout_policy_pct']}% of profit" + ("; last payout broke it" if broke else "")))

    # 12. dividend growth and gross margin
    cagr = m.dividend_cagr(prices.dividends, ctx.asof)
    gm = n["gross_margin_a"]
    gm_falling = (not bank and gm is not None and len(gm) >= 4
                  and all(gm.iloc[i] < gm.iloc[i + 1] for i in range(3)))
    infl = ctx.cfg["market"]["inflation"]
    if cagr is None and gm_falling is False and (gm is None or len(gm) < 4):
        out.append(check("12", "Dividend growth", "keep", "flag", "nodata", None, "Not enough dividend history for a 5-year rate"))
    else:
        reasons = []
        if cagr is not None and cagr < infl:
            reasons.append(f"5-year dividend growth {cagr:.1f}% a year, below {infl}% inflation")
        if gm_falling:
            reasons.append("gross margin fell 3 years running")
        out.append(check("12", "Dividend growth", "keep", "flag", "flag" if reasons else "ok", r(cagr),
                         "; ".join(reasons) or (f"5-year dividend growth {cagr:.1f}% a year" if cagr is not None else "Gross margin holding")))

    # 13. payout vs own history
    hist = payout_history(n)
    if payout is None or payout == float("inf") or len(hist) < 2:
        out.append(check("13", "Payout vs own history", "keep", "flag", "nodata", None, "Fewer than 2 years of payout history"))
    else:
        avg = sum(hist) / len(hist)
        bad = avg > 0 and payout > avg * c2["payout_vs_history_flag"]
        out.append(check("13", "Payout vs own history", "keep", "flag", "flag" if bad else "ok", r(avg, 0),
                         f"Now {payout:.0f}% vs {avg:.0f}% average over {len(hist)} years"))

    # 14. bond rating (hand-entered)
    rat = ctx.ratings.get(ticker)
    if not rat:
        out.append(check("14", "Bond rating", "keep", "flag", "nodata", None, "No rating recorded"))
    else:
        changed = pd.to_datetime(rat.get("changed") or None, errors="coerce")
        recent = changed is not pd.NaT and changed is not None and (ctx.asof - changed).days <= 365
        bad = recent and (rat.get("direction") == "downgrade" or rat.get("outlook") == "negative")
        out.append(check("14", "Bond rating", "keep", "flag", "flag" if bad else "ok", rat.get("rating"),
                         f"{rat.get('rating')} outlook {rat.get('outlook') or 'n/a'}" + ("; downgrade or negative outlook in the last 12 months" if bad else "")))

    numbers = {"payout": None if payout in (None, float("inf")) else payout, "payout_history": hist,
               "ni_ttm": n["ni_ttm"], "ytd": ytd, "earnings_quality_ok": not any(c["id"] == "7" and c["status"] == "flag" for c in out)}
    return out, numbers


def bank_track(ticker: str, n: dict, ctx: Context) -> list[dict]:
    cb = ctx.cfg["bank"]
    b = ctx.banks.get(ticker) or {}
    src = f" ({b.get('period')})" if b.get("period") else ""

    def num(k):
        try:
            return float(b[k]) if b.get(k) not in (None, "") else None
        except ValueError:
            return None

    out = []
    car = num("car")
    out.append(check("B1", "Capital adequacy (CAR)", "keep", "gate",
                     "nodata" if car is None else ("pass" if car >= cb["car_min"] else "fail"), car,
                     "Not recorded yet in data/manual/banks.csv" if car is None else
                     f"CAR {car}%{src}" + ("" if car >= cb["car_min"] else f", below {cb['car_min']}%")))
    npl, prev = num("npl_gross"), num("npl_gross_prev")
    if npl is None:
        out.append(check("B2", "Gross NPL", "keep", "flag", "nodata", None, "Not recorded yet"))
    else:
        bad = npl > cb["npl_max"] or (prev is not None and npl - prev > cb["npl_rise_max"])
        out.append(check("B2", "Gross NPL", "keep", "flag", "flag" if bad else "ok", npl,
                         f"NPL {npl}%{src}" + (f", a year earlier {prev}%" if prev is not None else "")))
    cov = num("npl_coverage")
    out.append(check("B3", "NPL coverage", "keep", "flag",
                     "nodata" if cov is None else ("flag" if cov < cb["coverage_min"] else "ok"), cov,
                     "Not recorded yet" if cov is None else f"Reserves {cov:.0f}% of NPL{src}"))
    ldr = num("ldr")
    out.append(check("B4", "Loan-to-deposit ratio", "keep", "flag",
                     "nodata" if ldr is None else ("flag" if ldr > cb["ldr_max"] else "ok"), ldr,
                     "Not recorded yet" if ldr is None else f"LDR {ldr}%{src}" + (f", above {cb['ldr_max']}%" if ldr > cb["ldr_max"] else "")))
    roe = n["ni_ttm"] / n["equity"] * 100 if n["ni_ttm"] is not None and n["equity"] else None
    out.append(check("B5", "Return on equity", "keep", "flag",
                     "nodata" if roe is None else ("flag" if roe < cb["roe_min"] else "ok"), r(roe),
                     "Not enough data" if roe is None else f"ROE {roe:.1f}% over the last 12 months"))
    return out


def ratios(n: dict) -> dict:
    de = n["debt"] / n["equity"] if n["debt"] is not None and n["equity"] else None
    cr = n["current_assets"] / n["current_liabilities"] if n["current_assets"] and n["current_liabilities"] else None
    return {"de": de, "cr": cr}


def sector_compare(f: Fundamentals, n: dict, ctx: Context) -> dict:
    x = ratios(n)
    med = (ctx.sector_medians or {}).get(f.sector)
    if not med or (x["de"] is None and x["cr"] is None):
        return check("10", "Debt/equity and current ratio", "keep", "flag", "nodata", None, "No sector comparison available")
    worse = []
    if x["de"] is not None and med.get("de") is not None and x["de"] > med["de"]:
        worse.append(f"debt/equity {x['de']:.2f} vs sector {med['de']:.2f}")
    if x["cr"] is not None and med.get("cr") is not None and x["cr"] < med["cr"]:
        worse.append(f"current ratio {x['cr']:.2f} vs sector {med['cr']:.2f}")
    # Flag only when both are worse, or the single available one is.
    available = sum(v is not None for v in x.values())
    bad = len(worse) == available and available > 0
    return check("10", "Debt/equity and current ratio", "keep", "flag", "flag" if bad else "ok", r(x["de"], 2),
                 "; ".join(worse) if bad else
                 f"Debt/equity {x['de']:.2f}, current ratio {x['cr']:.2f}" if x["de"] is not None and x["cr"] is not None
                 else "Within sector norms")


# ------------------------------------------------------------- projection

def projection(f: Fundamentals, prices: PriceData, numbers: dict, ticker: str, fx: float | None, ctx: Context) -> dict:
    """Projected dividend and forward yield (the Projection layer)."""
    pol = ctx.policies.get(ticker) or {}
    if pol.get("payout_policy_pct"):
        payout, basis = min(float(pol["payout_policy_pct"]), 100.0), "stated policy"
    elif numbers["payout_history"]:
        hist = numbers["payout_history"][:5]
        payout, basis = min(sum(hist) / len(hist), 100.0), f"{len(hist)}-year average payout"
    else:
        return {}
    ni, shares = numbers["ni_ttm"], f.shares
    price = float(prices.close.iloc[-1])
    if not ni or not shares or fx is None or ni <= 0:
        return {"payout_used": payout, "payout_basis": basis}
    eps = ni * fx / shares
    dps = eps * payout / 100
    tax = ctx.cfg["tax"]["dividend"] / 100
    fwd = dps / price * 100
    return {"payout_used": round(payout, 1), "payout_basis": basis, "eps": eps, "dps": dps,
            "forward_yield": fwd, "forward_yield_after_tax": fwd * (1 - tax)}


# ------------------------------------------------------------- filter 3

def ladder(after_tax_yield: float, ctx: Context) -> dict:
    mk, tx = ctx.cfg["market"], ctx.cfg["tax"]
    rungs = [
        ("Deposit", mk["deposit_rate"] * (1 - tx["deposit"] / 100)),
        ("SBN 10Y", mk["sbn_10y"] * (1 - tx["bond"] / 100)),
        ("AAA bond", mk["corp_aaa"] * (1 - tx["bond"] / 100)),
        ("A bond", mk["corp_a"] * (1 - tx["bond"] / 100)),
        ("BBB bond", mk["corp_bbb"] * (1 - tx["bond"] / 100)),
    ]
    beaten = [name for name, y in rungs if after_tax_yield > y]
    return {"highest": beaten[-1] if beaten else "None", "rungs": [{"name": n, "after_tax": round(y, 2)} for n, y in rungs]}


def filter3(prices: PriceData, proj: dict, sector: str, ticker: str, ctx: Context) -> tuple[list[dict], dict]:
    c3, mk = ctx.cfg["filter3"], ctx.cfg["market"]
    tax = ctx.cfg["tax"]["dividend"]
    close3 = m.window(prices.close, c3["lookback_years"])
    vol = m.volatility(close3)
    b_mkt = m.beta(close3, m.window(ctx.market_returns, c3["lookback_years"]))
    peers = (ctx.sector_returns or {}).get(sector, {})
    others = [s for t, s in peers.items() if t != ticker]
    b_sec = None
    if len(others) >= 3:
        sector_index = pd.concat(others, axis=1).mean(axis=1, skipna=True)
        b_sec = m.beta(close3, m.window(sector_index, c3["lookback_years"]))
    mdd = m.max_drawdown(close3)
    tr3 = m.total_return_after_tax(prices.close, prices.dividends, 3, tax)
    rec = m.ex_date_recovery(prices.close, prices.dividends, 5, c3["recovery_days_flag"])

    out = []
    fwd = proj.get("forward_yield_after_tax")
    required = mk["sbn_10y"] + c3["k"] * vol if vol is not None else None
    if fwd is None or required is None:
        out.append(check("15", "Excess yield", "risk", "gate", "nodata", r(fwd, 2),
                         "Cannot project next dividend" if fwd is None else "Not enough price history"))
    else:
        ok = fwd > required
        out.append(check("15", "Excess yield", "risk", "gate", "pass" if ok else "fail", r(fwd, 2),
                         f"Forward yield after tax {fwd:.1f}% vs required {required:.1f}% "
                         f"(SBN {mk['sbn_10y']}% + {c3['k']} x {vol:.0f}% volatility)"))
    lad = ladder(fwd, ctx) if fwd is not None else None
    out.append(check("16", "Bond ladder rung", "risk", "info", "info", lad["highest"] if lad else None,
                     f"Highest rung beaten after tax: {lad['highest']}" if lad else "No forward yield"))
    out.append(check("17", "Beta", "risk", "info", "info", r(b_mkt, 2),
                     f"vs IHSG {b_mkt:.2f}" if b_mkt is not None else "Not enough price history"))
    if b_sec is not None:
        out[-1]["detail"] += f"; vs sector peers {b_sec:.2f} ({len(others)} peers, equal-weighted)"
    out.append(check("18", "Volatility and max drawdown", "risk", "info", "info", r(vol),
                     f"Volatility {vol:.0f}% a year; worst fall {mdd:.0f}% in {c3['lookback_years']} years"
                     if vol is not None and mdd is not None else "Not enough price history"))
    reasons = []
    if tr3 is not None and tr3 < mk["sbn_10y"]:
        reasons.append(f"3-year total return after tax {tr3:.1f}% a year, below SBN {mk['sbn_10y']}%")
    if rec["median_days"] is not None and rec["median_days"] > c3["recovery_days_flag"]:
        reasons.append(f"ex-date drop takes {rec['median_days']:.0f} trading days to recover (median of {len(rec['events'])})")
    if tr3 is None and rec["median_days"] is None:
        out.append(check("19", "Return check", "risk", "flag", "nodata", None, "Not enough history"))
    else:
        out.append(check("19", "Return check", "risk", "flag", "flag" if reasons else "ok", r(tr3),
                         "; ".join(reasons) or
                         (f"3-year total return after tax {tr3:.1f}% a year" if tr3 is not None else "")
                         + (f"; ex-date recovery {rec['median_days']:.0f} days" if rec["median_days"] is not None else "")))
    sharpe = (fwd - mk["sbn_10y"]) / vol if fwd is not None and vol else None
    return out, {"volatility": vol, "beta": b_mkt, "beta_sector": b_sec, "max_drawdown": mdd,
                 "total_return_3y": tr3, "recovery": rec, "required_yield": required,
                 "sharpe": sharpe, "ladder": lad, "drop_from_high": m.drop_from_high(prices.close)}


# ------------------------------------------------------------- verdict

GATE_ORDER = ["1", "4", "5", "6", "B1", "15"]


def verdict(checks: list[dict], numbers: dict, risk: dict, ctx: Context) -> dict:
    by_id = {c["id"]: c for c in checks}
    for gid in GATE_ORDER:
        c = by_id.get(gid)
        if c and c["status"] == "fail":
            return {"passed": False, "tier": None, "failed": {"id": gid, "name": c["name"], "detail": c["detail"]},
                    "flags": [], "opportunity": False}
    flags = [{"id": c["id"], "name": c["name"], "detail": c["detail"]} for c in checks
             if c["status"] == "flag" or c.get("flag")]
    flags += [{"id": c["id"], "name": f"No data: {c['name']}", "detail": c["detail"]}
              for c in checks if c["kind"] == "gate" and c["status"] == "nodata"]
    k = len(flags)
    tier = "A" if k == 0 else ("B" if k <= 2 else "C")
    ytd = numbers.get("ytd")
    opp = (ytd is not None and ytd.get("pct") is not None and ytd["pct"] >= 0
           and numbers.get("earnings_quality_ok")
           and risk.get("drop_from_high") is not None
           and risk["drop_from_high"] < -ctx.cfg["opportunity"]["drop_from_high"])
    return {"passed": True, "tier": tier, "failed": None, "flags": flags, "opportunity": bool(opp)}
