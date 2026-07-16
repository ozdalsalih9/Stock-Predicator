namespace Probora.Domain.Markets;

public sealed class DerivativeDailySnapshot
{
    public long Id { get; set; }
    public Guid AssetId { get; set; }
    public Asset? Asset { get; set; }
    public DateTimeOffset SnapshotTime { get; set; }
    public double FundingRate { get; set; }
    public double Premium { get; set; }
    public double FuturesQuoteVolume { get; set; }
    public double FuturesTakerBuyRatio { get; set; }
    public double OpenInterestValue { get; set; }
    public double LongShortRatio { get; set; }
    public double TakerLongShortRatio { get; set; }
    public int FuturesKlineCount { get; set; }
    public int PremiumKlineCount { get; set; }
    public int FundingPointCount { get; set; }
    public int OpenInterestPointCount { get; set; }
    public int LongShortPointCount { get; set; }
    public int TakerLongShortPointCount { get; set; }
    public bool IsComplete { get; set; }
    public DateTimeOffset SourceMaxEventTime { get; set; }
    public DateTimeOffset AvailableAt { get; set; }
    public DateTimeOffset IngestedAt { get; set; }
    public string Source { get; set; } = "binance-usdm";
    public string SourceChecksum { get; set; } = string.Empty;
}
