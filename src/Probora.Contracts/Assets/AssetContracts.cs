namespace Probora.Contracts.Assets;

public sealed record AssetResponse(
    string Symbol,
    string BaseAsset,
    string QuoteAsset,
    string DisplayName,
    string AssetClass,
    string Exchange,
    DateTimeOffset DataStartsAt,
    decimal? LatestPrice,
    DateTimeOffset? LatestPriceAt,
    string DataState);

public sealed record PriceBarResponse(
    DateTimeOffset OpenTime,
    DateTimeOffset CloseTime,
    string Interval,
    decimal Open,
    decimal High,
    decimal Low,
    decimal Close,
    decimal Volume,
    long TradeCount,
    bool IsFinal);
