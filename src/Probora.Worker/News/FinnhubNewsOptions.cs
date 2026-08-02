namespace Probora.Worker.News;

public sealed class FinnhubNewsOptions
{
    public const string SectionName = "FinnhubNews";
    public bool Enabled { get; set; }
    public string ApiKey { get; set; } = string.Empty;
    public string BaseUrl { get; set; } = "https://finnhub.io/api/v1/";
    public int LookbackDays { get; set; } = 2;
    public int MinimumRequestIntervalMilliseconds { get; set; } = 1_100;
    public int MaximumRequestAttempts { get; set; } = 3;
    public int MaxCryptoArticles { get; set; } = 30;
}
