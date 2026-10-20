"""Run the whole scan and write the site's data files.

    python -m scanner.pipeline            # live scan from Yahoo Finance
    python -m scanner.pipeline --demo     # made-up data, for trying the site offline
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import metrics as m
from . import rules
from .providers import Fundamentals, PriceData

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("scanner")


def load_config(path: Path = ROOT / "config" / "settings.toml") -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_csv(name: str) -> dict:
    p = ROOT / "data" / "manual" / name
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as fh:
        return {row["ticker"].strip().upper(): row for row in csv.DictReader(fh) if row.get("ticker")}


def fallback_tickers() -> list[str]:
    p = ROOT / "data" / "manual" / "tickers.txt"
    return [ln.strip().upper() for ln in p.read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def clean(o):
    """Make numpy and pandas values JSON-safe."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, (pd.Series, pd.DataFrame)):
        return None
    return o


def scan(provider, cfg: dict, demo: bool = False) -> dict:
    t0 = time.time()
    uc = cfg["universe"]
    # The universe is the union of every list we can get, so one source
    # missing a ticker does not drop it from the scan.
    sources: dict[str, int] = {}
    universe_set: set[str] = set()
    for label, fn in [("IDX stock list", getattr(provider, "idx_list", None)),
                      ("Yahoo Finance screener", provider.universe),
                      ("data/manual/tickers.txt", None if demo else fallback_tickers)]:
        if fn is None:
            continue
        try:
            got = fn()
        except Exception as exc:
            log.warning("%s failed: %s", label, exc)
            got = []
        sources[label] = len(got)
        universe_set.update(got)
    universe = sorted(universe_set)
    if uc.get("limit"):
        universe = universe[: uc["limit"]]
    source = ", ".join(f"{k} ({v})" for k, v in sources.items() if v)
    log.info("universe: %d tickers from %s", len(universe), source)

    prices = provider.prices(universe)
    market = provider.index_close(uc["market_index"])
    asof = market.index.max() if len(market) else pd.Timestamp.today().normalize()
    sectors_override = load_csv("sectors.csv")
    ctx = rules.Context(cfg=cfg, asof=asof, market_returns=m.daily_returns(market),
                        banks=load_csv("banks.csv"), policies=load_csv("policies.csv"),
                        ratings=load_csv("ratings.csv"))

    cards: dict[str, dict] = {}
    pass1: list[str] = []
    for t in universe:
        p = prices.get(t)
        if p is None or p.close.empty:
            cards[t] = {"ticker": t, "name": t, "sector": "", "is_bank": False, "stage": 0,
                        "price": None, "price_date": None, "checks": [],
                        "verdict": {"passed": False, "tier": None, "flags": [], "opportunity": False,
                                    "failed": {"id": "data", "name": "No price data",
                                               "detail": "Yahoo Finance has no price history for this ticker"}}}
            continue
        f1 = rules.filter1(p, ctx)
        cards[t] = {"ticker": t, "name": t, "sector": "", "is_bank": False, "stage": 1,
                    "price": float(p.close.iloc[-1]), "price_date": p.close.index.max(),
                    "checks": f1, **{k: v for k, v in rules.yields(p, ctx).items() if k != "price"}}
        if f1[0]["status"] == "pass":
            pass1.append(t)
    log.info("filter 1: %d of %d pay dividends", len(pass1), len(cards))

    funds: dict[str, Fundamentals] = {}
    for i, t in enumerate(pass1):
        try:
            f = provider.fundamentals(t)
        except Exception as exc:
            log.warning("%s fundamentals failed: %s", t, exc)
            continue
        ov = sectors_override.get(t)
        if ov and ov.get("sector"):
            f.sector = ov["sector"].strip()
        funds[t] = f
        if (i + 1) % 25 == 0:
            log.info("fundamentals %d/%d", i + 1, len(pass1))

    # Sector norms (check 10) and equal-weighted sector peer returns (beta vs sector).
    by_sector: dict[str, list] = {}
    ctx.sector_returns = {}
    for t, f in funds.items():
        if not f.is_bank:
            by_sector.setdefault(f.sector, []).append(rules.ratios(rules.statement_numbers(f)))
        ctx.sector_returns.setdefault(f.sector, {})[t] = m.daily_returns(
            m.window(prices[t].close, cfg["filter3"]["lookback_years"]))
    ctx.sector_medians = {s: {"de": m.median(x["de"] for x in v), "cr": m.median(x["cr"] for x in v)}
                          for s, v in by_sector.items() if len(v) >= 3}

    fx_cache: dict[str, float | None] = {}
    for t, f in funds.items():
        p = prices[t]
        card = cards[t]
        card.update(name=f.name, sector=f.sector or "Unclassified", industry=f.industry,
                    is_bank=f.is_bank, stage=2, financial_currency=f.financial_currency)
        try:
            f2, numbers = rules.filter2(f, p, t, ctx)
            if f.financial_currency not in fx_cache:
                fx_cache[f.financial_currency] = provider.fx_to_idr(f.financial_currency)
            proj = rules.projection(f, p, numbers, t, fx_cache[f.financial_currency], ctx)
            f3, risk = rules.filter3(p, proj, f.sector, t, ctx)
        except Exception as exc:  # one bad statement must not stop the scan
            log.exception("%s evaluation failed: %s", t, exc)
            card["error"] = str(exc)
            continue
        card["checks"] += f2 + f3
        card["_numbers"] = numbers
        card.update(stage=3, payout=numbers["payout"], payout_history=numbers["payout_history"],
                    projection=proj, risk=risk, chart=m.weekly_closes(p.close),
                    dividends=[[d.strftime("%Y-%m-%d"), float(v)] for d, v in p.dividends.items()][-20:])

    for card in cards.values():
        if card["stage"] == 0:
            continue
        card["verdict"] = rules.verdict(card["checks"], card.pop("_numbers", {}), card.get("risk", {}), ctx)
        if card["stage"] < 3 and card["verdict"]["passed"]:
            # Passed filter 1 but no statements could be read: not rankable.
            card["verdict"] = {"passed": False, "tier": None, "flags": [], "opportunity": False,
                               "failed": {"id": "data", "name": "No financial data",
                                          "detail": card.get("error") or "Financial statements could not be read"}}

    ranked = sorted((c for c in cards.values() if c["verdict"]["passed"]),
                    key=lambda c: (c["verdict"]["tier"], -(c["risk"].get("sharpe") or -99)))
    for i, c in enumerate(ranked, 1):
        c["rank"] = i

    mk = cfg["market"]
    return clean({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": asof,
        "demo": demo,
        "universe_source": source,
        "universe_sources": sources,
        "runtime_seconds": round(time.time() - t0),
        "settings": {k: cfg[k] for k in ("market", "tax", "filter1", "filter2", "bank", "filter3", "opportunity")},
        "counts": {
            "universe": len(universe), "with_prices": sum(1 for c in cards.values() if c["stage"] > 0),
            "missing_prices": sum(1 for c in cards.values() if c["stage"] == 0), "filter1": len(pass1),
            "filter2_data": len(funds), "passed": len(ranked),
            "tiers": {t: sum(1 for c in ranked if c["verdict"]["tier"] == t) for t in "ABC"},
        },
        "ladder": rules.ladder(0, ctx)["rungs"],
        "stocks": sorted(cards.values(), key=lambda c: (c.get("rank") or 10**6, c["ticker"])),
    })


