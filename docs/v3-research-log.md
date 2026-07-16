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
