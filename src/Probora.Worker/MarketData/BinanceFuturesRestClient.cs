using System.Globalization;
using System.Net;
using System.Text.Json;
using Microsoft.Extensions.Options;

namespace Probora.Worker.MarketData;

public sealed class BinanceFuturesRestClient(
    HttpClient httpClient,
    IOptions<BinanceFuturesOptions> options,
    TimeProvider timeProvider,
    ILogger<BinanceFuturesRestClient> logger)
{
    private readonly BinanceFuturesOptions _options = options.Value;
    private readonly SemaphoreSlim _requestGate = new(1, 1);
    private DateTimeOffset _nextRequestAt = DateTimeOffset.MinValue;

    public async Task<DateTimeOffset> GetServerTimeAsync(CancellationToken cancellationToken)
    {
        using JsonDocument document = await GetJsonAsync("/fapi/v1/time", cancellationToken);
        return DateTimeOffset.FromUnixTimeMilliseconds(document.RootElement.GetProperty("serverTime").GetInt64());
    }

    public async Task<DerivativeSnapshotValues> GetDailySnapshotAsync(
        string symbol,
        DateTimeOffset cutoff,
        CancellationToken cancellationToken)
    {
        DateTimeOffset start = cutoff.AddDays(-1);
        long startTime = start.ToUnixTimeMilliseconds();
        long endTime = cutoff.ToUnixTimeMilliseconds() - 1;
        string escapedSymbol = Uri.EscapeDataString(symbol);
        string window = $"startTime={startTime}&endTime={endTime}";

        using JsonDocument futuresDocument = await GetJsonAsync(
            $"/fapi/v1/klines?symbol={escapedSymbol}&interval=1h&{window}&limit=24",
            cancellationToken);
        using JsonDocument premiumDocument = await GetJsonAsync(
            $"/fapi/v1/premiumIndexKlines?symbol={escapedSymbol}&interval=1h&{window}&limit=24",
            cancellationToken);
        using JsonDocument fundingDocument = await GetJsonAsync(
            $"/fapi/v1/fundingRate?symbol={escapedSymbol}&{window}&limit=100",
            cancellationToken);
        using JsonDocument openInterestDocument = await GetJsonAsync(
            $"/futures/data/openInterestHist?symbol={escapedSymbol}&period=5m&{window}&limit=500",
            cancellationToken);
        using JsonDocument longShortDocument = await GetJsonAsync(
            $"/futures/data/globalLongShortAccountRatio?symbol={escapedSymbol}&period=5m&{window}&limit=500",
            cancellationToken);
        using JsonDocument takerDocument = await GetJsonAsync(
            $"/futures/data/takerlongshortRatio?symbol={escapedSymbol}&period=5m&startTime={startTime}" +
            $"&endTime={cutoff.AddMinutes(5).ToUnixTimeMilliseconds() - 1}&limit=500",
            cancellationToken);

        IReadOnlyList<TimedValue> takerValues = ParseObjectValues(
                takerDocument.RootElement,
                "timestamp",
                "buySellRatio")
            .Where(x => x.Time >= start && x.Time < cutoff)
            .ToArray();

        return DerivativeSnapshotAssembler.Assemble(
            cutoff,
            ParseFuturesKlines(futuresDocument.RootElement),
            ParsePremiumKlines(premiumDocument.RootElement),
            ParseObjectValues(fundingDocument.RootElement, "fundingTime", "fundingRate"),
            ParseObjectValues(openInterestDocument.RootElement, "timestamp", "sumOpenInterestValue"),
            ParseObjectValues(longShortDocument.RootElement, "timestamp", "longShortRatio"),
            takerValues);
    }

    private async Task<JsonDocument> GetJsonAsync(string uri, CancellationToken cancellationToken)
    {
        Exception? lastException = null;
        for (int attempt = 1; attempt <= Math.Max(1, _options.MaximumRequestAttempts); attempt++)
        {
            using HttpResponseMessage response = await SendRateLimitedAsync(uri, cancellationToken);
            if (response.IsSuccessStatusCode)
            {
                await using Stream stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                return await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
            }

            string body = await response.Content.ReadAsStringAsync(cancellationToken);
            bool retryable = response.StatusCode == HttpStatusCode.TooManyRequests ||
                (int)response.StatusCode == 418 ||
                (int)response.StatusCode >= 500;
            lastException = new HttpRequestException(
                $"Binance Futures returned {(int)response.StatusCode} for {uri}: {body}",
                null,
                response.StatusCode);
            if (!retryable || attempt == _options.MaximumRequestAttempts)
            {
                throw lastException;
            }

            TimeSpan delay = RetryDelay(response, attempt);
            logger.LogWarning(
                "Binance Futures request {Uri} returned {Status}; retrying in {Delay} after attempt {Attempt}.",
                uri,
                (int)response.StatusCode,
                delay,
                attempt);
            await Task.Delay(delay, timeProvider, cancellationToken);
        }
        throw lastException ?? new HttpRequestException($"Binance Futures request failed: {uri}");
    }

    private async Task<HttpResponseMessage> SendRateLimitedAsync(string uri, CancellationToken cancellationToken)
    {
        await _requestGate.WaitAsync(cancellationToken);
        try
        {
            DateTimeOffset now = timeProvider.GetUtcNow();
            if (_nextRequestAt > now)
            {
                await Task.Delay(_nextRequestAt - now, timeProvider, cancellationToken);
            }

            HttpResponseMessage response = await httpClient.GetAsync(uri, cancellationToken);
            DateTimeOffset sentAt = timeProvider.GetUtcNow();
            _nextRequestAt = sentAt.AddMilliseconds(Math.Max(0, _options.MinimumRequestIntervalMilliseconds));
            if (TryGetUsedWeight(response, out int usedWeight) && usedWeight >= _options.UsedWeightSoftLimit)
            {
                _nextRequestAt = Max(_nextRequestAt, sentAt.AddSeconds(10));
                logger.LogWarning(
                    "Binance Futures used weight {UsedWeight} reached soft limit {SoftLimit}; requests are being paced.",
                    usedWeight,
                    _options.UsedWeightSoftLimit);
            }
            return response;
        }
        finally
        {
            _requestGate.Release();
        }
    }

    private static TimeSpan RetryDelay(HttpResponseMessage response, int attempt)
    {
        if (response.Headers.RetryAfter?.Delta is TimeSpan delta)
        {
            return delta;
        }
        if (response.Headers.RetryAfter?.Date is DateTimeOffset retryAt)
        {
            return retryAt > DateTimeOffset.UtcNow ? retryAt - DateTimeOffset.UtcNow : TimeSpan.FromSeconds(1);
        }
        return TimeSpan.FromSeconds(Math.Min(30, Math.Pow(2, attempt)) + Random.Shared.NextDouble());
    }

    private static bool TryGetUsedWeight(HttpResponseMessage response, out int usedWeight)
    {
        usedWeight = 0;
        return response.Headers.TryGetValues("X-MBX-USED-WEIGHT-1M", out IEnumerable<string>? values) &&
            int.TryParse(values.FirstOrDefault(), NumberStyles.Integer, CultureInfo.InvariantCulture, out usedWeight);
    }

    private static DateTimeOffset Max(DateTimeOffset left, DateTimeOffset right) => left >= right ? left : right;

    private static IReadOnlyList<FuturesKlinePoint> ParseFuturesKlines(JsonElement root) => root
        .EnumerateArray()
        .Select(item => new FuturesKlinePoint(
            Milliseconds(item[0]),
            Milliseconds(item[6]),
            Double(item[5]),
            Double(item[7]),
            Double(item[9])))
        .ToArray();

    private static IReadOnlyList<TimedKlineValue> ParsePremiumKlines(JsonElement root) => root
        .EnumerateArray()
        .Select(item => new TimedKlineValue(
            Milliseconds(item[0]),
            Milliseconds(item[6]),
            Double(item[4])))
        .ToArray();

    private static IReadOnlyList<TimedValue> ParseObjectValues(
        JsonElement root,
        string timeProperty,
        string valueProperty) => root
        .EnumerateArray()
        .Select(item => new TimedValue(
            Milliseconds(item.GetProperty(timeProperty)),
            Double(item.GetProperty(valueProperty))))
        .ToArray();

    private static DateTimeOffset Milliseconds(JsonElement element) =>
        DateTimeOffset.FromUnixTimeMilliseconds(element.GetInt64());

    private static double Double(JsonElement element) => double.Parse(
        element.ValueKind == JsonValueKind.String ? element.GetString()! : element.GetRawText(),
        CultureInfo.InvariantCulture);
}
