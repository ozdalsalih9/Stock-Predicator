using Microsoft.AspNetCore.SignalR;
using Probora.Api.Hubs;
using Probora.Application.Abstractions;
using Probora.Contracts.System;

namespace Probora.Api.Hubs;

public sealed class MarketPriceBroadcaster(
    IServiceScopeFactory scopeFactory,
    IHubContext<MarketHub> hubContext,
    ILogger<MarketPriceBroadcaster> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using PeriodicTimer timer = new(TimeSpan.FromSeconds(15));
        while (await timer.WaitForNextTickAsync(stoppingToken))
        {
            try
            {
                using IServiceScope scope = scopeFactory.CreateScope();
                IProboraQueryService queries = scope.ServiceProvider.GetRequiredService<IProboraQueryService>();
                IReadOnlyList<MarketPriceUpdate> prices = await queries.GetLatestPricesAsync(stoppingToken);
                await hubContext.Clients.All.SendAsync("marketPrices", prices, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exception)
            {
                logger.LogWarning(exception, "Could not broadcast latest market prices.");
            }
        }
    }
}
