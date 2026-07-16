using System.Net;
using System.Text;
using Microsoft.Extensions.Options;
using Probora.Worker.MarketData;

namespace Probora.UnitTests;

public sealed class TwelveDataMarketDataClientTests
{
    [Fact]
    public async Task GetDailyBars_UsesHeaderAuthenticationAndParsesAdjustedEodBar()
    {
        RecordingHandler handler = new(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                """
                {
                  "meta": { "symbol": "AAPL" },
                  "values": [
                    {
                      "datetime": "2026-07-13",
                      "open": "210.00",
                      "high": "215.00",
                      "low": "209.00",
                      "close": "214.00",
                      "volume": "1000"
                    }
                  ],
                  "status": "ok"
                }
                """,
                Encoding.UTF8,
                "application/json")
        });
        HttpClient httpClient = new(handler) { BaseAddress = new Uri("https://api.twelvedata.com") };
        TwelveDataOptions options = new()
        {
            Enabled = true,
            ApiKey = "secret-test-key",
            MinimumRequestIntervalMilliseconds = 0
        };
        TwelveDataMarketDataClient client = new(
            httpClient,
            Options.Create(options),
            TimeProvider.System);

        var bars = await client.GetDailyBarsAsync(
            ["AAPL"],
            new DateOnly(2026, 7, 13),
            new DateOnly(2026, 7, 13),
            CancellationToken.None);

        var bar = Assert.Single(bars);
        Assert.Equal("AAPL", bar.Symbol);
        Assert.Equal(214m, bar.Close);
        Assert.Equal(214_000m, bar.QuoteVolume);
        Assert.Equal(TwelveDataOptions.Source, bar.Source);
        Assert.Contains("adjust=all", handler.RequestUri!.Query);
        Assert.Equal("apikey secret-test-key", handler.Authorization);
        Assert.DoesNotContain("secret-test-key", handler.RequestUri.ToString());
    }

    [Fact]
    public async Task GetDailyBars_RejectsApiLevelError()
    {
        RecordingHandler handler = new(_ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                """{"code":403,"message":"plan does not allow this endpoint","status":"error"}""",
                Encoding.UTF8,
                "application/json")
        });
        HttpClient httpClient = new(handler) { BaseAddress = new Uri("https://api.twelvedata.com") };
        TwelveDataMarketDataClient client = new(
            httpClient,
            Options.Create(new TwelveDataOptions
            {
                Enabled = true,
                ApiKey = "test",
                MinimumRequestIntervalMilliseconds = 0
            }),
            TimeProvider.System);

        InvalidOperationException exception = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            client.GetDailyBarsAsync(
                ["AAPL"],
                new DateOnly(2026, 7, 13),
                new DateOnly(2026, 7, 13),
                CancellationToken.None));

        Assert.Contains("plan does not allow", exception.Message);
    }

    private sealed class RecordingHandler(Func<HttpRequestMessage, HttpResponseMessage> responseFactory)
        : HttpMessageHandler
    {
        public Uri? RequestUri { get; private set; }
        public string? Authorization { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            RequestUri = request.RequestUri;
            Authorization = request.Headers.TryGetValues("Authorization", out IEnumerable<string>? values)
                ? values.Single()
                : null;
            return Task.FromResult(responseFactory(request));
        }
    }
}
