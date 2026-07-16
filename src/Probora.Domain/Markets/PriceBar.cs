namespace Probora.Domain.Markets;

public sealed class PriceBar
{
    public long Id { get; set; }
    public Guid AssetId { get; set; }
    public Asset? Asset { get; set; }
    public DateTimeOffset OpenTime { get; set; }
    public DateTimeOffset CloseTime { get; set; }
    public string Interval { get; set; } = "1h";
    public decimal Open { get; set; }
    public decimal High { get; set; }
    public decimal Low { get; set; }
    public decimal Close { get; set; }
    public decimal Volume { get; set; }
    public decimal QuoteVolume { get; set; }
    public long TradeCount { get; set; }
    public decimal TakerBuyBaseVolume { get; set; }
    public decimal TakerBuyQuoteVolume { get; set; }
    public string Source { get; set; } = "binance";
    public bool IsFinal { get; set; }
    public DateTimeOffset AvailableAt { get; set; }
    public DateTimeOffset IngestedAt { get; set; }
    public string? SourceChecksum { get; set; }
}

public sealed record PriceBarCandidate(
    string Symbol,
    DateTimeOffset OpenTime,
    DateTimeOffset CloseTime,
    string Interval,
    decimal Open,
    decimal High,
    decimal Low,
    decimal Close,
    decimal Volume,
    decimal QuoteVolume,
    long TradeCount,
    decimal TakerBuyBaseVolume,
    decimal TakerBuyQuoteVolume,
    bool IsFinal,
    DateTimeOffset AvailableAt,
    string Source = "binance",
    string? SourceChecksum = null);