SNAPSHOT_FIELDS = ["ticker", "rank", "tier", "sharpe", "forward_yield_after_tax", "required_yield",
                   "trailing_yield", "payout", "beta", "volatility", "price", "failed_gate", "flags", "opportunity"]


def snapshot_rows(result: dict) -> list[dict]:
    """One row per dividend payer: the record kept for every scan day."""
    rows = []
    for c in result["stocks"]:
        if c["stage"] < 2:
            continue
        v, r, p = c["verdict"], c.get("risk") or {}, c.get("projection") or {}
        rows.append({
            "ticker": c["ticker"], "rank": c.get("rank"), "tier": v["tier"],
            "sharpe": r.get("sharpe"), "forward_yield_after_tax": p.get("forward_yield_after_tax"),
            "required_yield": r.get("required_yield"), "trailing_yield": c.get("trailing_yield"),
            "payout": c.get("payout"), "beta": r.get("beta"), "volatility": r.get("volatility"),
            "price": c["price"], "failed_gate": (v["failed"] or {}).get("id"),
            "flags": ";".join(f["id"] for f in v["flags"]), "opportunity": int(bool(v["opportunity"])),
        })
    return rows


def write_daily(result: dict, history_dir: Path) -> Path:
    """history/daily/YYYY-MM-DD.csv, one per scan day; a rerun the same day replaces it."""
    path = history_dir / "daily" / f"{result['asof']}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"# sbn_10y={result['settings']['market']['sbn_10y']}\n"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(header)
        w = csv.DictWriter(fh, fieldnames=SNAPSHOT_FIELDS)
        w.writeheader()
        for row in snapshot_rows(result):
            w.writerow({k: ("" if v is None else (round(v, 4) if isinstance(v, float) else v)) for k, v in row.items()})
    return path


