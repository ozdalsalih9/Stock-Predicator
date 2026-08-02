using System.Security.Cryptography;
using System.Text;
using System.Xml.Linq;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Domain.Markets;
using Probora.Domain.News;
using Probora.Infrastructure.Persistence;
using Quartz;

namespace Probora.Worker.News;

[DisallowConcurrentExecution]
public sealed class MacroRssNewsJob(
    HttpClient httpClient,
    ProboraDbContext dbContext,
    IOptions<MacroNewsOptions> options,
    TimeProvider timeProvider,
    ILogger<MacroRssNewsJob> logger) : IJob
{
    private readonly MacroNewsOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.Enabled)
        {
            return;
        }

        List<Asset> assets = await dbContext.Assets
            .Where(asset => asset.IsActive || asset.IsShadowEnabled)
            .ToListAsync(context.CancellationToken);
        Dictionary<Guid, Dictionary<string, NewsArticle>> knownArticles = new();
        foreach (Asset asset in assets)
        {
            knownArticles[asset.Id] = await dbContext.NewsArticles
                .Where(article => article.AssetId == asset.Id)
                .ToDictionaryAsync(article => article.ContentHash, context.CancellationToken);
        }

        int written = 0;
        foreach (string feedUrl in _options.FeedUrls.Where(url => !string.IsNullOrWhiteSpace(url)))
        {
            try
            {
                written += await FetchFeedAsync(feedUrl, assets, knownArticles, context.CancellationToken);
                await dbContext.SaveChangesAsync(context.CancellationToken);
            }
            catch (Exception exception)
            {
                logger.LogWarning(exception, "Macro RSS ingestion failed for {FeedUrl}.", feedUrl);
            }
        }

        logger.LogInformation("Macro RSS ingestion completed; wrote {Written} asset-linked rows.", written);
    }

    private async Task<int> FetchFeedAsync(
        string feedUrl,
        IReadOnlyCollection<Asset> assets,
        IReadOnlyDictionary<Guid, Dictionary<string, NewsArticle>> knownArticles,
        CancellationToken cancellationToken)
    {
        using HttpResponseMessage response = await httpClient.GetAsync(feedUrl, cancellationToken);
        response.EnsureSuccessStatusCode();
        DateTimeOffset availableAt = timeProvider.GetUtcNow();
        await using Stream stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        XDocument document = await XDocument.LoadAsync(stream, LoadOptions.None, cancellationToken);
        XElement[] items = document.Descendants()
            .Where(element => element.Name.LocalName == "item")
            .Take(Math.Clamp(_options.MaxItemsPerFeed, 1, 100))
            .ToArray();
        int written = 0;
        foreach (XElement item in items)
        {
            string? title = Value(item, "title")?.Trim();
            string? link = Value(item, "link")?.Trim();
            if (string.IsNullOrWhiteSpace(title) || !Uri.TryCreate(link, UriKind.Absolute, out Uri? uri) ||
                uri.Scheme is not ("http" or "https"))
            {
                continue;
            }

            string canonicalUrl = uri.GetLeftPart(UriPartial.Path);
            string hash = ContentHash(title, canonicalUrl);
            DateTimeOffset publishedAt = ParsePublishedAt(Value(item, "pubDate"), availableAt);
            foreach (Asset asset in assets)
            {
                if (knownArticles[asset.Id].TryGetValue(hash, out NewsArticle? existing))
                {
                    existing.RetrievedAt = availableAt;
                    existing.Provider = "federal_reserve_rss";
                    existing.SourceName = "Federal Reserve";
                    existing.SourceReliabilityScore = 1.0;
                    existing.RelevanceScore = Math.Max(existing.RelevanceScore, 0.65);
                    existing.EventType = "macro_monetary_policy";
                    continue;
                }

                NewsArticle article = new()
                {
                    Id = Guid.NewGuid(),
                    AssetId = asset.Id,
                    Title = title,
                    SourceName = "Federal Reserve",
                    SourceUrl = canonicalUrl,
                    PublishedAt = publishedAt,
                    AvailableAt = availableAt,
                    RetrievedAt = availableAt,
                    Provider = "federal_reserve_rss",
                    Language = "English",
                    ContentHash = hash,
                    SourceReliabilityScore = 1.0,
                    RelevanceScore = 0.65,
                    SentimentScore = null,
                    EventType = "macro_monetary_policy",
                    NoveltyScore = 1.0,
                    ShadowOnly = true
                };
                dbContext.NewsArticles.Add(article);
                knownArticles[asset.Id].Add(hash, article);
                written++;
            }
        }

        return written;
    }

    private static string? Value(XElement parent, string localName) =>
        parent.Elements().FirstOrDefault(element => element.Name.LocalName == localName)?.Value;

    private static DateTimeOffset ParsePublishedAt(string? value, DateTimeOffset fallback) =>
        DateTimeOffset.TryParse(value, out DateTimeOffset parsed) ? parsed.ToUniversalTime() : fallback;

    private static string ContentHash(string title, string sourceUrl) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            $"{title.Trim().ToUpperInvariant()}|{sourceUrl}"))).ToLowerInvariant();
}
