using Probora.Contracts.Analysis;
using Probora.Contracts.Assets;
using Probora.Contracts.News;
using Probora.Contracts.System;

namespace Probora.Application.Abstractions;

public interface IProboraQueryService
{
    Task<IReadOnlyList<AssetResponse>> GetAssetsAsync(CancellationToken cancellationToken);
    Task<IReadOnlyList<PriceBarResponse>?> GetBarsAsync(
        string symbol,
        string interval,
        DateTimeOffset? from,
        DateTimeOffset? to,
        int limit,
        CancellationToken cancellationToken);
    Task<AnalysisResponse?> GetLatestAnalysisAsync(
        string symbol,
        int horizonDays,
        bool includeShadowPreview,
        CancellationToken cancellationToken);
    Task<ModelCardResponse?> GetModelCardAsync(string version, CancellationToken cancellationToken);
    Task<PerformanceResponse?> GetPerformanceAsync(string? symbol, int horizonDays, CancellationToken cancellationToken);
    Task<SystemFreshnessResponse> GetFreshnessAsync(CancellationToken cancellationToken);
    Task<ShadowCollectorDashboardResponse> GetShadowCollectorDashboardAsync(CancellationToken cancellationToken);
    Task<UsEquityShadowDashboardResponse> GetUsEquityShadowDashboardAsync(CancellationToken cancellationToken);
    Task<ShadowPredictionDashboardResponse> GetShadowPredictionDashboardAsync(CancellationToken cancellationToken);
    Task<IReadOnlyList<MarketPriceUpdate>> GetLatestPricesAsync(CancellationToken cancellationToken);
    Task<IReadOnlyList<NewsArticleResponse>?> GetNewsAsync(string symbol, int limit, CancellationToken cancellationToken);
}

public interface IPriceBarWriter
{
    Task<int> UpsertAsync(IReadOnlyCollection<Domain.Markets.PriceBarCandidate> bars, CancellationToken cancellationToken);
}