def read_daily(path: Path) -> dict:
    with open(path, newline="", encoding="utf-8") as fh:
        first = fh.readline()
        sbn = float(first.split("=", 1)[1]) if first.startswith("# sbn_10y=") else None
        if sbn is None:
            fh.seek(0)
        stocks = []
        for row in csv.DictReader(fh):
            rec = {}
            for k, v in row.items():
                if v == "":
                    rec[k] = None
                elif k in ("ticker", "tier", "failed_gate", "flags"):
                    rec[k] = v
                elif k in ("rank", "opportunity"):
                    rec[k] = int(float(v))
                else:
                    rec[k] = float(v)
            stocks.append(rec)
    return {"asof": path.stem, "sbn_10y": sbn, "stocks": stocks}


def build_monthly(history_dir: Path, out_dir: Path) -> list[str]:
    """Site history files: the last scan of each month, from the daily snapshots."""
    hist = out_dir / "history"
    hist.mkdir(parents=True, exist_ok=True)
    last_of_month: dict[str, Path] = {}
    for p in sorted((history_dir / "daily").glob("????-??-??.csv")):
        last_of_month[p.stem[:7]] = p
    for month, p in last_of_month.items():
        (hist / f"{month}.json").write_text(json.dumps(read_daily(p), separators=(",", ":")))
    months = sorted(last_of_month)
    (hist / "index.json").write_text(json.dumps(months))
    return months


def write(result: dict, out_dir: Path, history_dir: Path = ROOT / "history") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scan.json").write_text(json.dumps(result, separators=(",", ":")))
    if not result["demo"]:
        write_daily(result, history_dir)
    build_monthly(history_dir, out_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", action="store_true", help="use made-up data instead of Yahoo Finance")
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "data")
    ap.add_argument("--limit", type=int, default=None, help="scan only the first N tickers")
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache" / "fundamentals")
    ap.add_argument("--history", type=Path, default=ROOT / "history", help="where the daily snapshots are kept")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if args.limit is not None:
        cfg["universe"]["limit"] = args.limit
    if args.demo:
        from .demo import DemoProvider
        provider = DemoProvider()
    else:
        from .providers import YahooProvider
        provider = YahooProvider(suffix=cfg["universe"]["suffix"], cache_dir=args.cache)
    result = scan(provider, cfg, demo=args.demo)
    c = result["counts"]
    log.info("done: %d scanned, %d pass filter 1, %d ranked (A %d, B %d, C %d)",
             c["with_prices"], c["filter1"], c["passed"], c["tiers"]["A"], c["tiers"]["B"], c["tiers"]["C"])
    if c["with_prices"] == 0:
        log.error("no price data at all; not overwriting the site")
        return 1
    write(result, args.out, args.history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
