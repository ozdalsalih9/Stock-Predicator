using Probora.Domain.Markets;

namespace Probora.Application.MarketData;

public sealed record QualityViolation(string Code, string Message);

public static class PriceBarQualityValidator
{
    public static IReadOnlyList<QualityViolation> Validate(PriceBarCandidate bar)
    {
        List<QualityViolation> violations = [];

        if (!AssetCatalog.Contains(bar.Symbol))
        {
            violations.Add(new("unknown_symbol", $"Unsupported symbol: {bar.Symbol}."));
        }

        if (bar.Open <= 0 || bar.High <= 0 || bar.Low <= 0 || bar.Close <= 0)
        {
            violations.Add(new("non_positive_price", "OHLC prices must be positive."));
        }

        if (bar.High < Math.Max(bar.Open, bar.Close) || bar.Low > Math.Min(bar.Open, bar.Close) || bar.High < bar.Low)
        {
            violations.Add(new("invalid_ohlc", "High/low values are inconsistent with open/close."));
        }

        if (bar.Volume < 0 || bar.QuoteVolume < 0 || bar.TradeCount < 0)
        {
            violations.Add(new("negative_activity", "Volume and trade count cannot be negative."));
        }

        if (bar.OpenTime.Offset != TimeSpan.Zero || bar.CloseTime.Offset != TimeSpan.Zero)
        {
            violations.Add(new("non_utc_timestamp", "All market timestamps must be UTC."));
        }

        if (bar.CloseTime <= bar.OpenTime)
        {
            violations.Add(new("invalid_time_range", "Close time must be after open time."));
        }

        return violations;
    }
}
