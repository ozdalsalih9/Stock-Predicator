# PROBORA V3 research log

Date: 2026-07-15

## Decision rules

- All model comparisons use purged 2023-2025 outer walk-forward folds.
- Calibration selection uses a chronological inner holdout, event purging and a seven-day embargo.
- Added complexity is charged by parameter count during calibration selection.
- A candidate is not deployable because its mean score improves once. It must improve at least two outer folds and must not materially damage calibration or key regimes.
- Historical outer folds have now informed V3 design, so shadow data remains the final independent promotion evidence.

## Baseline diagnosis

| Horizon | Current Brier | Baseline Brier | Mean BSS | Main diagnosis |
| --- | ---: | ---: | ---: | --- |
| 30 sessions | 0.63205 | 0.62176 | -1.67% | Weak resolution; worst in high volatility |
| 90 sessions | 0.61599 | 0.58787 | -5.10% | Near-zero resolution; severe 2023/high-volatility failure |

The multiclass Murphy decomposition is binned and therefore diagnostic. Its binning gap is always reported; ECE is not substituted for reliability.

## Experiment decisions

### Log-probability matrix calibration

Rejected for deployment. It was selected in one 30-session inner fold, then worsened that outer test fold. The average selected 30-session Brier rose from about 0.6321 to 0.6343. It did not produce a meaningful 90-session gain.

The implementation remains an ablation candidate. It is a regularized Dirichlet-form matrix calibrator, not an ODIR or SMS implementation.

### Explicit SPY macro feature group

Features: SPY 20/60-session return, 20/60-session volatility, 60-session trend strength and deterministic regime.

Rejected for deployment:

| Horizon | Existing features | With SPY macro group | Result |
| --- | ---: | ---: | --- |
| 30 sessions | 0.63205 | 0.63314 | Worse in all 3 folds |
| 90 sessions | 0.61599 | 0.61554 | Tiny mean gain; worse in 2 of 3 folds |

The experimental dataset is retained as `data/equity_training_samples_v3.parquet`; the live Python and .NET feature schema remains `us-equity-daily-v1`.

### Neutral band claim

No emergency ATR floor was added. The existing labeler already enforces an annualized volatility floor and a hard minimum threshold. In the equity dataset, the observed minimum neutral band is 3.45% for 30 sessions and 5.98% for 90 sessions. ATR/GARCH variants require a separate label ablation.

### Custom LightGBM Brier objective

Not implemented. The report provides a binary derivative, while PROBORA requires a coupled softmax multiclass Hessian. The stated binary Hessian is negative over part of its domain, which makes a direct second-order tree objective unsafe without a documented approximation and dedicated tests.

## Shadow status on 2026-07-15

- Crypto: healthy, 8/8 assets, 16 predictions per horizon across two UTC cutoffs.
- US equity collector: healthy, 20/20 assets, latest completed session 2026-07-14, 120 records written in the latest run.
- US equity predictions: still 20 per horizon because the prediction trigger ran before the EOD collector.
- Fix prepared: retry daily prediction at 05:45, 07:45 and 09:45 UTC after the US-equity collector windows. Prediction uniqueness prevents duplicates.

## Next V3 sequence

1. Deploy the post-collector prediction trigger and verify that equity counts rise by 20 per horizon.
2. Run label ablations (current volatility floor vs ATR-confirmed floor) without changing the live labeler.
3. Test 90-session horizon redesign: direct 90-session label versus aggregated 30-session path probabilities and an ordinal target.
4. Add genuinely new point-in-time macro sources only as isolated feature groups; each group needs fold wins and a confidence interval over daily Brier differences.
5. Keep all candidates in shadow until BSS is positive on matured live outcomes; target BSS is at least +5%, not merely above zero.

## 2026-07-15 continuation: 90-session redesign

The following candidates were tested with the same purged 2023-2025 design folds and a
partial, locked 2026 check. None was promoted merely because one period improved.

