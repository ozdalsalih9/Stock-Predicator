using System.Globalization;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;
using Probora.Application.Abstractions;
using Probora.Domain.Markets;

namespace Probora.Worker.MarketData;

public sealed class BinanceWebSocketService(
    IServiceScopeFactory scopeFactory,
    IOptions<BinanceOptions> options,
    ILogger<BinanceWebSocketService> logger) : BackgroundService
{
    private readonly BinanceOptions _options = options.Value;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!_options.EnableWebSocket)
        {
            logger.LogInformation("Binance WebSocket ingestion is disabled.");
            return;
        }

        int failureCount = 0;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ConsumeAsync(stoppingToken);
                failureCount = 0;
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exception)
            {
                failureCount++;
                TimeSpan delay = TimeSpan.FromSeconds(Math.Min(60, Math.Pow(2, Math.Min(failureCount, 6))));
                logger.LogWarning(exception, "Binance WebSocket disconnected; reconnecting in {Delay}.", delay);
                await Task.Delay(delay, stoppingToken);
            }
        }
    }

    private async Task ConsumeAsync(CancellationToken cancellationToken)
    {
        string streams = string.Join('/', AssetCatalog.Crypto.Select(x => $"{x.Symbol.ToLowerInvariant()}@kline_1h"));
        Uri uri = new($"{_options.WebSocketBaseUrl.TrimEnd('/')}/stream?streams={streams}");
        using ClientWebSocket socket = new();
        socket.Options.KeepAliveInterval = TimeSpan.FromSeconds(20);
        await socket.ConnectAsync(uri, cancellationToken);
        logger.LogInformation("Connected to Binance combined kline stream.");

        byte[] buffer = new byte[32 * 1024];
        while (socket.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
        {
            using MemoryStream message = new();
            WebSocketReceiveResult result;
            do
            {
                result = await socket.ReceiveAsync(buffer, cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "reconnect", cancellationToken);
                    return;
                }
                message.Write(buffer, 0, result.Count);
            } while (!result.EndOfMessage);

            PriceBarCandidate? bar = ParseFinalBar(message.ToArray());
            if (bar is null)
            {
                continue;
            }

            using IServiceScope scope = scopeFactory.CreateScope();
            IPriceBarWriter writer = scope.ServiceProvider.GetRequiredService<IPriceBarWriter>();
            await writer.UpsertAsync([bar], cancellationToken);
        }
    }

    private static PriceBarCandidate? ParseFinalBar(byte[] payload)
    {
        using JsonDocument document = JsonDocument.Parse(payload);
        JsonElement data = document.RootElement.GetProperty("data");
        JsonElement kline = data.GetProperty("k");
        if (!kline.GetProperty("x").GetBoolean())
        {
            return null;
        }

        static decimal Number(JsonElement element, string name) =>
            decimal.Parse(element.GetProperty(name).GetString()!, CultureInfo.InvariantCulture);

        return new PriceBarCandidate(
            data.GetProperty("s").GetString()!,
            BinanceRestClient.FromUnixTimestamp(kline.GetProperty("t").GetInt64()),
            BinanceRestClient.FromUnixTimestamp(kline.GetProperty("T").GetInt64()),
            kline.GetProperty("i").GetString()!,
            Number(kline, "o"),
            Number(kline, "h"),
            Number(kline, "l"),
            Number(kline, "c"),
            Number(kline, "v"),
            Number(kline, "q"),
            kline.GetProperty("n").GetInt64(),
            Number(kline, "V"),
            Number(kline, "Q"),
            true,
            DateTimeOffset.UtcNow);
    }
}
