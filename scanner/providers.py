"""Where the raw data comes from.

`YahooProvider` reads Yahoo Finance through the yfinance package. Anything
that offers the same methods can replace it, so a licensed feed or IDX's own
files can be swapped in later without touching the rules.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

BANK_INDUSTRIES = {"Banks - Regional", "Banks - Diversified", "Banks"}


@dataclass
class Fundamentals:
    name: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = "IDR"            # currency the share trades in
    financial_currency: str = "IDR"  # currency the reports are in
    shares: float | None = None
    q_income: pd.DataFrame | None = None
    a_income: pd.DataFrame | None = None
    q_cash: pd.DataFrame | None = None
    a_cash: pd.DataFrame | None = None
    q_balance: pd.DataFrame | None = None
    a_balance: pd.DataFrame | None = None

    @property
    def is_bank(self) -> bool:
        return self.industry in BANK_INDUSTRIES or self.sector == "Banks"


@dataclass
class PriceData:
    close: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    dividends: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    def __post_init__(self):
        for name in ("close", "dividends"):
            s = getattr(self, name)
            if not isinstance(s.index, pd.DatetimeIndex):
                s = s.copy()
                s.index = pd.DatetimeIndex(s.index)
                setattr(self, name, s)


def _retry(fn, tries: int = 4, wait: float = 5.0):
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # yfinance raises many kinds
            if i == tries - 1:
                raise
            log.warning("retrying after %s", exc)
            time.sleep(wait * (2 ** i))


class YahooProvider:
    def __init__(self, suffix: str = ".JK", cache_dir: Path | None = None,
                 cache_days: int = 7, pause: float = 0.4):
        import yfinance as yf  # imported here so tests do not need it
        self.yf = yf
        self.suffix = suffix
        self.cache_dir = cache_dir
        self.cache_days = cache_days
        self.pause = pause

    # ---- universe
    def idx_list(self) -> list[str]:
        """Every listed share from IDX's own stock list page."""
        from curl_cffi import requests as creq
        url = "https://www.idx.co.id/primary/StockData/GetSecuritiesStock?start=0&length=9999&code=&sector=&board=&language=en-us"
        res = _retry(lambda: creq.get(url, impersonate="chrome", timeout=30,
                                      headers={"Referer": "https://www.idx.co.id/en/market-data/stocks-data/stock-list"}), tries=3)
        res.raise_for_status()
        rows = res.json().get("data", [])
        return sorted({r["Code"].strip().upper() for r in rows if r.get("Code")})

    def universe(self) -> list[str]:
        from yfinance import EquityQuery
        q = EquityQuery("eq", ["exchange", "JKT"])
        out, offset = [], 0
        while True:
            res = _retry(lambda: self.yf.screen(q, offset=offset, size=250))
            quotes = res.get("quotes", [])
            out += [x["symbol"].removesuffix(self.suffix) for x in quotes
                    if x.get("symbol", "").endswith(self.suffix) and x.get("quoteType", "EQUITY") == "EQUITY"]
            offset += len(quotes)
            if not quotes or offset >= res.get("total", 0):
                break
        return sorted(set(out))

    # ---- prices and dividends, in bulk
    def prices(self, tickers: list[str], start: str = "2013-12-01") -> dict[str, PriceData]:
        """Daily closes and dividends since `start` (early enough for the 2014 vs 2015-16 check)."""
        out: dict[str, PriceData] = {}
        for i in range(0, len(tickers), 80):
            chunk = tickers[i:i + 80]
            symbols = [t + self.suffix for t in chunk]
            df = _retry(lambda: self.yf.download(
                symbols, start=start, interval="1d", auto_adjust=False,
                actions=True, group_by="ticker", progress=False, threads=True))
            for t, s in zip(chunk, symbols):
                try:
                    sub = df[s] if isinstance(df.columns, pd.MultiIndex) else df
                except KeyError:
                    continue
                close = sub["Close"].dropna()
                if close.empty:
                    continue
                divs = sub["Dividends"].fillna(0) if "Dividends" in sub else pd.Series(dtype=float)
                close.index = pd.to_datetime(close.index).tz_localize(None)
                divs.index = pd.to_datetime(divs.index).tz_localize(None)
                out[t] = PriceData(close=close.astype(float), dividends=divs[divs > 0].astype(float))
            time.sleep(self.pause)
        return out

    def index_close(self, symbol: str, years: int = 4) -> pd.Series:
        df = _retry(lambda: self.yf.download(symbol, period=f"{years}y", auto_adjust=False, progress=False))
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.dropna().astype(float)

    def fx_to_idr(self, currency: str) -> float | None:
        if currency in ("IDR", "", None):
            return 1.0
        s = self.index_close(f"{currency}IDR=X", years=1)
        return float(s.iloc[-1]) if len(s) else None

    # ---- statements, cached on disk because they change only each quarter
    def fundamentals(self, ticker: str) -> Fundamentals:
        cached = self._read_cache(ticker)
        if cached is not None:
            return cached
        t = self.yf.Ticker(ticker + self.suffix)
        info = _retry(lambda: t.info) or {}
        f = Fundamentals(
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector", "") or "",
            industry=info.get("industry", "") or "",
            currency=info.get("currency", "IDR") or "IDR",
            financial_currency=info.get("financialCurrency", "IDR") or "IDR",
            shares=info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
        )
        for attr, prop in [("q_income", "quarterly_income_stmt"), ("a_income", "income_stmt"),
                           ("q_cash", "quarterly_cashflow"), ("a_cash", "cashflow"),
                           ("q_balance", "quarterly_balance_sheet"), ("a_balance", "balance_sheet")]:
            try:
                setattr(f, attr, _retry(lambda: getattr(t, prop), tries=2))
            except Exception as exc:
                log.warning("%s %s: %s", ticker, prop, exc)
        self._write_cache(ticker, f)
        time.sleep(self.pause)
        return f

    def _cache_path(self, ticker: str) -> Path | None:
        return self.cache_dir / f"{ticker}.json" if self.cache_dir else None

    def _read_cache(self, ticker: str) -> Fundamentals | None:
        p = self._cache_path(ticker)
        if not p or not p.exists() or time.time() - p.stat().st_mtime > self.cache_days * 86400:
            return None
        return fundamentals_from_json(json.loads(p.read_text()))

    def _write_cache(self, ticker: str, f: Fundamentals) -> None:
        p = self._cache_path(ticker)
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(fundamentals_to_json(f)))


FRAMES = ["q_income", "a_income", "q_cash", "a_cash", "q_balance", "a_balance"]


def fundamentals_to_json(f: Fundamentals) -> dict:
    d = {k: getattr(f, k) for k in ["name", "sector", "industry", "currency", "financial_currency", "shares"]}
    for k in FRAMES:
        df = getattr(f, k)
        if df is not None and not df.empty:
            df = df.copy()
            df.columns = [pd.Timestamp(c).strftime("%Y-%m-%d") for c in df.columns]
            d[k] = json.loads(df.to_json(orient="split"))
    return d


def fundamentals_from_json(d: dict) -> Fundamentals:
    f = Fundamentals(**{k: d.get(k) for k in ["name", "sector", "industry", "currency", "financial_currency", "shares"]})
    for k in FRAMES:
        if d.get(k):
            s = d[k]
            df = pd.DataFrame(s["data"], index=s["index"], columns=pd.to_datetime(s["columns"]))
            setattr(f, k, df)
    return f
