using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Domain.Markets;
using Probora.Domain.News;
using Probora.Infrastructure.Persistence;
using Quartz;

namespace Probora.Worker.News;

[DisallowConcurrentExecution]
public sealed class GdeltNewsJob(
    HttpClient httpClient,
    ProboraDbContext dbContext,
    IOptions<GdeltOptions> options,
    TimeProvider timeProvider,
    ILogger<GdeltNewsJob> logger) : IJob
{
    private static readonly IReadOnlyDictionary<string, string> CryptoQueries = new Dictionary<string, string>
    {
        ["BTCUSDT"] = "(Bitcoin OR BTC) crypto",
        ["ETHUSDT"] = "(Ethereum OR Ether) crypto",
        ["SOLUSDT"] = "Solana crypto",
        ["BNBUSDT"] = "(BNB OR \"Binance Coin\") crypto",
        ["XRPUSDT"] = "(XRP OR Ripple) crypto",
        ["ADAUSDT"] = "(Cardano OR ADA) crypto",
        ["LINKUSDT"] = "(Chainlink OR LINK) crypto",
        ["DOGEUSDT"] = "(Dogecoin OR DOGE) crypto"
    };

    private readonly GdeltOptions _options = options.Value;
    private DateTimeOffset _lastRequestAt = DateTimeOffset.MinValue;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.Enabled)
        {
            return;
        }

        List<Asset> assets = await dbContext.Assets
            .Where(asset => asset.IsActive || asset.IsShadowEnabled)
            .OrderBy(asset => asset.AssetClass)
            .ThenBy(asset => asset.Symbol)
            .ToListAsync(context.CancellationToken);
        int written = 0;
        foreach (Asset asset in assets)
        {
            try
            {
                written += await FetchAssetAsync(asset, context.CancellationToken);
                await dbContext.SaveChangesAsync(context.CancellationToken);
            }
            catch (Exception exception)
            {
                logger.LogWarning(exception, "GDELT shadow ingestion failed for {Symbol}.", asset.Symbol);
                dbContext.ChangeTracker.Clear();
            }
        }

        logger.LogInformation("GDELT news ingestion completed for {AssetCount} assets; wrote {Written} rows.", assets.Count, written);
    }

    private async Task<int> FetchAssetAsync(Asset asset, CancellationToken cancellationToken)
    {
        string query = BuildQuery(asset) + " sourcelang:English";
        string path = "/api/v2/doc/doc?query=" + Uri.EscapeDataString(query) +
                      $"&mode=ArtList&format=json&maxrecords={Math.Clamp(_options.MaxRecordsPerAsset, 1, 50)}" +
                      $"&timespan={Uri.EscapeDataString(_options.QueryTimespan)}&sort=datedesc";
        using HttpResponseMessage response = await SendWithRetryAsync(path, asset.Symbol, cancellationToken);
        DateTimeOffset availableAt = timeProvider.GetUtcNow();
        await using Stream stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using JsonDocument document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
        if (!document.RootElement.TryGetProperty("articles", out JsonElement articles))
        {
            return 0;
        }

        Dictionary<string, NewsArticle> knownArticles = await dbContext.NewsArticles
            .Where(article => article.AssetId == asset.Id)
            .ToDictionaryAsync(article => article.ContentHash, cancellationToken);
        int written = 0;
        foreach (JsonElement item in articles.EnumerateArray())
        {
            string? title = item.TryGetProperty("title", out JsonElement titleElement) ? titleElement.GetString() : null;
            string? url = item.TryGetProperty("url", out JsonElement urlElement) ? urlElement.GetString() : null;
            if (string.IsNullOrWhiteSpace(title) || !Uri.TryCreate(url, UriKind.Absolute, out Uri? sourceUri) ||
                sourceUri.Scheme is not ("http" or "https"))
            {
                continue;
            }

            string canonicalUrl = sourceUri.GetLeftPart(UriPartial.Path);
            string hash = ContentHash(title, canonicalUrl);
            if (knownArticles.TryGetValue(hash, out NewsArticle? existing))
            {
                existing.RetrievedAt = availableAt;
                continue;
            }

            DateTimeOffset publishedAt = ParsePublishedAt(
                item.TryGetProperty("seendate", out JsonElement dateElement) ? dateElement.GetString() : null,
                availableAt);
            string language = item.TryGetProperty("language", out JsonElement languageElement)
                ? languageElement.GetString() ?? "unknown"
                : "unknown";
            string source = item.TryGetProperty("domain", out JsonElement domainElement)
                ? domainElement.GetString() ?? sourceUri.Host
                : sourceUri.Host;
            NewsArticle article = new()
            {
                Id = Guid.NewGuid(),
                AssetId = asset.Id,
                Title = title.Trim(),
                SourceName = source,
                SourceUrl = canonicalUrl,
                PublishedAt = publishedAt,
                AvailableAt = availableAt,
                RetrievedAt = availableAt,
                Provider = "gdelt",
                Language = language,
                ContentHash = hash,
                SourceReliabilityScore = SourceReliability(source),
                RelevanceScore = 0.80,
                SentimentScore = null,
                EventType = ClassifyEvent(title),
                NoveltyScore = 1.0,
                ShadowOnly = true
            };
            dbContext.NewsArticles.Add(article);
            knownArticles.Add(hash, article);
            written++;
        }

        return written;
    }

    private async Task<HttpResponseMessage> SendWithRetryAsync(
        string path,
        string symbol,
        CancellationToken cancellationToken)
    {
        int attempts = Math.Clamp(_options.MaximumRequestAttempts, 1, 8);
        for (int attempt = 1; attempt <= attempts; attempt++)
        {
            await RespectRateLimitAsync(cancellationToken);
            HttpResponseMessage response = await httpClient.GetAsync(path, cancellationToken);
            _lastRequestAt = timeProvider.GetUtcNow();
            if (response.IsSuccessStatusCode)
            {
                return response;
            }

            if (attempt == attempts || response.StatusCode is not HttpStatusCode.TooManyRequests &&
                (int)response.StatusCode < 500)
            {
                response.EnsureSuccessStatusCode();
            }

            TimeSpan delay = RetryDelay(response, attempt);
            logger.LogWarning(
                "GDELT returned {StatusCode} for {Symbol}; retry {Attempt}/{Attempts} after {DelaySeconds}s.",
                (int)response.StatusCode,
                symbol,
                attempt,
                attempts,
                delay.TotalSeconds);
            response.Dispose();
            await Task.Delay(delay, cancellationToken);
        }

        throw new InvalidOperationException($"GDELT retry budget was exhausted for {symbol}.");
    }

    private async Task RespectRateLimitAsync(CancellationToken cancellationToken)
    {
        TimeSpan minimumInterval = TimeSpan.FromMilliseconds(
            Math.Max(0, _options.MinimumRequestIntervalMilliseconds));
        TimeSpan remaining = _lastRequestAt + minimumInterval - timeProvider.GetUtcNow();
        if (remaining > TimeSpan.Zero)
        {
            await Task.Delay(remaining, cancellationToken);
        }
    }

    private TimeSpan RetryDelay(HttpResponseMessage response, int attempt)
    {
        if (response.Headers.RetryAfter?.Delta is { } retryAfter && retryAfter > TimeSpan.Zero)
        {
            return retryAfter;
        }
        if (response.Headers.RetryAfter?.Date is { } retryDate)
        {
            TimeSpan until = retryDate - timeProvider.GetUtcNow();
            if (until > TimeSpan.Zero)
            {
                return until;
            }
        }
        double seconds = Math.Max(1, _options.RetryBaseDelaySeconds) * Math.Pow(2, attempt - 1);
        return TimeSpan.FromSeconds(Math.Min(seconds, 180));
    }

    public static string BuildQuery(Asset asset)
    {
        if (CryptoQueries.TryGetValue(asset.Symbol, out string? query))
        {
            return query;
        }

        string name = asset.DisplayName.Replace('"', ' ').Trim();
        return $"\"{name}\" (stock OR shares OR earnings OR guidance)";
    }

    public static string ClassifyEvent(string title)
    {
        string value = title.ToLowerInvariant();
        if (ContainsAny(value, "earnings", "revenue", "guidance", "quarterly results")) return "earnings_guidance";
        if (ContainsAny(value, "acquisition", "merger", "takeover", "buys ")) return "merger_acquisition";
        if (ContainsAny(value, "sec ", "regulator", "lawsuit", "court", "antitrust")) return "legal_regulatory";
        if (ContainsAny(value, "hack", "breach", "cyber", "exploit")) return "cyber_security";
        if (ContainsAny(value, "rate cut", "rate hike", "federal reserve", "inflation", "jobs report")) return "macro_policy";
        return "market_news";
    }

    private static bool ContainsAny(string value, params string[] needles) => needles.Any(value.Contains);

    private static string ContentHash(string title, string sourceUrl) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            $"{title.Trim().ToUpperInvariant()}|{sourceUrl}"))).ToLowerInvariant();

    private static double SourceReliability(string source) => source.ToLowerInvariant() switch
    {
        "sec.gov" or "www.sec.gov" or "federalreserve.gov" or "www.federalreserve.gov" => 1.0,
        "reuters.com" or "www.reuters.com" or "apnews.com" => 0.90,
        _ => 0.55
    };

    private static DateTimeOffset ParsePublishedAt(string? value, DateTimeOffset fallback)
    {
        if (!string.IsNullOrWhiteSpace(value) && DateTimeOffset.TryParseExact(
                value,
                ["yyyyMMdd'T'HHmmss'Z'", "yyyyMMddHHmmss"],
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                out DateTimeOffset result))
        {
            return result;
        }
        return fallback;
    }
}
