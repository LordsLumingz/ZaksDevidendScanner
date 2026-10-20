import json

from scanner import pipeline
from scanner.demo import DemoProvider


def run_demo(tmp_path):
    result = pipeline.scan(DemoProvider(), pipeline.load_config(), demo=True)
    pipeline.write(result, tmp_path / "site", tmp_path / "history")
    return result


def test_demo_scan_end_to_end(tmp_path):
    result = run_demo(tmp_path)
    c = result["counts"]
    assert c["universe"] == 15
    assert c["missing_prices"] == 1          # XNOD is listed but has no prices
    assert c["with_prices"] == 14
    assert c["filter1"] == 13                # XPRP pays nothing
    by_t = {s["ticker"]: s for s in result["stocks"]}
    assert by_t["XNOD"]["verdict"]["failed"]["name"] == "No price data"
    assert by_t["XPRP"]["verdict"]["failed"]["id"] == "1"
    assert by_t["XNMA"]["verdict"]["failed"]["id"] == "4"   # pays 160%+ of profit
    assert by_t["XROT"]["verdict"]["failed"]["id"] == "4"
    ranked = [s for s in result["stocks"] if s.get("rank")]
    assert [s["rank"] for s in ranked] == list(range(1, len(ranked) + 1))
    tiers = [s["verdict"]["tier"] for s in ranked]
    assert tiers == sorted(tiers)            # tiers first, then Sharpe
    data = json.loads((tmp_path / "site" / "scan.json").read_text())
    assert data["demo"] is True
    assert not (tmp_path / "history" / "daily").exists()   # demo data never enters history


def test_daily_history_round_trip_and_monthly_build(tmp_path):
    result = pipeline.scan(DemoProvider(), pipeline.load_config(), demo=True)
    result["demo"] = False
    hist = tmp_path / "history"
    for day in ("2026-09-29", "2026-09-30", "2026-10-16"):
        result["asof"] = day
        pipeline.write_daily(result, hist)
    months = pipeline.build_monthly(hist, tmp_path / "site")
    assert months == ["2026-09", "2026-10"]
    sep = json.loads((tmp_path / "site" / "history" / "2026-09.json").read_text())
    assert sep["asof"] == "2026-09-30"       # last scan of the month
    assert sep["sbn_10y"] == 7.2
    rows = {r["ticker"]: r for r in sep["stocks"]}
    ranked = {s["ticker"]: s["rank"] for s in result["stocks"] if s.get("rank")}
    assert {t: rows[t]["rank"] for t in ranked} == ranked
    assert rows["XNMA"]["failed_gate"] == "4"


def test_statement_cache_round_trip():
    from scanner import rules
    from scanner.providers import fundamentals_from_json, fundamentals_to_json
    f = DemoProvider().fundamentals("XBNK")
    g = fundamentals_from_json(json.loads(json.dumps(fundamentals_to_json(f))))
    a, b = rules.statement_numbers(f), rules.statement_numbers(g)
    for k in ("ni_ttm", "fcf_ttm", "div_paid_ttm", "debt", "equity", "ebitda_ttm"):
        assert a[k] == b[k]
    assert g.is_bank