| Candidate | Historical result | Decision |
| --- | --- | --- |
| Ordinal two-threshold direction | Brier 0.60194 vs 0.61598 current; only 1/3 fold wins and paired CI crosses zero | Reject for live direction |
| Nested current/ordinal/prior selector | Chose the wrong model in key folds; Brier 0.62028 | Reject |
| Regime-conditioned shrinkage prior | Brier 0.59647 vs its 0.58787 baseline | Reject |
| Regularized linear model | 90-session Brier 0.62027; locked 2026 fell back fully to prior | Reject |
| ATR-confirmed neutral bands | 0.65 multiplier produced only 1/3 positive-BSS folds and reduced the down class to about 5.5% | Reject label change |
| Shallower/recent-window trees | No stable positive BSS; shallower trees worsened the mean | Reject |
| Lagged FRED market stress group | Brier 0.61553 vs 0.61584 existing, but BSS remained about -5.0% and locked 2026 was negative | Research-only; reject |

The FRED research group uses VIXCLS, DGS2, DGS10 and NFCI. A conservative seven-calendar-day
availability lag is applied before a backward as-of join. Downloadable FRED graph data is a
current-vintage snapshot, so it is explicitly ineligible for production until immutable live
snapshots or ALFRED vintage reconstruction exists.

### Accepted: volatility-scaled conformal intervals

The existing absolute conformal adjustment carried the 2022 high-volatility calibration residual
into the calmer 2023 test year. This caused 95% coverage and an unnecessarily wide interval.
Scaling the conformal expansion by point-in-time 60-session annualized volatility fixed the regime
transfer without touching future data.

| Metric, 90 sessions | Absolute adjustment | Volatility-scaled | Prior interval |
| --- | ---: | ---: | ---: |
| Mean coverage | 83.12% | 82.64% | — |
| Mean interval score | 0.55773 | **0.52029** | 0.56481 |
| Interval skill vs prior | +1.25% | **+7.88%** | 0% |
| Fold wins vs absolute | — | **3/3** | — |

The partial locked-2026 result retained 82.20% coverage and an interval score of 0.40712 versus
0.42026 for the prior interval. It was only 0.00075 worse than the absolute method while remaining
narrower. The runtime formula is identical in Python and .NET:

`adjustment = conformal_multiplier * annualized_volatility_60s * sqrt(horizon / 252)`

### Independent output gates

Direction and scenario quality are now separate contracts:

- Direction gate: Brier skill, fold wins and ECE.
- Scenario gate: quantile pinball, proper interval score, 80% coverage and risk MAE.
- A scenario may be published without a directional call. The API exposes both eligibility flags;
  the UI hides direction probabilities and direction factors when the direction gate fails.
- Feature explanations perturb to training medians stored in the manifest, report probability-point
  impact on `P(up) - P(down)`, and state that the comparison is not causal.

Fresh shadow bundles:

| Version | Direction gate | Scenario gate | Key scenario result |
| --- | --- | --- | --- |
| `probora-us-equity-v1-30d-20260715120509` | Fail | **Pass** | Coverage 83.69%, interval score 0.31018 vs 0.33385 prior |
| `probora-us-equity-v1-90d-20260715120200` | Fail | **Pass** | Coverage 82.68%, interval score 0.52022 vs 0.56481 prior |

These bundles remain shadow candidates. The application must not turn their direction probabilities
into user signals. Promotion requires matured live outcomes; direction remains abstained until its
own BSS gate passes.

## 2026-07-16 continuation: crypto 90-day regime blend

A leakage-safe regime gate was tested between the calibrated crypto direction model and its
training prior. Candidate structures were limited to global, volatility, trend-strength and market
regime weights. Structure selection used a purged chronological inner validation split. Each
additional regime weight was charged an information-criterion-like complexity penalty before the
outer test was opened.

Rejected for deployment:

