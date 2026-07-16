namespace Probora.Worker.MarketData;

public sealed class BinanceFuturesOptions
{
    public const string SectionName = "BinanceFutures";
    public string RestBaseUrl { get; set; } = "https://fapi.binance.com";
    public bool EnableShadowCollector { get; set; } = true;
    public int CutoffDelayMinutes { get; set; } = 5;
    public int CollectionWindowMinutes { get; set; } = 45;
    public int MinimumRequestIntervalMilliseconds { get; set; } = 150;
    public int MaximumRequestAttempts { get; set; } = 4;
    public int UsedWeightSoftLimit { get; set; } = 1_800;
    public int RequiredHistoryDays { get; set; } = 90;
    public int MaximumClockSkewSeconds { get; set; } = 30;
}
