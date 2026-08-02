namespace Probora.Contracts.News;

public sealed record NewsArticleResponse(
    Guid Id,
    string Symbol,
    string Title,
    string SourceName,
    string SourceUrl,
    DateTimeOffset PublishedAt,
    DateTimeOffset AvailableAt,
    DateTimeOffset RetrievedAt,
    string Provider,
    string Language,
    double RelevanceScore,
    double? SentimentScore,
    string EventType,
    double NoveltyScore,
    bool ShadowOnly);