- The selector kept the existing global blend in all four 2023-2026 folds.
- Historical 2023-2025 Brier was unchanged at 0.65092, with zero fold wins.
- The locked 2026 Brier was unchanged at 0.67663.
- The best raw inner-validation improvement was 0.00146 for the volatility gate in the 2024 fold,
  below its 0.00438 complexity penalty.

This is a useful negative result: the known regime failures do not justify extra live parameters
with the current sample size. Shadow inference and production eligibility remain unchanged.

## 2026-07-16 continuation: stable baseline audit and market-relative V4

### Stable validation-only baseline

The former training report selected the better logistic/climatology baseline separately on every
outer test fold. That was conservative but not deployable because the test result participated in
the benchmark choice.

The replacement is fixed before each test:

- Selection uses only the outer validation period.
- Logistic regression must beat climatology by at least 0.005 Brier.
- Logistic regression must also beat the uniform three-class forecast by at least 0.005 Brier.
- Otherwise the zero-parameter training climatology remains the baseline.
- The old test-fold minimum is retained only as an explicitly named oracle diagnostic and never
  drives BSS or a promotion gate.

Clean RTX 3050 Ti reruns:

| Asset class | Horizon | Model Brier | Stable baseline | BSS | Direction gate | Scenario gate |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Crypto | 30 days | 0.65612 | 0.65652 | +0.06% | Fail | Fail |
| Crypto | 90 days | 0.65105 | 0.65964 | +1.30% | Fail | Fail |
| US equity | 30 sessions | 0.63205 | 0.62176 | -1.65% | Fail | Pass |
| US equity | 90 sessions | 0.61603 | 0.58787 | -4.79% | Fail | Pass |

This confirms that the US-equity scenario contracts are useful while their direction contracts
must remain abstained. Crypto 90-day direction has small genuine skill, but it misses the +5% BSS
gate and its ECE is 5.49%.

### Market-relative V4 target

Two isolated research datasets were built:

- Crypto target: asset log return minus BTC log return.
- US-equity target: asset log return minus SPY log return.

The neutral band is not fixed. It uses point-in-time residual volatility:

`sqrt(asset_vol^2 + benchmark_vol^2 - 2 * correlation * asset_vol * benchmark_vol)`

BTC and SPY themselves are excluded from their relative datasets. All comparisons retain purging,
the seven-day embargo, validation-only calibration, the stable baseline selector and a locked 2026
fold.

90-horizon results:

| Component | Brier | Baseline | BSS | Fold wins | Paired 95% Brier-delta CI | Locked 2026 BSS | Decision |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| Altcoin minus BTC | 0.67353 | 0.66426 | -1.37% | 2/3 | [-0.00059, +0.01857] | -2.70% | Reject |
| US equity minus SPY | 0.60357 | 0.61939 | **+2.55%** | **3/3** | **[-0.02724, -0.00522]** | **+0.64%** | Continue research |

The equity-relative component is the first new V4 direction target with consistent fold wins and a
confidence interval entirely below zero. It is not promotable yet: BSS is below +5% and historical
ECE is 6.48%. The next bounded experiment should compare nominal versus ordinal relative direction
and leakage-safe calibration candidates. Crypto relative direction should not receive more
complexity without a new information source.

## 2026-07-20 continuation: shadow audit and relative-direction design

### Shadow audit

The VPS collectors and inference worker are healthy. The current four shadow candidates contain
272 predictions:

| Asset class | Horizon | Current predictions | Prediction days | Latest cutoff/session |
| --- | ---: | ---: | ---: | --- |
| Crypto | 30 days | 56 | 7 | 2026-07-20 UTC |
| Crypto | 90 days | 56 | 7 | 2026-07-20 UTC |
| US equity | 30 sessions | 80 | 4 | 2026-07-17 completed session |
| US equity | 90 sessions | 80 | 4 | 2026-07-17 completed session |

The database contains 372 total shadow rows because it also retains older candidate versions. The
current-candidate counter intentionally excludes those historical candidates. Crypto readiness is
8/8; US-equity readiness is 20/20 with 68,100 stored daily bars. No outcome has matured yet. The
first 30-day crypto evaluation remains 2026-08-13.

