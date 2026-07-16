namespace Probora.Worker.MarketData;

public sealed class TwelveDataOptions
{
    public const string SectionName = "TwelveData";
    public const string Source = "twelvedata-us-eod-total-return";

    public bool Enabled { get; set; }
    public string ApiKey { get; set; } = string.Empty;
    public string BaseUrl { get; set; } = "https://api.twelvedata.com";
    public string Adjustment { get; set; } = "all";
    public int MinimumRequestIntervalMilliseconds { get; set; } = 8_000;
    public int MaximumRequestAttempts { get; set; } = 4;
    public DateOnly HistoryStart { get; set; } = new(2013, 1, 1);

    public bool IsConfigured => Enabled && !string.IsNullOrWhiteSpace(ApiKey);
}
