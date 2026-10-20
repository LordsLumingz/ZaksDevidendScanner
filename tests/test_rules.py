import pandas as pd
import pytest

from scanner import rules
from scanner.pipeline import load_config
from scanner.providers import Fundamentals, PriceData

ASOF = pd.Timestamp("2026-10-16")


def ctx(**kw):
    base = dict(cfg=load_config(), asof=ASOF, market_returns=pd.Series(dtype=float),
                banks={}, policies={}, ratings={})
    base.update(kw)
    return rules.Context(**base)


def prices(div_years=(2023, 2024, 2025, 2026), price=1000.0, dps=50.0):
    idx = pd.bdate_range("2022-01-03", ASOF)
    divs = pd.Series({pd.Timestamp(f"{y}-05-20"): dps for y in div_years}, dtype=float)
    return PriceData(close=pd.Series(price, index=idx), dividends=divs)


def statements(ni=100.0, div_paid=60.0, fcf=120.0, prev_ni=None, bank=False):
    qs = pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"])
    prev_ni = ni if prev_ni is None else prev_ni
    q_ni = [ni / 4, ni / 4, prev_ni / 4, prev_ni / 4, prev_ni / 4, prev_ni / 4]
    q_inc = pd.DataFrame({q: {"Net Income Common Stockholders": v, "Operating Income": v * 1.3,
                               "EBITDA": v * 1.8, "Interest Expense": v * 0.1} for q, v in zip(qs, q_ni)})
    q_cash = pd.DataFrame({q: {"Free Cash Flow": fcf / 4, "Cash Dividends Paid": -div_paid / 4} for q in qs})
    ys = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31"])
    a_inc = pd.DataFrame({y: {"Net Income Common Stockholders": prev_ni, "Operating Income": prev_ni * 1.3} for y in ys})
    a_cash = pd.DataFrame({y: {"Cash Dividends Paid": -div_paid, "Operating Cash Flow": fcf * 1.2} for y in ys})
    bal = pd.DataFrame({qs[0]: {"Total Debt": 50.0, "Cash And Cash Equivalents": 20.0, "Stockholders Equity": 500.0,
                                "Current Assets": 200.0, "Current Liabilities": 100.0}})
    return Fundamentals(name="Test", sector="Financial Services" if bank else "Industrials",
                        industry="Banks - Regional" if bank else "Machinery", shares=1.0,
                        q_income=q_inc, a_income=a_inc, q_cash=q_cash, a_cash=a_cash, q_balance=bal)


def by_id(checks):
    return {c["id"]: c for c in checks}


def test_filter1_needs_latest_year_and_two_of_three():
    assert rules.filter1(prices(), ctx())[0]["status"] == "pass"
    stopped = prices(div_years=(2021, 2022, 2023, 2024))
    assert rules.filter1(stopped, ctx())[0]["status"] == "fail"
    one_off = prices(div_years=(2026,))
    assert rules.filter1(one_off, ctx())[0]["status"] == "fail"


def test_cnma_style_payout_over_100_fails_gate_4():
    checks, _ = rules.filter2(statements(ni=100, div_paid=166), prices(), "CNMA", ctx())
    c = by_id(checks)["4"]
    assert c["status"] == "fail" and c["value"] == 166


def test_payout_between_80_and_100_is_flagged_not_failed():
    checks, _ = rules.filter2(statements(ni=100, div_paid=87, fcf=200), prices(), "X", ctx())
    c = by_id(checks)["4"]
    assert c["status"] == "pass" and c.get("flag") is True


def test_loss_making_payer_fails_payout():
    checks, _ = rules.filter2(statements(ni=-10, div_paid=20), prices(), "X", ctx())
    assert by_id(checks)["4"]["status"] == "fail"


def test_fcf_below_dividend_fails_gate_5():
    checks, _ = rules.filter2(statements(div_paid=60, fcf=40), prices(), "X", ctx())
    assert by_id(checks)["5"]["status"] == "fail"


def test_profit_drop_over_10_percent_fails_gate_6():
    checks, _ = rules.filter2(statements(ni=80, prev_ni=100), prices(), "X", ctx())
    assert by_id(checks)["6"]["status"] == "fail"


def test_banks_skip_fcf_and_debt_checks_and_use_bank_track():
    banks = {"BMRI": {"period": "1H26", "car": "17.5", "npl_gross": "1.0", "npl_gross_prev": "1.1",
                      "npl_coverage": "235", "ldr": "94.9"}}
    checks, _ = rules.filter2(statements(fcf=-500, bank=True), prices(), "BMRI", ctx(banks=banks))
    c = by_id(checks)
    assert c["5"]["status"] == "skip"
    assert "8" not in c and "9" not in c and "10" not in c
    assert c["B1"]["status"] == "pass"
    assert c["B4"]["status"] == "flag"          # LDR 94.9% > 92%, as in the framework doc
    assert c["B2"]["status"] == "ok" and c["B3"]["status"] == "ok"