Running the same daily model twice per day was rejected. Its feature vector changes only after a
new final daily cutoff/session, so a second run would add a correlated duplicate rather than an
independent observation. The database uniqueness contract already prevents the same
asset/model/horizon/analysis-time tuple from being inserted twice. The worker retains multiple
retry windows for operational recovery; retries do not increment the evidence counter. A future
intraday model would require separate 1h/4h features, labels, horizons, model versions and metrics.

### US-equity relative nominal/ordinal/calibration ablation

The 90-session SPY-relative target was retested on the RTX 3050 Ti. Candidate choice used a
chronological inner validation tail with label purging and a seven-day embargo. Nominal
temperature/blend calibration was charged two parameters, ordinal calibration three, and the
log-probability matrix twelve. The zero-parameter prior remained the safety fallback. The 2026
outer fold was not used for fitting or selection.

| Candidate | Historical Brier | Stable baseline | BSS | ECE | Wins vs baseline | Locked 2026 BSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nominal | 0.60357 | 0.61939 | +2.55% | 6.54% | 3/3 | +0.64% |
| Ordinal | **0.60247** | 0.61939 | **+2.72%** | 6.19% | 3/3 | +0.43% |
| Matrix calibration | 0.60306 | 0.61939 | +2.63% | **4.51%** | 3/3 | -0.19% |
| Nested safe selector | 0.61146 | 0.61939 | +1.27% | 1.98% | 1/3 | -0.19% |

Ordinal direction beat nominal in all three historical folds, but the paired 95% Brier-delta
interval was `[-0.00315, +0.00096]`; it still crosses zero. Matrix calibration cleared the 5% ECE
threshold historically but failed the locked 2026 baseline. The inner selector correctly avoided
complexity in two historical folds, yet the changing validation regimes made it too conservative.

Decision: retain nominal market-relative V4 as a research reference and do not deploy any of these
variants. Ordinal is the leading next candidate, but it needs genuinely new forward evidence or a
new causal feature group; post-hoc tuning against the now-open 2026 fold is prohibited. Existing
shadow candidates and their counters remain unchanged.

## 2026-07-20 continuation: cross-sectional V4.1 feature groups

The equity feature audit found that V1 already contained one 20-session breadth measure plus
20/60-session momentum ranks and a 20-session volatility rank. Repackaging those columns would not
add information. A separate 117,420-row research dataset therefore added ten same-cutoff features:

- 5/60-session positive-return breadth;
- 20/60-session fraction above the corresponding moving average;
- 20/60-session cross-sectional return dispersion;
- short-minus-long breadth momentum;
- 20/60-session return and 20-session volatility relative to a causal peer ETF.

Peer mappings use QQQ for the large Nasdaq growth names, XLF for JPM/V, XLE for XOM, XLV for UNH,
and SPY for the remaining broad/sector ETFs and unmatched names. Every peer must be present at the
same completed daily cutoff or feature generation fails closed. The feature group is research-only
and does not change the live `.NET` schema.

The SPY-relative 90-session ordinal model was rerun on the RTX 3050 Ti with four feature groups.
Added feature counts participate in the chronological inner-selection complexity penalty.

| Candidate | Historical Brier | Stable baseline | BSS | ECE | Wins vs base ordinal | 2026 diagnostic BSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base ordinal | 0.60254 | 0.61939 | +2.71% | 6.23% | — | +0.42% |
| Breadth/dispersion | 0.60383 | 0.61939 | +2.50% | 5.43% | 0/3 | +0.57% |
| Peer-relative | **0.60207** | 0.61939 | **+2.79%** | 6.83% | 1/3 | -0.06% |
| Combined | 0.60335 | 0.61939 | +2.58% | 6.22% | 1/3 | +0.22% |

