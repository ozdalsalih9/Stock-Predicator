using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;
using Probora.Domain.Markets;

namespace Probora.Worker.MarketData;

public sealed class TwelveDataMarketDataClient(
    HttpClient httpClient,
    IOptions<TwelveDataOptions> options,
    TimeProvider timeProvider)
{
    private readonly TwelveDataOptions _options = options.Value;
    private readonly SemaphoreSlim _rateLock = new(1, 1);
    private DateTimeOffset _nextRequestAt = DateTimeOffset.MinValue;

    public async Task<IReadOnlyList<PriceBarCandidate>> GetDailyBarsAsync(
        IReadOnlyCollection<string> symbols,
        DateOnly start,
        DateOnly endInclusive,
        CancellationToken cancellationToken)
    {
        List<PriceBarCandidate> result = [];
        foreach (string symbol in symbols)
        {
            using JsonDocument document = await GetTimeSeriesAsync(
                symbol,
                start,
                endInclusive,
                cancellationToken);
            ThrowIfApiError(document.RootElement, symbol);
            if (!document.RootElement.TryGetProperty("values", out JsonElement values) ||
                values.ValueKind != JsonValueKind.Array)
            {
                throw new InvalidOperationException($"Twelve Data returned no daily values for {symbol}.");
            }

            foreach (JsonElement bar in values.EnumerateArray())
            {
                result.Add(ParseBar(symbol, bar));
            }
        }
        return result;
    }

    private async Task<JsonDocument> GetTimeSeriesAsync(
        string symbol,
        DateOnly start,
        DateOnly endInclusive,
        CancellationToken cancellationToken)
    {
        string url = "/time_series" +
            $"?symbol={Uri.EscapeDataString(symbol)}" +
            "&interval=1day" +
            $"&start_date={start:yyyy-MM-dd}" +
            $"&end_date={endInclusive:yyyy-MM-dd}" +
            "&outputsize=5000&order=asc&timezone=Exchange" +
            $"&adjust={Uri.EscapeDataString(_options.Adjustment)}";

        for (int attempt = 1; attempt <= _options.MaximumRequestAttempts; attempt++)
        {
            await WaitForRateLimitAsync(cancellationToken);
            using HttpRequestMessage request = new(HttpMethod.Get, url);
            request.Headers.TryAddWithoutValidation("Authorization", $"apikey {_options.ApiKey}");
            using HttpResponseMessage response = await httpClient.SendAsync(request, cancellationToken);
            string payload = await response.Content.ReadAsStringAsync(cancellationToken);
            if (response.IsSuccessStatusCode)
            {
                return JsonDocument.Parse(payload);
            }

            if ((response.StatusCode == HttpStatusCode.TooManyRequests ||
                 (int)response.StatusCode >= 500) &&
                attempt < _options.MaximumRequestAttempts)
            {
                TimeSpan retryAfter = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(60);
                await Task.Delay(retryAfter, timeProvider, cancellationToken);
                continue;
            }

            string detail = TryReadError(payload) ?? response.ReasonPhrase ?? "Unknown error";
            throw new HttpRequestException(
                $"Twelve Data request for {symbol} failed with {(int)response.StatusCode}: {detail}",
                null,
                response.StatusCode);
        }

        throw new InvalidOperationException($"Twelve Data request for {symbol} exhausted its retry budget.");
    }

    private async Task WaitForRateLimitAsync(CancellationToken cancellationToken)
    {
        await _rateLock.WaitAsync(cancellationToken);
        try
        {
            DateTimeOffset now = timeProvider.GetUtcNow();
            if (_nextRequestAt > now)
            {
                await Task.Delay(_nextRequestAt - now, timeProvider, cancellationToken);
                now = timeProvider.GetUtcNow();
            }
            _nextRequestAt = now.AddMilliseconds(_options.MinimumRequestIntervalMilliseconds);
        }
        finally
        {
            _rateLock.Release();
        }
    }

    private PriceBarCandidate ParseBar(string symbol, JsonElement bar)
    {
        string dateText = bar.GetProperty("datetime").GetString()!;
        DateOnly sessionDate = DateOnly.ParseExact(dateText[..10], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        DateTimeOffset openTime = new(
            DateTime.SpecifyKind(sessionDate.ToDateTime(TimeOnly.MinValue), DateTimeKind.Utc));
        decimal volume = DecimalOrZero(bar, "volume");
        decimal close = Decimal(bar, "close");
        string identity = $"{symbol}|{_options.Adjustment}|{bar.GetRawText()}";
        string checksum = Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant();
        return new PriceBarCandidate(
            symbol.ToUpperInvariant(),
            openTime,
            openTime.AddDays(1).AddTicks(-1),
            "1d",
            Decimal(bar, "open"),
            Decimal(bar, "high"),
            Decimal(bar, "low"),
            close,
            volume,
            volume * close,
            0,
            0,
            0,
            true,
            timeProvider.GetUtcNow(),
            TwelveDataOptions.Source,
            checksum);
    }

    private static void ThrowIfApiError(JsonElement root, string symbol)
    {
        if (root.TryGetProperty("status", out JsonElement status) &&
            string.Equals(status.GetString(), "error", StringComparison.OrdinalIgnoreCase))
        {
            string message = root.TryGetProperty("message", out JsonElement detail)
                ? detail.GetString() ?? "Unknown API error"
                : "Unknown API error";
            throw new InvalidOperationException($"Twelve Data rejected {symbol}: {message}");
        }
    }

    private static string? TryReadError(string payload)
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(payload);
            return document.RootElement.TryGetProperty("message", out JsonElement message)
                ? message.GetString()
                : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static decimal DecimalOrZero(JsonElement item, string property) =>
        item.TryGetProperty(property, out JsonElement value) && value.ValueKind != JsonValueKind.Null
            ? Decimal(value)
            : 0;

    private static decimal Decimal(JsonElement item, string property) => Decimal(item.GetProperty(property));

    private static decimal Decimal(JsonElement item) => item.ValueKind == JsonValueKind.String
        ? decimal.Parse(item.GetString()!, CultureInfo.InvariantCulture)
        : item.GetDecimal();
}
