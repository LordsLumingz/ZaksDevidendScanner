# IHSG Dividend Hunter

A daily screener for IDX dividend stocks. It looks for companies whose
dividend is likely to keep coming, and only then asks whether the yield pays
enough for the price risk (volatility and beta). The rules follow the
Dividend Scanner Framework: 3 filters of gates, warning flags that never
block, tiers by flag count, and a ranking by dividend Sharpe.

**This is a screener, not investment advice.** The site shows data and
rule-based scores, not recommendations.

## How it runs

```
GitHub Actions (17:30 WIB, Mon-Fri)
  └─ python -m scanner.pipeline
       1. universe: IDX stock list ∪ Yahoo screener ∪ data/manual/tickers.txt
       2. prices + dividends for every ticker            → filter 1 (does it pay?)
       3. statements for dividend payers (cached 1 week) → filter 2 (can it keep paying?)
       4. beta, volatility, drawdown, projected dividend → filter 3 (worth the risk?)
       5. writes site/data/scan.json and history/daily/YYYY-MM-DD.csv
  └─ commits the day's snapshot to history/
  └─ deploys site/ to GitHub Pages
```

The site is plain HTML, CSS and JavaScript in `site/` with no build step, so
it can move to any static host (Cloudflare Pages, Netlify) by pointing that
host at the `site/` folder after a scan.

## Changing the rules

* **Thresholds and benchmark rates:** `config/settings.toml`. Update the SBN,
  deposit and corporate bond yields there by hand (PHEI/IBPA, LPS).
* **Hand-entered data:** `data/manual/` (bank CAR/NPL/LDR, dividend
  policies, bond ratings, sector corrections). See its README.

Commit to `main` and the site rebuilds within the hour; the daily scan picks
it up too. You can also run it by hand: **Actions → Scan and deploy → Run
workflow**.

## History

Every scan day adds one small CSV to `history/daily/` with each dividend
payer's tier, rank, forward yield, Sharpe, price and failed gate. The site's
History page is built from the last snapshot of each month. Raw prices and
statements are never committed.

## Running locally

```bash
pip install -r requirements.txt
python -m pytest -q                  # unit tests
python -m scanner.pipeline --demo    # made-up data, no network needed
python -m scanner.pipeline --limit 30   # live scan of 30 tickers
cd site && python -m http.server     # open http://localhost:8000
```

## Data sources and limits

* Prices, dividends and financial statements: Yahoo Finance via `yfinance`.
  Yahoo usually has 4 years of annual and 5 quarters of quarterly
  statements, so "own history" checks use what is there.
* Stock list: IDX's stock list page, merged with Yahoo's screener.
* Bank capital ratios, dividend policies and bond ratings are not in any
  free feed and are entered by hand in `data/manual/`.
* Sectors are Yahoo's classification unless corrected in
  `data/manual/sectors.csv`.
* Fiscal years are assumed to end in December. USD reporters are converted
  at the current rate.
