using System.Globalization;
using System.Text.Json;
using Microsoft.Extensions.Options;
using Probora.Domain.Markets;

namespace Probora.Worker.MarketData;

public sealed class BinanceRestClient(HttpClient httpClient, IOptions<BinanceOptions> options)
{
    private readonly BinanceOptions _options = options.Value;

    public async Task<IReadOnlyList<PriceBarCandidate>> GetKlinesAsync(
        string symbol,
        string interval,
        int limit,
        CancellationToken cancellationToken)
        => await GetKlinesAsync(symbol, interval, limit, null, null, cancellationToken);

    public async Task<IReadOnlyList<PriceBarCandidate>> GetKlinesAsync(
        string symbol,
        string interval,
        int limit,
        DateTimeOffset? startTime,
        DateTimeOffset? endTime,
        CancellationToken cancellationToken)
    {
        string uri = $"/api/v3/klines?symbol={Uri.EscapeDataString(symbol)}&interval={Uri.EscapeDataString(interval)}&limit={Math.Clamp(limit, 1, 1000)}";
        if (startTime.HasValue)
        {
            uri += $"&startTime={startTime.Value.ToUnixTimeMilliseconds()}";
        }
        if (endTime.HasValue)
        {
            uri += $"&endTime={endTime.Value.ToUnixTimeMilliseconds()}";
        }
        using HttpResponseMessage response = await httpClient.GetAsync(uri, cancellationToken);
        response.EnsureSuccessStatusCode();
        await using Stream stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using JsonDocument document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
        DateTimeOffset now = DateTimeOffset.UtcNow;

        return document.RootElement.EnumerateArray()
            .Select(item => ParseKline(symbol, interval, item, now))
            .ToArray();
    }

    private static PriceBarCandidate ParseKline(
        string symbol,
        string interval,
        JsonElement item,
        DateTimeOffset availableAt)
    {
        JsonElement.ArrayEnumerator values = item.EnumerateArray();
        JsonElement[] cells = values.ToArray();
        DateTimeOffset openTime = FromUnixTimestamp(cells[0].GetInt64());
        DateTimeOffset closeTime = FromUnixTimestamp(cells[6].GetInt64());
        return new PriceBarCandidate(
            symbol,
            openTime,
            closeTime,
            interval,
            Decimal(cells[1]),
            Decimal(cells[2]),
            Decimal(cells[3]),
            Decimal(cells[4]),
            Decimal(cells[5]),
            Decimal(cells[7]),
            cells[8].GetInt64(),
            Decimal(cells[9]),
            Decimal(cells[10]),
            closeTime <= availableAt,
            availableAt);
    }

    public static DateTimeOffset FromUnixTimestamp(long timestamp)
    {
        // Binance archive files changed to microseconds in 2025; REST defaults to milliseconds.
        long milliseconds = timestamp >= 100_000_000_000_000 ? timestamp / 1_000 : timestamp;
        return DateTimeOffset.FromUnixTimeMilliseconds(milliseconds);
    }

    private static decimal Decimal(JsonElement value) =>
        decimal.Parse(value.GetString() ?? throw new InvalidDataException("Missing decimal value."), CultureInfo.InvariantCulture);
}
