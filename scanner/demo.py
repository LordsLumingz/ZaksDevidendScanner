"""Made-up companies for trying the site and the tests without network access.

None of these tickers or numbers are real. The site shows a DEMO banner
whenever this provider produced the data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .providers import Fundamentals, PriceData

END = pd.Timestamp("2026-10-16")

# ticker, sector, industry, start price, drift %/yr, vol %/yr, dps per year, net income (bn), fcf (bn),
# yoy profit change %, shares (bn), currency of reports, special case
COMPANIES = [
    ("XBNK", "Financial Services", "Banks - Regional", 5000, 4, 22, 380, 50_000, -5_000, 8, 90, "IDR", "bank"),
    ("XBNB", "Financial Services", "Banks - Regional", 4200, 2, 26, 290, 20_000, -3_000, 4, 37, "IDR", "bank"),
    ("XTEL", "Communication Services", "Telecom Services", 3600, 1, 20, 180, 24_000, 30_000, 3, 99, "IDR", ""),
    ("XCON", "Consumer Defensive", "Packaged Foods", 9000, 5, 18, 320, 10_000, 12_000, 9, 11, "IDR", ""),
    ("XCOA", "Energy", "Thermal Coal", 2600, -6, 38, 400, 20_000, 22_000, -4, 11, "IDR", ""),
    ("XMIN", "Energy", "Thermal Coal", 14000, -2, 34, 2100, 18_000, 19_000, -2, 1.1, "IDR", ""),
    ("XGAS", "Utilities", "Utilities - Regulated Gas", 1600, -3, 30, 120, 300, 500, -37, 24, "USD", ""),
    ("XROT", "Consumer Defensive", "Packaged Foods", 900, -12, 28, 75, 300, 330, -15, 6, "IDR", "overpay"),
    ("XNMA", "Consumer Cyclical", "Department Stores", 160, -20, 40, 12, 600, 700, -30, 83, "IDR", "overpay"),
    ("XPRP", "Real Estate", "Real Estate - Development", 450, 3, 32, 0, 1_500, 800, 5, 48, "IDR", "nodiv"),
    ("XCEM", "Basic Materials", "Building Materials", 6500, -8, 27, 180, 2_200, 3_000, 12, 6, "IDR", "dip"),
    ("XAUT", "Consumer Cyclical", "Auto Parts", 1800, 6, 24, 110, 1_700, 1_600, 6, 5, "IDR", ""),
    ("XPLT", "Consumer Defensive", "Farm Products", 1100, 0, 29, 60, 900, 1_100, 2, 7, "IDR", ""),
    ("XTOW", "Communication Services", "Telecom Services", 700, -4, 25, 25, 3_400, 6_000, 1, 51, "IDR", "debt"),
]


def _quarters(n=6):
    return [pd.Timestamp(f"{y}-{mo:02d}-{d}") for y, mo, d in
            [(2026, 6, 30), (2026, 3, 31), (2025, 12, 31), (2025, 9, 30), (2025, 6, 30), (2025, 3, 31)]][:n]


def _years(n=4):
    return [pd.Timestamp(f"{y}-12-31") for y in (2025, 2024, 2023, 2022)][:n]


class DemoProvider:
    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.companies = {c[0]: c for c in COMPANIES}

    def idx_list(self):
        return sorted(self.companies) + ["XNOD"]  # XNOD: listed, but no price data

    def universe(self):
        return sorted(self.companies)

    def prices(self, tickers, start="2013-12-01"):
        out = {}
        dates = pd.bdate_range(pd.Timestamp(start), END)
        for t in tickers:
            if t not in self.companies:
                continue
            c = self.companies[t]
            _, _, _, p0, drift, vol, dps, *_ , case = c
            if case == "dip":
                drift = 4
            daily = self.rng.normal(drift / 100 / 250, vol / 100 / np.sqrt(250), len(dates))
            close = pd.Series(p0 * np.exp(np.cumsum(daily)), index=dates)
            if case == "dip":
                close.iloc[-120:] *= np.linspace(1, 0.72, 120)
            divs = {}
            if case != "nodiv":
                for y in range(dates[0].year + 1, END.year + 1):
                    ex = pd.Timestamp(f"{y}-05-20")
                    if ex > END:
                        continue
                    pos = close.index.searchsorted(ex)
                    if pos >= len(close):
                        continue
                    ex = close.index[pos]
                    amount = dps * (1 + 0.04 * (y - END.year))
                    if case == "overpay" and y < 2023:
                        amount *= 0.6
                    if y in (2016, 2020) and c[1] == "Energy":
                        amount *= 0.5
                    amount = min(amount, close[ex] * 0.15)
                    divs[ex] = amount
                    close.loc[ex:] *= 1 - amount / close[ex]  # price drops by the dividend on ex-date
            factor = p0 / close.iloc[-1]  # end at the listed price so yields look realistic
            close = (close * factor).clip(lower=1).round(0)
            divs = {d: round(v * factor, 1) for d, v in divs.items()}
            out[t] = PriceData(close=close, dividends=pd.Series(divs, dtype=float))
        return out

    def index_close(self, symbol, years=4):
        dates = pd.bdate_range(END - pd.DateOffset(years=years), END)
        r = np.random.default_rng(1).normal(0.03 / 250, 0.14 / np.sqrt(250), len(dates))
        return pd.Series(7000 * np.exp(np.cumsum(r)), index=dates)

    def fx_to_idr(self, currency):
        return {"IDR": 1.0, "USD": 16_400.0}.get(currency)

    def fundamentals(self, t):
        c = self.companies[t]
        tk, sector, industry, p0, drift, vol, dps, ni, fcf, yoy, shares, ccy, case = c
        unit = 1e9 if ccy == "IDR" else 1e6
        shares_n = shares * 1e9
        fx = 16_400.0 if ccy == "USD" else 1.0
        dps_now = dps
        payout = {"overpay": 1.6, "bank": 0.6}.get(case, 0.7 if sector == "Energy" else 0.55)
        if dps_now:
            ni = dps_now * shares_n / fx / unit / payout
        qs, ys = _quarters(), _years()
        growth = 1 + yoy / 100
        q_ni = [ni / 4 * (growth if q.year == 2026 else 1) for q in qs]
        a_ni = [ni / growth ** 0, ni / growth * 0.97, ni / growth * 0.93, ni / growth * 0.9]
        if case == "dip":
            a_ni = [ni, ni * 0.9, ni * 0.85, ni * 0.8]
        div_paid = dps_now * shares_n / fx / unit
        q_inc = pd.DataFrame({
            q: {"Net Income Common Stockholders": v * unit, "Operating Income": v * 1.3 * unit,
                "EBITDA": v * 1.8 * unit, "Interest Expense": v * (0.6 if case == "debt" else 0.1) * unit}
            for q, v in zip(qs, q_ni)})
        a_inc = pd.DataFrame({
            y: {"Net Income Common Stockholders": v * unit, "Operating Income": v * 1.3 * unit,
                "EBITDA": v * 1.8 * unit, "Interest Expense": v * 0.1 * unit,
                "Gross Profit": v * 3 * unit * (1 - 0.02 * i if case == "dip" else 1), "Total Revenue": v * 8 * unit}
            for i, (y, v) in enumerate(zip(ys, a_ni))})
        q_cash = pd.DataFrame({q: {"Free Cash Flow": fcf / 4 * unit, "Cash Dividends Paid": -div_paid / 4 * unit}
                               for q in qs})
        a_cash = pd.DataFrame({y: {"Free Cash Flow": fcf * unit, "Operating Cash Flow": fcf * 1.4 * unit,
                                   "Cash Dividends Paid": -div_paid * (0.96 ** i) * unit}
                               for i, y in enumerate(ys)})
        debt_mult = 6 if case == "debt" else 1
        q_bal = pd.DataFrame({qs[0]: {"Total Debt": ni * debt_mult * unit, "Cash And Cash Equivalents": ni * 0.5 * unit,
                                      "Stockholders Equity": ni * 6 * unit, "Current Assets": ni * 2 * unit,
                                      "Current Liabilities": ni * 1.4 * unit}})
        return Fundamentals(name=f"{tk} Demo Company Tbk", sector=sector, industry=industry, currency="IDR",
                            financial_currency=ccy, shares=shares_n, q_income=q_inc, a_income=a_inc,
                            q_cash=q_cash, a_cash=a_cash, q_balance=q_bal, a_balance=None)
