using System.Globalization;
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
    private static readonly IReadOnlyDictionary<string, string> Queries = new Dictionary<string, string>
    {
        ["BTCUSDT"] = "(Bitcoin OR BTC) crypto",
        ["ETHUSDT"] = "(Ethereum OR Ether) crypto",
        ["SOLUSDT"] = "Solana crypto",
        ["BNBUSDT"] = "(BNB OR Binance Coin) crypto",
        ["XRPUSDT"] = "(XRP OR Ripple) crypto",
        ["ADAUSDT"] = "(Cardano OR ADA) crypto",
        ["LINKUSDT"] = "(Chainlink OR LINK) crypto",
        ["DOGEUSDT"] = "(Dogecoin OR DOGE) crypto"
    };
    private readonly GdeltOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.Enabled)
        {
            return;
        }
        List<Asset> assets = await dbContext.Assets.Where(x => x.IsActive).ToListAsync(context.CancellationToken);
        foreach (Asset asset in assets)
        {
            try
            {
                await FetchAssetAsync(asset, context.CancellationToken);
            }
            catch (Exception exception)
            {
                logger.LogWarning(exception, "GDELT shadow ingestion failed for {Symbol}.", asset.Symbol);
            }
        }
        await dbContext.SaveChangesAsync(context.CancellationToken);
    }

    private async Task FetchAssetAsync(Asset asset, CancellationToken cancellationToken)
    {
        string query = Queries[asset.Symbol];
        string path = "/api/v2/doc/doc?query=" + Uri.EscapeDataString(query) +
                      $"&mode=ArtList&format=json&maxrecords={Math.Clamp(_options.MaxRecordsPerAsset, 1, 250)}" +
                      "&timespan=3d&sort=datedesc";
        using HttpResponseMessage response = await httpClient.GetAsync(path, cancellationToken);
        response.EnsureSuccessStatusCode();
        await using Stream stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using JsonDocument document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
        if (!document.RootElement.TryGetProperty("articles", out JsonElement articles))
        {
            return;
        }

        foreach (JsonElement item in articles.EnumerateArray())
        {
            string? title = item.TryGetProperty("title", out JsonElement titleElement) ? titleElement.GetString() : null;
            string? url = item.TryGetProperty("url", out JsonElement urlElement) ? urlElement.GetString() : null;
            if (string.IsNullOrWhiteSpace(title) || !Uri.TryCreate(url, UriKind.Absolute, out Uri? sourceUri))
            {
                continue;
            }
            string hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
                $"{title.Trim().ToUpperInvariant()}|{sourceUri.AbsoluteUri}"))).ToLowerInvariant();
            bool exists = await dbContext.NewsArticles.AnyAsync(
                x => x.AssetId == asset.Id && x.ContentHash == hash,
                cancellationToken);
            if (exists)
            {
                continue;
            }
            DateTimeOffset publishedAt = ParsePublishedAt(
                item.TryGetProperty("seendate", out JsonElement dateElement) ? dateElement.GetString() : null);
            string language = item.TryGetProperty("language", out JsonElement languageElement)
                ? languageElement.GetString() ?? "unknown"
                : "unknown";
            string source = item.TryGetProperty("domain", out JsonElement domainElement)
                ? domainElement.GetString() ?? sourceUri.Host
                : sourceUri.Host;
            dbContext.NewsArticles.Add(new NewsArticle
            {
                Id = Guid.NewGuid(),
                AssetId = asset.Id,
                Title = title.Trim(),
                SourceName = source,
                SourceUrl = sourceUri.AbsoluteUri,
                PublishedAt = publishedAt,
                RetrievedAt = timeProvider.GetUtcNow(),
                Language = language,
                ContentHash = hash,
                SourceReliabilityScore = 0.50,
                RelevanceScore = 1.0,
                SentimentScore = null,
                EventType = "unclassified",
                NoveltyScore = 1.0,
                ShadowOnly = true
            });
        }
    }

    private DateTimeOffset ParsePublishedAt(string? value)
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
        return timeProvider.GetUtcNow();
    }
}