No group is shadow-eligible. The peer-relative Brier delta versus base ordinal has a paired 95%
interval of `[-0.00208, +0.00127]`, while the breadth interval is
`[-0.00103, +0.00362]`. Both cross zero. Breadth improves calibration but not enough to clear the
5% ECE gate, and its average Brier is worse.

Training-only regime thresholds were also applied for diagnostics. Relative to base ordinal, the
peer group improved Brier in high-dispersion (`-0.00212`), broad-breadth (`-0.00157`) and bull
(`-0.00120`) segments. It worsened bear (`+0.00227`) and normal-dispersion (`+0.00257`) segments.
This is a hypothesis for future evidence, not permission to build a post-hoc gate from the same
outer folds. The 2026 fold had already been opened by earlier work and is explicitly labelled a
diagnostic rather than fresh confirmation.

Decision: reject all-feature deployment and leave the existing shadow candidates untouched. The
next defensible source of information is a broader, point-in-time breadth/sector universe or new
forward shadow evidence for a predeclared high-dispersion peer gate. Repeated tuning on the same
2023-2026 periods is not accepted as progress.

## 2026-07-20 continuation: external sector data and V4.2

Official source and limit checks selected Twelve Data Basic for the bounded expansion. It provides
8 API credits/minute and 800/day; daily history costs one credit per symbol and supports up to 5,000
observations. Five long-history sector ETFs missing from the pilot were downloaded with
`adjust=all`: XLY, XLP, XLI, XLB and XLU. Each has 3,405 sessions from 2013-01-02 through
2026-07-17, for 17,025 new verified bars and five payload checksums.

Together with XLK, XLF, XLE and XLV already present, V4.2 uses a stable nine-sector panel. It adds
5/20/60-session sector breadth, 20/60-session sector dispersion, cyclical-minus-defensive spreads,
and sector-ETF-relative 20/60-session momentum and volatility. AAPL/MSFT/NVDA now compare with XLK;
AMZN/TSLA with XLY; WMT with XLP; JPM/V with XLF; XOM with XLE; and UNH with XLV.

90-session RTX 3050 Ti results:

| Candidate | Historical Brier | Stable baseline | BSS | ECE | Wins vs base ordinal | 2026 diagnostic BSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Base ordinal | 0.60253 | 0.61939 | +2.71% | 6.34% | — | +0.42% |
| Nine-sector breadth | 0.60236 | 0.61939 | +2.74% | 6.56% | 2/3 | +0.57% |
| Sector peer-relative | **0.60181** | 0.61939 | **+2.83%** | 7.11% | 2/3 | +0.06% |
| Combined | 0.60186 | 0.61939 | +2.82% | 6.99% | 2/3 | +0.55% |

The extra data contains signal, but no candidate is shadow-eligible. Sector peer's paired Brier
delta versus base ordinal is `[-0.00262, +0.00130]`; it crosses zero, BSS remains below +5%, and
calibration worsens. The nested selector again chose the prior in 2024/2025 and underperformed.
No live schema, registry entry or shadow model was changed.

The MIT historical S&P membership snapshot contains 734 distinct tickers from 2013 onward, implying
about 2.5 million daily bars for full point-in-time breadth. This is storage-feasible and nearly
fits one free daily API quota, but delisted and renamed security coverage is not yet trustworthy.
The full bootstrap must be resumable and fail closed on missing historical members; details are in
`docs/v4-data-requirements.md`.

## 2026-07-20 continuation: point-in-time S&P breadth V4.3 bootstrap

The 2.5 million estimate means symbol-session rows, not 2.5 million calendar days. The frozen
734-symbol union was split deterministically into two 367-call batches so the Twelve Data daily
quota is not shared unsafely with the VPS shadow collector. Batch one was started as a hidden,
resumable local process. Each success is stored as adjusted compressed Parquet and each failure is
recorded with its provider error; restarts skip both completed files and known failures unless an
explicit retry audit is requested.

