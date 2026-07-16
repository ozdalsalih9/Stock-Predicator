namespace Probora.Worker.News;

public sealed class GdeltOptions
{
    public const string SectionName = "Gdelt";
    public string BaseUrl { get; set; } = "https://api.gdeltproject.org";
    public bool Enabled { get; set; } = true;
    public int MaxRecordsPerAsset { get; set; } = 25;
}
