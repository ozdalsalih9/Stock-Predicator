# Tiingo S&P 500 history recovery

Tiingo is a secondary, research-only provider for point-in-time S&P 500 breadth. It does not
replace Twelve Data in the live US-equity shadow collector. Its first job is to recover historical
symbols that the primary bootstrap could not resolve.

## Data and license contract

- Authentication uses `Authorization: Token ...`; the token is never placed in a URL or artifact.
- The free/internal-use license does not permit redistribution of raw Tiingo data. Public product
  use requires a separate license review.
- CSV is requested to reduce bandwidth. Raw and adjusted OHLCV, `divCash`, and `splitFactor` are
  retained in each Parquet file.
- Model-facing OHLCV uses Tiingo's split-and-dividend-adjusted fields. Raw values remain available
  for corporate-action audits.
- A completed US session is conservatively available at 20:00 `America/New_York`. Conversion to
  UTC is timezone-aware, so daylight-saving changes are not hard-coded.

## Safety budgets

The defaults deliberately stay below the account allocation:

| Budget | Account allocation | Collector safety limit |
|---|---:|---:|
| Requests/hour | 50 | 45 |
| Requests/day | 1,000 | 900 |
| Unique symbols/month | 500 | 450 |
| Monthly bandwidth | dashboard shows 2 GB | 800 MB |

Usage counters and completed symbols are atomically persisted in
`data/raw-equity/sp500-pit/tiingo-bootstrap-state.json`. A restart skips successful files.
The public supported-ticker archive is cached daily and used to avoid spending API requests on
unsupported symbols.

## Commands

```powershell
.\.venv\Scripts\probora-ml.exe import-sp500-membership-archive `
  C:\path\to\sp500-master.zip

# One-symbol smoke test
.\.venv\Scripts\probora-ml.exe bootstrap-tiingo-sp500-recovery `
  --symbol AET --maximum-symbols 1 --request-interval-seconds 0

# Resume all supported gaps with the safety defaults
.\.venv\Scripts\probora-ml.exe bootstrap-tiingo-sp500-recovery

# Recalculate the hard V4.3 gate
.\.venv\Scripts\probora-ml.exe audit-sp500-pit-coverage `
  --membership data\reference\sp500_historical_components.audited.csv `
  --output artifacts\reports\sp500-pit-coverage-tiingo.json
```

Provider states are merged by canonical symbol. Primary Twelve Data files win when both providers
have the same symbol; Tiingo is used only for missing histories. Share-class punctuation such as
`BF.B` and `BF-B` is canonicalized before coverage and breadth calculations.

Collection alone cannot activate V4.3. The mean, fifth-percentile, and minimum point-in-time
coverage are audited again, and every required cutoff must reach at least 95% before feature
generation or model ablation can proceed.

## Completed recovery and qualified research suffix

The 2026-07-31 run completed 141 of 142 requested Tiingo histories and used 146 total API calls,
including catalog and retry overhead. `NYX` was the only failed history. The unrestricted
2013-present audit remains closed: its minimum daily coverage is 88.73%.

Thirty-six membership symbols have more than one provider lifecycle and are quarantined in
`data/reference/sp500_identity_quarantine.csv`. Quarantined histories are never used in breadth
features and remain missing in the coverage denominator. This protects the research set from cases
such as an old company ticker later being recycled for a different security.

A result-independent coverage audit identified 2020-01-28 as the start of the first contiguous
suffix in which every retained cutoff reaches 95% under this conservative identity policy. The
qualified report is `artifacts/reports/sp500-pit-coverage-v43-qualified.json`. It records the exact
membership and quarantine checksums and is the only report accepted by the V4.3 dataset build.