def test_bank_with_low_car_fails():
    banks = {"XBNK": {"car": "12"}}
    checks, _ = rules.filter2(statements(bank=True), prices(), "XBNK", ctx(banks=banks))
    v = rules.verdict(checks, {}, {}, ctx())
    assert v["passed"] is False and v["failed"]["id"] == "B1"


def test_tiers_by_flag_count():
    gate = rules.check("1", "Paid", "pays", "gate", "pass")
    flag = lambda i: rules.check(str(i), f"F{i}", "keep", "flag", "flag")
    assert rules.verdict([gate], {}, {}, ctx())["tier"] == "A"
    assert rules.verdict([gate, flag(7), flag(8)], {}, {}, ctx())["tier"] == "B"
    assert rules.verdict([gate, flag(7), flag(8), flag(9)], {}, {}, ctx())["tier"] == "C"


def test_gate_with_no_data_counts_as_flag():
    checks = [rules.check("1", "Paid", "pays", "gate", "pass"), rules.check("5", "FCF", "keep", "gate", "nodata")]
    v = rules.verdict(checks, {}, {}, ctx())
    assert v["passed"] and v["tier"] == "B" and v["flags"][0]["name"] == "No data: FCF"


def test_first_failed_gate_is_reported_in_framework_order():
    checks = [rules.check("15", "Excess yield", "risk", "gate", "fail"), rules.check("4", "Payout", "keep", "gate", "fail")]
    assert rules.verdict(checks, {}, {}, ctx())["failed"]["id"] == "4"


def test_projection_caps_payout_at_100_and_converts_currency():
    f = statements(ni=100, div_paid=60)
    f.shares = 10.0
    numbers = {"payout_history": [150.0, 130.0], "ni_ttm": 100.0}
    p = rules.projection(f, prices(price=1000), numbers, "X", 16000.0, ctx())
    assert p["payout_used"] == 100.0
    assert p["dps"] == pytest.approx(100 * 16000 / 10)


def test_excess_yield_gate_uses_sbn_plus_k_times_volatility():
    c = ctx()
    p = prices(price=1000)
    p.close = p.close * (1 + 0.02 * (pd.Series(range(len(p.close)), index=p.close.index) % 2))
    checks, risk = rules.filter3(p, {"forward_yield_after_tax": 30.0}, "Industrials", "X", c)
    expected = c.cfg["market"]["sbn_10y"] + c.cfg["filter3"]["k"] * risk["volatility"]
    assert risk["required_yield"] == pytest.approx(expected)
    assert by_id(checks)["15"]["status"] == ("pass" if 30.0 > expected else "fail")


def test_ladder_after_tax():
    lad = rules.ladder(7.0, ctx())
    names = [r["name"] for r in lad["rungs"]]
    assert names == ["Deposit", "SBN 10Y", "AAA bond", "A bond", "BBB bond"]
    # SBN 7.20 x 0.9 = 6.48 is beaten; AAA 7.80 x 0.9 = 7.02 is not.
    assert lad["highest"] == "SBN 10Y"


def test_projection_scales_from_dividends_actually_paid():
    # Paid 50/share in May 2026; cash dividends paid in the 12 months to June were 60
    # against profit 100. With a 60% average payout the projection keeps 50/share,
    # whatever share count or currency Yahoo reports.
    f = statements(ni=100, div_paid=60)
    f.shares = 1e-6  # deliberately wrong
    numbers = {"payout_history": [60.0], "ni_ttm": 100.0, "div_paid_ttm": 60.0,
               "div_paid_end": pd.Timestamp("2026-06-30")}
    p = rules.projection(f, prices(price=1000, dps=50), numbers, "X", None, ctx())
    assert p["method"] == "scaled from dividends paid"
    assert p["dps"] == pytest.approx(50.0)
    assert p["forward_yield"] == pytest.approx(5.0)


def test_stock_without_forward_yield_is_not_ranked():
    checks = [rules.check("1", "Paid", "pays", "gate", "pass"), rules.check("4", "Payout", "keep", "gate", "pass"),
              rules.check("15", "Excess yield", "risk", "gate", "nodata", None, "Cannot project next dividend")]
    v = rules.verdict(checks, {}, {}, ctx())
    assert v["passed"] is False and v["failed"]["id"] == "data"


def test_implausible_forward_yield_is_not_scored():
    p = prices(price=1000)
    checks, risk = rules.filter3(p, {"forward_yield_after_tax": 600.0}, "Industrials", "X", ctx())
    c = by_id(checks)["15"]
    assert c["status"] == "nodata" and "data error" in c["detail"]
    assert risk["sharpe"] is None
