"""Pure calculations on price, dividend and statement data.

Nothing here touches the network, so every function can be unit tested
with small hand-made series.
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd

TRADING_DAYS = 250


# ---------------------------------------------------------------- prices

def window(series: pd.Series, years: float, end: pd.Timestamp | None = None) -> pd.Series:
    """The part of a date-indexed series that falls in the last `years` years."""
    if series is None or series.empty:
        return pd.Series(dtype=float)
    end = end or series.index.max()
    start = end - timedelta(days=round(365.25 * years))
    return series[(series.index > start) & (series.index <= end)]


def daily_returns(close: pd.Series) -> pd.Series:
    close = close.dropna()
    close = close[close > 0]
    return np.log(close).diff().dropna()


def volatility(close: pd.Series) -> float | None:
    """Annualised standard deviation of daily log returns, in percent."""
    r = daily_returns(close)
    if len(r) < 60:
        return None
    return float(r.std(ddof=1) * math.sqrt(TRADING_DAYS) * 100)


def beta(close: pd.Series, benchmark_returns: pd.Series) -> float | None:
    """Beta of a stock's daily returns against a benchmark's daily returns."""
    if benchmark_returns is None or benchmark_returns.empty:
        return None
    r = daily_returns(close)
    joined = pd.concat([r, benchmark_returns], axis=1, join="inner").dropna()
    if len(joined) < 60:
        return None
    var = joined.iloc[:, 1].var(ddof=1)
    if not var or var <= 0:
        return None
    return float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var)


def max_drawdown(close: pd.Series) -> float | None:
    """Worst peak-to-bottom fall, in percent (a negative number)."""
    close = close.dropna()
    if len(close) < 2:
        return None
    dd = close / close.cummax() - 1
    return float(dd.min() * 100)


def drop_from_high(close: pd.Series) -> float | None:
    """How far the last price sits below its one-year high, in percent."""
    last_year = window(close.dropna(), 1)
    if last_year.empty:
        return None
    return float((last_year.iloc[-1] / last_year.max() - 1) * 100)


def total_return_after_tax(close: pd.Series, dividends: pd.Series, years: float,
                           tax_pct: float) -> float | None:
    """Annualised price change plus after-tax dividends, in percent.

    Dividends are not reinvested; this is the simple holder's return.
    """
    close = close.dropna()
    if close.empty:
        return None
    end = close.index.max()
    start = end - timedelta(days=round(365.25 * years))
    if close.index.min() > start + timedelta(days=15):
        return None  # not enough history
    p0 = close[close.index <= start + timedelta(days=15)]
    p0 = p0.iloc[-1] if not p0.empty else close.iloc[0]
    divs = dividends[(dividends.index > start) & (dividends.index <= end)].sum() if dividends is not None else 0.0
    growth = (close.iloc[-1] + divs * (1 - tax_pct / 100)) / p0
    if growth <= 0:
        return -100.0
    return float((growth ** (1 / years) - 1) * 100)


def ex_date_recovery(close: pd.Series, dividends: pd.Series, last_n: int = 5,
                     min_days: int = 30) -> dict:
    """Trading days the price took to climb back to its pre-ex-date close.

    For each of the last `last_n` ex-dates that have at least `min_days`
    trading days after them (or already recovered), returns the count.
    A payout that has not recovered is counted as the days elapsed so far
    and marked as not recovered.
    """
    close = close.dropna()
    events = []
    if dividends is None or dividends.empty or close.empty:
        return {"median_days": None, "events": events}
    for ex_date in sorted(dividends.index)[::-1]:
        before = close[close.index < ex_date]
        after = close[close.index >= ex_date]
        if before.empty or after.empty:
            continue
        target = before.iloc[-1]
        hit = np.nonzero(after.values >= target)[0]
        if len(hit):
            days, recovered = int(hit[0]), True
        else:
            days, recovered = len(after), False
            if days < min_days:
                continue  # too recent to judge
        events.append({"ex_date": ex_date.strftime("%Y-%m-%d"), "days": days, "recovered": recovered})
        if len(events) == last_n:
            break
    median = float(np.median([e["days"] for e in events])) if events else None
    return {"median_days": median, "events": events}


def weekly_closes(close: pd.Series, years: float = 3) -> list[list]:
    """Weekly closes for the stock card chart: [[YYYY-MM-DD, price], ...]."""
    w = window(close.dropna(), years).resample("W-FRI").last().dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in w.items()]


# ------------------------------------------------------------- dividends

def dividends_by_year(dividends: pd.Series) -> pd.Series:
    """Dividend per share summed by calendar year of the ex-date."""
    if dividends is None or dividends.empty:
        return pd.Series(dtype=float)
    d = dividends[dividends > 0]
    return d.groupby(d.index.year).sum()


def trailing_dps(dividends: pd.Series, asof: pd.Timestamp, months: int = 12) -> float:
    if dividends is None or dividends.empty:
        return 0.0
    start = asof - pd.DateOffset(months=months)
    return float(dividends[(dividends.index > start) & (dividends.index <= asof)].sum())


def dividend_record(dividends: pd.Series, asof: pd.Timestamp, year_end_prices: pd.Series | None = None) -> dict:
    """The 10-year informational panel."""
    by_year = dividends_by_year(dividends)
    last_full = asof.year - 1
    years = list(range(last_full - 9, last_full + 1))
    paid = [int(y) for y in years if by_year.get(y, 0) > 0]

    def avg(ys):
        vals = [by_year.get(y, 0.0) for y in ys]
        return sum(vals) / len(vals)

    recent, prior = avg(years[-3:]), avg(years[-6:-3])
    if recent == 0 and prior == 0:
        trend = "none"
    elif prior == 0:
        trend = "new"
    elif recent > prior * 1.1:
        trend = "growing"
    elif recent < prior * 0.9:
        trend = "cut"
    else:
        trend = "flat"

    def stress(base, bad):
        b = by_year.get(base, 0.0)
        if b <= 0:
            return None
        worst = min(by_year.get(y, 0.0) for y in bad)
        return round((worst / b - 1) * 100, 1)

    avg_yield = None
    if year_end_prices is not None and not year_end_prices.empty:
        ys = [by_year.get(y, 0.0) / year_end_prices[y] * 100
              for y in years if y in year_end_prices.index and year_end_prices[y] > 0]
        if ys:
            avg_yield = round(sum(ys) / len(ys), 2)

    return {
        "years_paid": len(paid),
        "years_checked": len(years),
        "by_year": {str(y): round(float(by_year.get(y, 0.0)), 2) for y in years},
        "avg_yield": avg_yield,
        "trend": trend,
        "stress_2015_16": stress(2014, [2015, 2016]),
        "stress_2020": stress(2019, [2020]),
    }


def dividend_cagr(dividends: pd.Series, asof: pd.Timestamp, years: int = 5) -> float | None:
    by_year = dividends_by_year(dividends)
    end_y = asof.year - 1
    a, b = by_year.get(end_y - years, 0.0), by_year.get(end_y, 0.0)
    if a <= 0 or b <= 0:
        return None
    return float(((b / a) ** (1 / years) - 1) * 100)


# ------------------------------------------------------------ statements

def row(df: pd.DataFrame | None, *names: str) -> pd.Series | None:
    """First matching line item from a yfinance statement, newest first."""
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            s = pd.to_numeric(df.loc[n], errors="coerce")
            s.index = pd.to_datetime(s.index)
            return s.sort_index(ascending=False)
    return None


def ttm(q: pd.Series | None) -> float | None:
    """Sum of the latest four quarters, only when all four are present."""
    if q is None:
        return None
    q = q.dropna()
    if len(q) < 4:
        return None
    newest = q.index[0]
    last4 = q.iloc[:4]
    if (newest - last4.index[-1]).days > 300:  # gap: quarters missing
        return None
    return float(last4.sum())


def latest(s: pd.Series | None) -> float | None:
    if s is None:
        return None
    s = s.dropna()
    return float(s.iloc[0]) if len(s) else None


def year_to_date_change(q: pd.Series | None, annual: pd.Series | None) -> dict | None:
    """This year's year-to-date total against the same period last year.

    Assumes a December fiscal year, which covers almost all IDX companies.
    Falls back to the latest quarter vs the same quarter last year, then to
    the last two full years.
    """
    if q is not None:
        q = q.dropna()
    if q is not None and len(q):
        newest = q.index[0]
        n = max(1, newest.month // 3)
        cur = [d for d in q.index if d.year == newest.year and d <= newest]
        prev = [d for d in q.index if d.year == newest.year - 1 and d.month <= newest.month]
        if len(cur) == n and len(prev) == n:
            now, then = float(q[cur].sum()), float(q[prev].sum())
            return _change(now, then, f"{'Q' + str(n) if n < 4 else 'FY'} {newest.year} YTD vs {newest.year - 1}")
        same = [d for d in q.index if d.year == newest.year - 1 and d.month == newest.month]
        if same:
            return _change(float(q[newest]), float(q[same[0]]),
                           f"Q{n} {newest.year} vs Q{n} {newest.year - 1}")
    if annual is not None:
        a = annual.dropna()
        if len(a) >= 2:
            return _change(float(a.iloc[0]), float(a.iloc[1]),
                           f"FY{a.index[0].year} vs FY{a.index[1].year}")
    return None


def _change(now: float, then: float, basis: str) -> dict:
    pct = None if then == 0 else (now - then) / abs(then) * 100
    return {"now": now, "then": then, "pct": None if pct is None else round(pct, 1), "basis": basis}


def median(values) -> float | None:
    vals = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return float(np.median(vals)) if vals else None
