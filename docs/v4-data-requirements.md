# Probora V4 Data Requirements

Updated: 2026-07-31

## What more data can and cannot fix

The current US-equity history contains roughly 12.4 years. A 90-session target therefore has only
about 35 independent, non-overlapping time windows even though the tabular dataset contains more
than 100,000 overlapping asset rows. Adding more stocks improves breadth and sector measurement;
it does not create hundreds of independent macro regimes.

For an uncorrelated binary breadth estimate near 50%, 19 names have an approximate one-standard-
error noise of 11.5 percentage points. About 100 names reduce that to 5 points. A 95% margin of
approximately 5 points requires about 384 names before correlation and finite-population effects.
For that reason the durable breadth target is the full point-in-time S&P 500 membership, not an
arbitrary current list of 100 winners.

The MIT-licensed historical membership snapshot currently contains 734 distinct tickers between
2013-01-02 and 2025-08-23. At the present 3,405-session depth, full price coverage is approximately
2.5 million daily bars. Expected storage is modest (roughly 0.15-0.30 GB compressed Parquet and
1-2 GB in PostgreSQL with indexes); identity, delisting and corporate-action validation is the
hard part.

A daily bar is one security on one trading session, not one calendar day. For example, 734
securities times roughly 3,405 sessions is about 2.5 million rows while the calendar span remains
about 13 years. A causal 2026-07-20 refresh applied only subsequently effective public component
changes and produced a 758-symbol historical union. The 24-symbol difference is an incremental
tail; it does not change the frozen 367 + 367 main bootstrap partition while it is running.

## Free-source decision

### Accepted for the current research step

- Twelve Data Basic: 8 API credits/minute and 800/day; `/time_series` costs one credit per symbol.
- A bounded date range returns at most 5,000 observations, enough for one 2013-present daily symbol.
- `adjust=all` is required to align splits and dividends with the existing equity dataset.
- Five missing long-history sector ETFs were downloaded: XLY, XLP, XLI, XLB and XLU.
- Each contains 3,405 sessions from 2013-01-02 through 2026-07-17; total 17,025 bars.
- Combined with XLK, XLF, XLE and XLV already in Probora, this provides a stable nine-sector panel.

### Not accepted as training truth yet

- Current Nasdaq or S&P member lists replayed backward: survivorship leakage.
- Free Alpaca IEX data as the primary price contract: only one exchange and about 2.5% of US volume;
  its free historical coverage begins in 2016, shorter than the current dataset.
- The 734-symbol bootstrap until delisted symbols, ticker changes, acquisition dates and provider
  coverage have been reconciled against the point-in-time membership file.

## Safe full-universe bootstrap

1. Freeze the MIT membership file and its checksum.
2. Convert each daily membership row to effective membership intervals.
3. Build a security-master alias table for ticker changes; never reuse a ticker as an identity.
4. Probe Twelve Data coverage in resumable daily batches below the shared 800-credit quota.
5. Record unavailable/delisted symbols rather than silently dropping them.
6. Require at least 95% membership-weighted coverage per historical cutoff before computing breadth.
7. Compute breadth only from members effective at that cutoff.
8. Keep full-universe breadth research-only until a second provider or corporate-action audit agrees.

At 8 credits/minute, 734 symbols require at least 91.75 minutes of API time and nearly the entire
free daily quota. It should be bootstrapped over multiple days so the live 20-symbol shadow
collector keeps its retry budget.

### Resumable execution contract

The frozen 734-symbol universe is alphabetically partitioned into two deterministic groups of 367.
State is atomically written after every symbol, successful Parquet files are never downloaded
again, and provider failures are not retried unless `--retry-failed` is explicitly supplied.

```powershell
$env:PYTHONPATH = "ml/src"
.\.venv\Scripts\python.exe -m probora_ml.cli bootstrap-sp500-pit-history --batch 1
.\.venv\Scripts\python.exe -m probora_ml.cli bootstrap-sp500-pit-history --batch 2
```

After the main pass, failed historical tickers can use Twelve Data's official delisted catalog to
resolve an exchange before a bounded retry. This intentionally costs additional catalog/time-series
credits and is never activated during the first pass:

```powershell
.\.venv\Scripts\python.exe -m probora_ml.cli bootstrap-sp500-pit-history `
  --batch 1 --retry-failed --resolve-delisted
```

After both frozen batches finish, the causally refreshed 24-symbol tail can be collected without
repartitioning or repeating completed calls:

```powershell
.\.venv\Scripts\python.exe -m probora_ml.cli refresh-sp500-membership
.\.venv\Scripts\python.exe -m probora_ml.cli bootstrap-sp500-pit-history `
  --membership data/reference/sp500_historical_components.current.csv --batch 1 --batch-count 1
```

The V4.3 build command calls a hard gate. It remains closed unless every model cutoff has at least
95% point-in-time member price coverage and the membership source is no more than 35 days stale:

```powershell
.\.venv\Scripts\python.exe -m probora_ml.cli audit-sp500-pit-coverage `
  --membership data/reference/sp500_historical_components.current.csv --require-ready
