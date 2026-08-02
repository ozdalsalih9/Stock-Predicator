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
public sealed class FinnhubNewsJob(
    HttpClient httpClient,
    ProboraDbContext dbContext,
    IOptions<FinnhubNewsOptions> options,
    TimeProvider timeProvider,
    ILogger<FinnhubNewsJob> logger) : IJob
{
    private readonly FinnhubNewsOptions _options = options.Value;
    private DateTimeOffset _lastRequestAt = DateTimeOffset.MinValue;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.Enabled || string.IsNullOrWhiteSpace(_options.ApiKey))
        {
            return;
        }

        List<Asset> assets = await dbContext.Assets
            .Where(asset => asset.IsActive || asset.IsShadowEnabled)
            .OrderBy(asset => asset.Symbol)
            .ToListAsync(context.CancellationToken);
        int written = 0;
        foreach (Asset asset in assets.Where(asset => asset.AssetClass == AssetClasses.UsEquity))
        {
            try
            {
                DateOnly today = DateOnly.FromDateTime(timeProvider.GetUtcNow().UtcDateTime);
                DateOnly from = today.AddDays(-Math.Clamp(_options.LookbackDays, 1, 7));
                string path = $"company-news?symbol={Uri.EscapeDataString(asset.Symbol)}&from={from:yyyy-MM-dd}&to={today:yyyy-MM-dd}";
                JsonElement[] articles = await FetchAsync(path, asset.Symbol, context.CancellationToken);
                written += await StoreAsync(asset, articles, 0.85, context.CancellationToken);
                await dbContext.SaveChangesAsync(context.CancellationToken);
            }
            catch (Exception exception)
            {
                logger.LogWarning(exception, "Finnhub company-news ingestion failed for {Symbol}.", asset.Symbol);
                dbContext.ChangeTracker.Clear();
            }
        }

        try
        {
            JsonElement[] cryptoNews = await FetchAsync("news?category=crypto", "crypto", context.CancellationToken);
            foreach (Asset asset in assets.Where(asset => asset.AssetClass == AssetClasses.Crypto))
            {
                JsonElement[] relevant = cryptoNews
                    .Where(article => IsRelevantCryptoArticle(article, asset))
                    .Take(Math.Clamp(_options.MaxCryptoArticles, 1, 100))
                    .ToArray();
                written += await StoreAsync(asset, relevant, 0.70, context.CancellationToken);
            }
            await dbContext.SaveChangesAsync(context.CancellationToken);
        }
        catch (Exception exception)
        {
            logger.LogWarning(exception, "Finnhub crypto-news ingestion failed.");
        }

        logger.LogInformation("Finnhub news ingestion completed; wrote {Written} rows.", written);
    }

    private async Task<JsonElement[]> FetchAsync(
        string path,
        string scope,
        CancellationToken cancellationToken)
    {
        int attempts = Math.Clamp(_options.MaximumRequestAttempts, 1, 6);
        for (int attempt = 1; attempt <= attempts; attempt++)
        {
            await RespectRateLimitAsync(cancellationToken);
            using HttpRequestMessage request = new(HttpMethod.Get, path);
            request.Headers.Add("X-Finnhub-Token", _options.ApiKey);
            using HttpResponseMessage response = await httpClient.SendAsync(request, cancellationToken);
            _lastRequestAt = timeProvider.GetUtcNow();
            if (response.IsSuccessStatusCode)
            {
                await using Stream stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                using JsonDocument document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                if (document.RootElement.ValueKind != JsonValueKind.Array)
                {
                    throw new InvalidOperationException("Finnhub news response was not an array.");
                }
                return document.RootElement.EnumerateArray().Select(item => item.Clone()).ToArray();
            }

            if (attempt == attempts || response.StatusCode is not HttpStatusCode.TooManyRequests &&
                (int)response.StatusCode < 500)
            {
                response.EnsureSuccessStatusCode();
            }
            TimeSpan delay = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(10 * attempt);
            logger.LogWarning(
                "Finnhub returned {StatusCode} for {Scope}; retry {Attempt}/{Attempts} after {DelaySeconds}s.",
                (int)response.StatusCode,
                scope,
                attempt,
                attempts,
                delay.TotalSeconds);
            await Task.Delay(delay, cancellationToken);
        }

        return [];
    }

    private async Task<int> StoreAsync(
        Asset asset,
        IEnumerable<JsonElement> articles,
        double relevance,
        CancellationToken cancellationToken)
    {
        Dictionary<string, NewsArticle> knownArticles = await dbContext.NewsArticles
            .Where(article => article.AssetId == asset.Id)
            .ToDictionaryAsync(article => article.ContentHash, cancellationToken);
        DateTimeOffset availableAt = timeProvider.GetUtcNow();
        int written = 0;
        foreach (JsonElement item in articles)
        {
            string? title = Text(item, "headline");
            string? url = Text(item, "url");
            if (string.IsNullOrWhiteSpace(title) || !Uri.TryCreate(url, UriKind.Absolute, out Uri? uri) ||
                uri.Scheme is not ("http" or "https"))
            {
                continue;
            }
            string canonicalUrl = uri.GetLeftPart(UriPartial.Path);
            string hash = ContentHash(title, canonicalUrl);
            if (knownArticles.TryGetValue(hash, out NewsArticle? existing))
            {
                existing.RetrievedAt = availableAt;
                if (existing.SourceReliabilityScore < 0.70)
                {
                    existing.Provider = "finnhub";
                    existing.SourceReliabilityScore = 0.70;
                }
                continue;
            }

            long timestamp = item.TryGetProperty("datetime", out JsonElement dateElement) &&
                             dateElement.TryGetInt64(out long parsedTimestamp)
                ? parsedTimestamp
                : availableAt.ToUnixTimeSeconds();
            string source = Text(item, "source") ?? uri.Host;
            NewsArticle article = new()
            {
                Id = Guid.NewGuid(),
                AssetId = asset.Id,
                Title = title.Trim(),
                SourceName = source,
                SourceUrl = canonicalUrl,
                PublishedAt = DateTimeOffset.FromUnixTimeSeconds(timestamp),
                AvailableAt = availableAt,
                RetrievedAt = availableAt,
                Provider = "finnhub",
                Language = "English",
                ContentHash = hash,
                SourceReliabilityScore = OfficialReliability(uri.Host),
                RelevanceScore = relevance,
                SentimentScore = null,
                EventType = GdeltNewsJob.ClassifyEvent(title),
                NoveltyScore = 1.0,
                ShadowOnly = true
            };
            dbContext.NewsArticles.Add(article);
            knownArticles.Add(hash, article);
            written++;
        }

        return written;
    }

    private async Task RespectRateLimitAsync(CancellationToken cancellationToken)
    {
        TimeSpan interval = TimeSpan.FromMilliseconds(Math.Max(0, _options.MinimumRequestIntervalMilliseconds));
        TimeSpan remaining = _lastRequestAt + interval - timeProvider.GetUtcNow();
        if (remaining > TimeSpan.Zero)
        {
            await Task.Delay(remaining, cancellationToken);
        }
    }

    public static bool IsRelevantCryptoArticle(JsonElement article, Asset asset)
    {
        string text = $"{Text(article, "headline")} {Text(article, "summary")} {Text(article, "related")}";
        string[] aliases = asset.Symbol switch
        {
            "BTCUSDT" => ["bitcoin", "btc"],
            "ETHUSDT" => ["ethereum", "ether", "eth"],
            "SOLUSDT" => ["solana", "sol"],
            "BNBUSDT" => ["binance coin", "bnb"],
            "XRPUSDT" => ["ripple", "xrp"],
            "ADAUSDT" => ["cardano", "ada"],
            "LINKUSDT" => ["chainlink", "link"],
            "DOGEUSDT" => ["dogecoin", "doge"],
            _ => [asset.BaseAsset.ToLowerInvariant()]
        };
        return aliases.Any(alias => ContainsWord(text, alias));
    }

    private static bool ContainsWord(string text, string value)
    {
        string normalized = text.ToLowerInvariant();
        int index = normalized.IndexOf(value, StringComparison.Ordinal);
        while (index >= 0)
        {
            bool left = index == 0 || !char.IsLetterOrDigit(normalized[index - 1]);
            int end = index + value.Length;
            bool right = end == normalized.Length || !char.IsLetterOrDigit(normalized[end]);
            if (left && right) return true;
            index = normalized.IndexOf(value, end, StringComparison.Ordinal);
        }
        return false;
    }

    private static string? Text(JsonElement item, string property) =>
        item.TryGetProperty(property, out JsonElement value) ? value.GetString() : null;

    private static string ContentHash(string title, string sourceUrl) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            $"{title.Trim().ToUpperInvariant()}|{sourceUrl}"))).ToLowerInvariant();

    private static double OfficialReliability(string host) => host.ToLowerInvariant() switch
    {
        "sec.gov" or "www.sec.gov" or "federalreserve.gov" or "www.federalreserve.gov" => 1.0,
        "reuters.com" or "www.reuters.com" or "apnews.com" => 0.90,
        _ => 0.70
    };
}
