namespace Probora.Worker.News;

public sealed class MacroNewsOptions
{
    public const string SectionName = "MacroNews";
    public bool Enabled { get; set; } = true;
    public int MaxItemsPerFeed { get; set; } = 20;
    public string[] FeedUrls { get; set; } =
    [
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://www.federalreserve.gov/feeds/press_monetary.xml"
    ];
}
