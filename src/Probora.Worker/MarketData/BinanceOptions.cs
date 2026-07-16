namespace Probora.Worker.MarketData;

public sealed class BinanceOptions
{
    public const string SectionName = "Binance";
    public string RestBaseUrl { get; set; } = "https://data-api.binance.vision";
    public string WebSocketBaseUrl { get; set; } = "wss://stream.binance.com:9443";
    public int BackfillLimit { get; set; } = 1_000;
    public int BackfillDays { get; set; } = 410;
    public int BackfillPageDelayMilliseconds { get; set; } = 100;
    public bool EnableWebSocket { get; set; } = true;
}
