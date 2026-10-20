import math

import numpy as np
import pandas as pd
import pytest

from scanner import metrics as m


def series(values, start="2023-01-02"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_volatility_of_constant_growth_is_zero():
    s = series(100 * 1.001 ** np.arange(300))
    assert m.volatility(s) == pytest.approx(0, abs=1e-9)


def test_volatility_needs_enough_history():
    assert m.volatility(series([100, 101, 102])) is None


def test_beta_of_a_leveraged_copy():
    rng = np.random.default_rng(0)
    mkt_r = rng.normal(0, 0.01, 500)
    mkt = series(100 * np.exp(np.cumsum(mkt_r)))
    stock = series(100 * np.exp(np.cumsum(2 * mkt_r)))
    assert m.beta(stock, m.daily_returns(mkt)) == pytest.approx(2.0, rel=1e-6)


def test_max_drawdown():
    s = series([100, 120, 60, 90, 130])
    assert m.max_drawdown(s) == pytest.approx(-50.0)


def test_ex_date_recovery_counts_trading_days_until_back_to_pre_ex_close():
    close = series([100, 100, 95, 96, 97, 101, 102] + [102] * 40)
    divs = pd.Series([5.0], index=[close.index[2]])
    rec = m.ex_date_recovery(close, divs)
    assert rec["events"][0] == {"ex_date": close.index[2].strftime("%Y-%m-%d"), "days": 3, "recovered": True}
    assert rec["median_days"] == 3


def test_ex_date_not_recovered_counts_elapsed_days():
    close = series([100, 100] + [90] * 40)
    divs = pd.Series([10.0], index=[close.index[2]])
    ev = m.ex_date_recovery(close, divs)["events"][0]
    assert ev["recovered"] is False and ev["days"] == 40


def test_too_recent_ex_date_is_skipped():
    close = series([100, 100] + [90] * 5)
    divs = pd.Series([10.0], index=[close.index[2]])
    assert m.ex_date_recovery(close, divs)["events"] == []


def test_dividend_record_trend_and_stress():
    divs = pd.Series({pd.Timestamp(f"{y}-05-20"): v for y, v in
                      [(2014, 100), (2015, 50), (2016, 60), (2019, 100), (2020, 80),
                       (2021, 100), (2022, 100), (2023, 130), (2024, 140), (2025, 150)]})
    rec = m.dividend_record(divs, pd.Timestamp("2026-10-16"))
    assert rec["years_paid"] == 8  # 2016..2025, missing 2017 and 2018
    assert rec["stress_2015_16"] == -50.0
    assert rec["stress_2020"] == -20.0
    assert rec["trend"] == "growing"


def test_ttm_requires_four_consecutive_quarters():
    q = pd.Series([1.0, 2.0, 3.0, 4.0],
                  index=pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]))
    assert m.ttm(q) == 10.0
    gap = pd.Series([1.0, 2.0, 3.0, 4.0],
                    index=pd.to_datetime(["2026-06-30", "2026-03-31", "2025-06-30", "2024-12-31"]))
    assert m.ttm(gap) is None


def test_year_to_date_compares_same_period():
    q = pd.Series([60.0, 50.0, 40.0, 30.0, 45.0, 40.0],
                  index=pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31",
                                        "2025-09-30", "2025-06-30", "2025-03-31"]))
    ch = m.year_to_date_change(q, None)
    assert ch["now"] == 110 and ch["then"] == 85
    assert ch["basis"] == "Q2 2026 YTD vs 2025"


def test_year_to_date_falls_back_to_annual():
    a = pd.Series([80.0, 100.0], index=pd.to_datetime(["2025-12-31", "2024-12-31"]))
    ch = m.year_to_date_change(None, a)
    assert ch["pct"] == -20.0


def test_total_return_after_tax():
    close = pd.Series([100.0, 100.0], index=pd.to_datetime(["2023-10-16", "2026-10-16"]))
    divs = pd.Series([10.0, 10.0, 10.0], index=pd.to_datetime(["2024-05-01", "2025-05-01", "2026-05-01"]))
    tr = m.total_return_after_tax(close, divs, 3, 10)
    assert tr == pytest.approx((1.27 ** (1 / 3) - 1) * 100)
