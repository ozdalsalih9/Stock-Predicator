namespace Probora.Domain.News;

public sealed class NewsArticle
{
    public Guid Id { get; set; }
    public Guid AssetId { get; set; }
    public string Title { get; set; } = string.Empty;
    public string SourceName { get; set; } = string.Empty;
    public string SourceUrl { get; set; } = string.Empty;
    public DateTimeOffset PublishedAt { get; set; }
    public DateTimeOffset RetrievedAt { get; set; }
    public string Language { get; set; } = string.Empty;
    public string ContentHash { get; set; } = string.Empty;
    public double SourceReliabilityScore { get; set; }
    public double RelevanceScore { get; set; }
    public double? SentimentScore { get; set; }
    public string EventType { get; set; } = "unclassified";
    public double NoveltyScore { get; set; }
    public bool ShadowOnly { get; set; } = true;
}
