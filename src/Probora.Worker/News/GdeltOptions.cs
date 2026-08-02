namespace Probora.Worker.News;

public sealed class GdeltOptions
{
    public const string SectionName = "Gdelt";
    public string BaseUrl { get; set; } = "https://api.gdeltproject.org";
    public bool Enabled { get; set; } = true;
    public int MaxRecordsPerAsset { get; set; } = 10;
    public int MinimumRequestIntervalMilliseconds { get; set; } = 2_500;
    public int MaximumRequestAttempts { get; set; } = 4;
    public int RetryBaseDelaySeconds { get; set; } = 15;
    public string QueryTimespan { get; set; } = "1d";
}