.\.venv\Scripts\python.exe -m probora_ml.cli build-equity-sp500-breadth-v43
```

V4.3 predeclares ten features: 1/5/20/60-session positive-return breadth, 20/60-session fractions
above moving averages, 20/60-session return dispersion, and 20/60-session median returns. The
ablation compares broad breadth alone and in combination with the V4.2 sector-peer candidate; the
existing live shadow models are not modified by data collection or research training.

## Statistical acceptance

More rows do not reduce the quality gates:

- historical BSS at least +5%;
- at least two out of three primary fold wins;
- paired block-bootstrap Brier-delta confidence interval entirely below zero;
- ECE at most 5%;
- an unseen live shadow period before production.

The current sector V4.2 gain is about 0.00072 Brier versus base ordinal. Its confidence interval
still crosses zero. At the observed variance and effect size, roughly 7.5 times as much independent
time evidence would be needed for a conventional confidence interval to exclude zero. The practical
answer is therefore a stronger causal signal plus forward evidence, not merely duplicating more
correlated asset rows.

## 2026-07-21 execution result

The two frozen batches and 24-symbol current tail completed with 620 usable histories out of 758.
The point-in-time audit measured 88.52% mean, 78.45% fifth-percentile and 77.44% minimum daily
membership coverage. Current-date coverage was 99.80%, demonstrating why a current-universe check
alone would conceal historical survivorship gaps. Exchange-aware retries of 40 delisted tickers
returned zero additional histories. V4.3 remains blocked; the missing requirement is a licensed
delisted-history source and audited ticker/security alias master, not more model tuning.

## 2026-07-31 Tiingo recovery

An updated MIT membership archive was frozen with its source checksum and license. It contains
2,718 membership rows, 1,206 distinct ticker strings and point-in-time history from 1996-01-02
through 2026-06-30. One later audited local tail row extends the merged reference through
2026-07-20. For the 2013-present V4.3 window, the audited universe contains 794 canonical symbols.

The Tiingo public EOD catalog covers 142 symbols absent from the 620 successful primary histories.
The first delisted smoke symbol, AET, returned 1,739 sessions from 2012-01-03 through 2018-11-28.
Full recovery is resumable, quota-capped, stored in a separate provider state and merged only at
coverage/feature read time. Existing primary files are never overwritten. See
`docs/tiingo-sp500-recovery.md` for the data, quota and license contract.

The recovery completed with 141 successful histories out of 142 Tiingo requests; `NYX` was the
only malformed/unsupported response. A full 2013-present audit still failed the hard gate because
several early historical identities remain unavailable. The complete-period result was 95.37%
mean, 89.38% fifth-percentile and 88.73% minimum daily coverage.

Tiingo's supported-ticker catalog also contained multiple lifecycles for 36 membership symbols.
Those symbols are explicitly listed in `data/reference/sp500_identity_quarantine.csv`; their bars
are excluded and they continue to count as missing in the conservative coverage denominator. No
old ticker is silently mapped to a current company or ETF.

Without looking at model outcomes, the first contiguous suffix satisfying the unchanged 95% gate
under that identity policy begins on 2020-01-28. The qualified audit contains 1,592 sessions through
2026-05-28, with 96.60% mean, 95.25% fifth-percentile, 95.05% minimum and 97.42% latest coverage.
This opens V4.3 for research only; it does not retroactively make the 2013-present gate pass.

```powershell
.\.venv\Scripts\probora-ml.exe audit-sp500-pit-coverage `
  --membership data\reference\sp500_historical_components.audited.csv `
  --coverage-start-date 2020-01-28 `
  --identity-quarantine data\reference\sp500_identity_quarantine.csv `
  --output artifacts\reports\sp500-pit-coverage-v43-qualified.json `
  --require-ready

.\.venv\Scripts\probora-ml.exe build-equity-sp500-breadth-v43 `
  --membership data\reference\sp500_historical_components.audited.csv `
  --coverage-report artifacts\reports\sp500-pit-coverage-v43-qualified.json
```

The audit now binds the exact membership SHA-256 to its coverage contract. Dataset construction
fails closed if that membership file changes, and writes a sidecar metadata file containing the
dataset, coverage-report, membership and identity-quarantine hashes.

## 2026-07-31 V4.3 ablation result

The qualified dataset contains 59,356 rows for 19 US assets: 30,248 at 30 sessions and 29,108 at
90 sessions. It has no duplicate asset/cutoff/horizon keys and no missing or non-finite S&P breadth
features. Full results are recorded in `docs/v4.3-breadth-ablation-2026-07-31.md`.

Broad point-in-time breadth improved point estimates at both horizons but did not pass every
predeclared acceptance gate. The paired Brier-delta confidence intervals versus the base ordinal
model still cross zero, BSS remains below 5%, and no variant is marked shadow eligible. V4.3 is
therefore a promising research candidate, not a production replacement.

## Sources

- Twelve Data pricing: <https://twelvedata.com/pricing>
- Twelve Data historical-data limits: <https://support.twelvedata.com/en/articles/5214728-getting-historical-data>
- Alpaca market-data coverage: <https://docs.alpaca.markets/us/docs/about-market-data-api>
- State Street sector ETF information: <https://www.ssga.com/us/en/individual/etfs/state-street-consumer-discretionary-select-sector-spdr-etf-xly>
- MIT historical membership project: <https://github.com/hanshof/sp500_constituents>
- Updated MIT point-in-time membership archive: <https://github.com/fja05680/sp500>
- Tiingo EOD documentation: <https://www.tiingo.com/documentation/end-of-day>
- Current public component table and changes: <https://en.wikipedia.org/wiki/List_of_S%26P_500_companies>
