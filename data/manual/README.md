# Hand-maintained data

These files fill gaps that free data feeds do not cover. Leave a file with
only its header row if you have nothing to add; the scanner then shows the
check as "no data" instead of judging.

| File | Used by | Columns |
|---|---|---|
| `banks.csv` | Bank track B1 to B4 | `car`, `npl_gross`, `npl_gross_prev`, `npl_coverage`, `ldr` in percent, from each bank's quarterly *laporan keuangan publikasi* |
| `policies.csv` | Check 11 (dividend policy) and the projected dividend | `payout_policy_pct` is the stated payout policy; `last_payout_kept_policy` is `yes` or `no` |
| `ratings.csv` | Check 14 (bond rating) | `direction` is `downgrade`, `upgrade` or blank; `outlook` is `negative`, `stable` or `positive`; `changed` is a date |
| `sectors.csv` | Overrides the sector Yahoo reports | `sector` uses IDX-IC names, for example `Banks` or `Energy` |
| `tickers.txt` | Fallback universe if the Yahoo screener fails | one IDX code per line, without `.JK` |

Tickers are IDX codes without the `.JK` suffix, for example `BBCA`.
