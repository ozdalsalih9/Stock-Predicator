namespace Probora.Domain.Markets;

public static class AssetClasses
{
    public const string Crypto = "crypto";
    public const string UsEquity = "us_equity";
}

public sealed class Asset
{
    public Guid Id { get; set; }
    public string Symbol { get; set; } = string.Empty;
    public string BaseAsset { get; set; } = string.Empty;
    public string QuoteAsset { get; set; } = "USD";
    public string DisplayName { get; set; } = string.Empty;
    public string AssetClass { get; set; } = AssetClasses.Crypto;
    public string Exchange { get; set; } = string.Empty;
    public string TradingCalendar { get; set; } = "24x7";
    public DateTimeOffset DataStartsAt { get; set; }
    public bool IsActive { get; set; } = true;
    public bool IsShadowEnabled { get; set; } = true;
}

public static class AssetCatalog
{
    public static readonly IReadOnlyList<AssetDefinition> Crypto =
    [
        new("BTCUSDT", "BTC", "USDT", "Bitcoin", Utc(2017, 8, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("ETHUSDT", "ETH", "USDT", "Ethereum", Utc(2017, 8, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("SOLUSDT", "SOL", "USDT", "Solana", Utc(2020, 8, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("BNBUSDT", "BNB", "USDT", "BNB", Utc(2017, 11, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("XRPUSDT", "XRP", "USDT", "XRP", Utc(2018, 5, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("ADAUSDT", "ADA", "USDT", "Cardano", Utc(2018, 4, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("LINKUSDT", "LINK", "USDT", "Chainlink", Utc(2019, 1, 1), AssetClasses.Crypto, "BINANCE", "24x7", true),
        new("DOGEUSDT", "DOGE", "USDT", "Dogecoin", Utc(2019, 7, 1), AssetClasses.Crypto, "BINANCE", "24x7", true)
    ];

    // Fixed, liquid pilot universe. It is shadow-only until point-in-time history
    // and a US-equity model independently pass the promotion gates.
    public static readonly IReadOnlyList<AssetDefinition> UsEquityPilot =
    [
        Equity("SPY", "SPDR S&P 500 ETF", 1993, 1, 29, "ARCA"),
        Equity("QQQ", "Invesco QQQ Trust", 1999, 3, 10, "NASDAQ"),
        Equity("IWM", "iShares Russell 2000 ETF", 2000, 5, 22, "ARCA"),
        Equity("DIA", "SPDR Dow Jones Industrial Average ETF", 1998, 1, 20, "ARCA"),
        Equity("XLK", "Technology Select Sector SPDR", 1998, 12, 22, "ARCA"),
        Equity("XLF", "Financial Select Sector SPDR", 1998, 12, 22, "ARCA"),
        Equity("XLE", "Energy Select Sector SPDR", 1998, 12, 22, "ARCA"),
        Equity("XLV", "Health Care Select Sector SPDR", 1998, 12, 22, "ARCA"),
        Equity("AAPL", "Apple", 1980, 12, 12, "NASDAQ"),
        Equity("MSFT", "Microsoft", 1986, 3, 13, "NASDAQ"),
        Equity("NVDA", "NVIDIA", 1999, 1, 22, "NASDAQ"),
        Equity("AMZN", "Amazon", 1997, 5, 15, "NASDAQ"),
        Equity("GOOGL", "Alphabet", 2004, 8, 19, "NASDAQ"),
        Equity("META", "Meta Platforms", 2012, 5, 18, "NASDAQ"),
        Equity("TSLA", "Tesla", 2010, 6, 29, "NASDAQ"),
        Equity("JPM", "JPMorgan Chase", 1980, 1, 2, "NYSE"),
        Equity("V", "Visa", 2008, 3, 19, "NYSE"),
        Equity("XOM", "Exxon Mobil", 1980, 1, 2, "NYSE"),
        Equity("UNH", "UnitedHealth Group", 1984, 10, 17, "NYSE"),
        Equity("WMT", "Walmart", 1980, 1, 2, "NYSE")
    ];

    public static readonly IReadOnlyList<AssetDefinition> All = [.. Crypto, .. UsEquityPilot];

    public static bool Contains(string symbol) =>
        All.Any(asset => string.Equals(asset.Symbol, symbol, StringComparison.OrdinalIgnoreCase));

    private static AssetDefinition Equity(
        string symbol,
        string displayName,
        int year,
        int month,
        int day,
        string exchange) => new(
            symbol,
            symbol,
            "USD",
            displayName,
            Utc(year, month, day),
            AssetClasses.UsEquity,
            exchange,
            "XNYS",
            false);

    private static DateTimeOffset Utc(int year, int month, int day) =>
        new(year, month, day, 0, 0, 0, TimeSpan.Zero);
}

public sealed record AssetDefinition(
    string Symbol,
    string BaseAsset,
    string QuoteAsset,
    string DisplayName,
    DateTimeOffset DataStartsAt,
    string AssetClass,
    string Exchange,
    string TradingCalendar,
    bool IsActive);
