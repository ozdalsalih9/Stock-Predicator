namespace Probora.Contracts.System;

public sealed record DatasetFreshnessItem(
    string Dataset,
    string? Symbol,
    DateTimeOffset? LatestDataAt,
    DateTimeOffset? LastSuccessfulIngestionAt,
    string State);

public sealed record SystemFreshnessResponse(
    DateTimeOffset CheckedAt,
    IReadOnlyList<DatasetFreshnessItem> Items);

public sealed record MarketPriceUpdate(
    string Symbol,
    decimal Price,
    DateTimeOffset PriceTime,
    decimal? Change24HoursPercent);

public sealed record ShadowCollectorRunResponse(
    DateTimeOffset StartedAt,
    DateTimeOffset? CompletedAt,
    string Status,
    long RecordsRead,
    long RecordsWritten,
    double? DurationSeconds,
    string? Error);

public sealed record ShadowCollectorAssetResponse(
    string Symbol,
    DateTimeOffset? LatestSnapshotAt,
    DateTimeOffset? LatestAvailableAt,
    int ConsecutiveDays,
    int RequiredHistoryDays,
    double ReadinessPercent,
    double? LatestAvailabilityLatencyMinutes,
    string State);

public sealed record ShadowCollectorDashboardResponse(
    DateTimeOffset CheckedAt,
    DateTimeOffset CurrentCutoff,
    string State,
    int TotalAssets,
    int CurrentCutoffCompleteAssets,
    int ModelReadyAssets,
    int RequiredHistoryDays,
    int UnresolvedQualityIssues,
    int SevenDayRuns,
    double? SevenDayRunSuccessRate,
    double? SevenDayOnTimeRate,
    double? AverageAvailabilityLatencyMinutes,
    double? P95AvailabilityLatencyMinutes,
    IReadOnlyList<ShadowCollectorAssetResponse> Assets,
    IReadOnlyList<ShadowCollectorRunResponse> RecentRuns);

public sealed record UsEquityShadowAssetResponse(
    string Symbol,
    string DisplayName,
    string Exchange,
    long BarCount,
    DateTimeOffset? FirstBarAt,
    DateTimeOffset? LatestBarAt,
    DateTimeOffset? LastIngestedAt,
    int RequiredHistoryBars,
    double ReadinessPercent,
    string State);

public sealed record UsEquityShadowDashboardResponse(
    DateTimeOffset CheckedAt,
    string State,
    string Provider,
    string Source,
    int TotalAssets,
    int ReadyAssets,
    long TotalBars,
    int RequiredHistoryBars,
    DateTimeOffset? FirstBarAt,
    DateTimeOffset? LatestSessionAt,
    int UnresolvedQualityIssues,
    ShadowCollectorRunResponse? LatestRun,
    IReadOnlyList<UsEquityShadowAssetResponse> Assets);

public sealed record ShadowPredictionModelResponse(
    string Version,
    string AssetClass,
    string HorizonUnit,
    int HorizonDays,
    DateTimeOffset? StartedAt,
    DateTimeOffset? LastPredictionAt,
    DateTimeOffset? FirstEvaluationAt,
    int CalendarDaysElapsed,
    int RequiredCalendarDays,
    int RemainingCalendarDays,
    int PredictionDays,
    int PredictionCount,
    int MaturedPredictionCount,
    int CoveredAssets,
    int TotalAssets,
    double CoveragePercent,
    string State);

public sealed record ShadowPredictionDashboardResponse(
    DateTimeOffset CheckedAt,
    string State,
    int CandidateCount,
    int TotalPredictions,
    int TotalMaturedPredictions,
    IReadOnlyList<ShadowPredictionModelResponse> Models);