The frozen MIT snapshot ends on 2025-08-23. A separate causal refresh consumes the current public
component and change tables, applies only changes after their effective dates, and records source
hash, attribution and reconciliation metadata. It extends the historical union from 734 to 758
symbols, leaving 24 incremental calls after the two frozen batches. This refreshed file does not
silently alter the running partitions.

The V4.3 feature and ablation code is predeclared before results are visible. It computes ten
point-in-time broad-market signals and compares base ordinal, the V4.2 sector-peer candidate,
broad breadth, and their combination. A hard gate blocks dataset construction below 95% coverage
on any cutoff or with stale membership. Therefore partial downloads cannot influence training,
the registry, or live shadow predictions.

## 2026-07-21 continuation: live evidence contract and crypto artifact rebuild

The production registry no longer treats `productionEligible` in an artifact manifest as authority
to change the production channel. A bundle can only become eligible for a separately audited manual
review after mature live outcomes exist. Each new prediction freezes its selected baseline
probabilities and its volatility-dependent neutral-band threshold. After the 30-day or 90-session
horizon matures, the worker resolves the outcome from final bars and records model/baseline Brier,
interval coverage, quantile pinball loss, risk absolute error, realized direction/return/volatility,
and a SHA-256 identity for the source bars.

The live review gate requires at least 100 resolved outcomes, 20 distinct evaluation dates, ten
outcomes in every class, Brier skill of at least +5%, ECE no greater than 5%, and nominal P10-P90
coverage between 75% and 90%. Passing creates only `eligible_for_manual_review`; automatic promotion
remains impossible. A newly trained offline-rejected artifact also cannot replace an existing
eligible shadow candidate merely because its timestamp is newer.

Every newly trained bundle now contains a fixed `runtime_parity.json` vector and Python ONNX
outputs. The .NET registry repeats the inference and rejects the bundle if direction probabilities,
quantiles, risk, or baseline differ by more than `1e-5`. Both rebuilds below passed this actual
Python-to-ONNX-to-.NET parity check on the local machine.

| Horizon | Model Brier | Stable baseline | BSS | ECE | Interval coverage | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 30 days | 0.65615 | 0.65652 | +0.06% | 5.26% | 85.29% | Reject; preserve current shadow |
| 90 days | 0.65094 | 0.65964 | +1.32% | 5.45% | 77.82% | Reject; preserve current shadow |

The RTX 3050 Ti rebuild therefore validates the new artifact and scoring contracts but does not
establish a useful directional or scenario improvement. Both direction and scenario gates remain
closed. This is a no-go result, not a reason to relax the thresholds.

## 2026-07-21 continuation: completed PIT bootstrap and V4.3 coverage decision

Both frozen 367-symbol partitions and the 24-symbol causal current-universe tail were completed
under the Twelve Data Basic rate limit. The final state contains 758 attempted symbols: 620 with
verified adjusted Parquet history and 138 provider 404 failures. A delisted-symbol retry first
resolved exchange metadata from one shared catalog request. Forty consecutive historical ticker
retries still returned no usable price series. With zero successes, the rule-of-three 95% upper
bound on the retry success rate is approximately 7.5%; spending the remaining quota could not
plausibly close the measured coverage gap, so the second retry partition was not burned blindly.

The final point-in-time audit covers 3,120 model trading dates:

| Measure | Coverage |
| --- | ---: |
| Mean daily membership coverage | 88.52% |
| Fifth percentile daily coverage | 78.45% |
| Minimum daily membership coverage | 77.44% |
| Latest daily membership coverage | 99.80% |

Membership freshness passed, but historical coverage did not. The explicit `--require-ready`
command failed closed with minimum coverage 77.44% versus the predeclared 95% requirement.
Consequently the V4.3 dataset builder and ablation were not run. Training on the partial panel would
reintroduce survivorship/availability bias and would not be an improvement. The next valid data step
requires a source with licensed delisted history plus an alias/security-master audit (including
class-share and renamed ticker mappings), after which the same frozen coverage gate can be rerun.
