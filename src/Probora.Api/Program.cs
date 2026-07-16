using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Http.HttpResults;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using Probora.Api.Hubs;
using Probora.Api.Middleware;
using Probora.Application.Abstractions;
using Probora.Contracts.Analysis;
using Probora.Contracts.Assets;
using Probora.Contracts.News;
using Probora.Contracts.System;
using Probora.Infrastructure;
using Probora.Infrastructure.Persistence;
using Serilog;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);
builder.Services.AddSerilog(configuration => configuration
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console());
builder.Services.AddProboraInfrastructure(builder.Configuration);
builder.Services.AddProblemDetails();
builder.Services.AddOpenApi();
builder.Services.AddSignalR();
builder.Services.AddHostedService<MarketPriceBroadcaster>();
builder.Services.AddHealthChecks();
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(context =>
        RateLimitPartition.GetFixedWindowLimiter(
            context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
            _ => new FixedWindowRateLimiterOptions
            {
                PermitLimit = 120,
                Window = TimeSpan.FromMinutes(1),
                QueueLimit = 0,
                AutoReplenishment = true
            }));
});
builder.Services.AddOpenTelemetry()
    .ConfigureResource(resource => resource.AddService("Probora.Api"))
    .WithTracing(tracing => tracing.AddAspNetCoreInstrumentation().AddHttpClientInstrumentation().AddOtlpExporter())
    .WithMetrics(metrics => metrics.AddAspNetCoreInstrumentation().AddRuntimeInstrumentation().AddOtlpExporter());

WebApplication app = builder.Build();
app.UseExceptionHandler();
app.UseMiddleware<SecurityHeadersMiddleware>();
app.UseRateLimiter();
app.UseMiddleware<ETagMiddleware>();

await InitialiseDatabaseAsync(app.Services);

app.MapOpenApi();
app.MapHealthChecks("/health/live");
app.MapGet("/health/ready", async (ProboraDbContext db, CancellationToken cancellationToken) =>
    await db.Database.CanConnectAsync(cancellationToken)
        ? Results.Ok(new { status = "ready" })
        : Results.Problem(statusCode: 503, title: "Database unavailable"));
app.MapHub<MarketHub>("/hubs/market");

RouteGroupBuilder api = app.MapGroup("/api/v1");
api.MapGet("/assets", async (IProboraQueryService queries, CancellationToken cancellationToken) =>
    Results.Ok(await queries.GetAssetsAsync(cancellationToken)));

api.MapGet("/assets/{symbol}/bars", async Task<Results<Ok<IReadOnlyList<PriceBarResponse>>, ProblemHttpResult>> (
    string symbol,
    string? interval,
    DateTimeOffset? from,
    DateTimeOffset? to,
    int? limit,
    IProboraQueryService queries,
    CancellationToken cancellationToken) =>
{
    interval ??= "1h";
    if (interval is not ("1h" or "1d"))
    {
        return TypedResults.Problem(statusCode: 400, title: "Unsupported interval", detail: "Use 1h or 1d.");
    }
    IReadOnlyList<PriceBarResponse>? result = await queries.GetBarsAsync(symbol, interval, from, to, Math.Clamp(limit ?? 500, 1, 2_000), cancellationToken);
    return result is null
        ? TypedResults.Problem(statusCode: 404, title: "Asset not found")
        : TypedResults.Ok(result);
});

api.MapGet("/assets/{symbol}/analyses/latest", async Task<Results<Ok<AnalysisResponse>, ProblemHttpResult>> (
    string symbol,
    int horizonDays,
    bool? includeShadowPreview,
    IProboraQueryService queries,
    CancellationToken cancellationToken) =>
{
    if (horizonDays is not (30 or 90))
    {
        return TypedResults.Problem(statusCode: 400, title: "Unsupported horizon", detail: "Use 30 or 90 days.");
    }
    AnalysisResponse? result = await queries.GetLatestAnalysisAsync(
        symbol,
        horizonDays,
        includeShadowPreview ?? false,
        cancellationToken);
    return result is null
        ? TypedResults.Problem(statusCode: 404, title: "Analysis not available")
        : TypedResults.Ok(result);
});

api.MapGet("/assets/{symbol}/news", async Task<Results<Ok<IReadOnlyList<NewsArticleResponse>>, ProblemHttpResult>> (
    string symbol,
    int? limit,
    IProboraQueryService queries,
    CancellationToken cancellationToken) =>
{
    IReadOnlyList<NewsArticleResponse>? result = await queries.GetNewsAsync(
        symbol,
        Math.Clamp(limit ?? 30, 1, 100),
        cancellationToken);
    return result is null
        ? TypedResults.Problem(statusCode: 404, title: "Asset not found")
        : TypedResults.Ok(result);
});

api.MapGet("/models/{version}/card", async Task<Results<Ok<ModelCardResponse>, ProblemHttpResult>> (
    string version,
    IProboraQueryService queries,
    CancellationToken cancellationToken) =>
{
    ModelCardResponse? result = await queries.GetModelCardAsync(version, cancellationToken);
    return result is null
        ? TypedResults.Problem(statusCode: 404, title: "Model not found")
        : TypedResults.Ok(result);
});

api.MapGet("/performance", async Task<Results<Ok<PerformanceResponse>, ProblemHttpResult>> (
    string? symbol,
    int horizonDays,
    IProboraQueryService queries,
    CancellationToken cancellationToken) =>
{
    if (horizonDays is not (30 or 90))
    {
        return TypedResults.Problem(statusCode: 400, title: "Unsupported horizon", detail: "Use 30 or 90 days.");
    }
    PerformanceResponse? result = await queries.GetPerformanceAsync(symbol, horizonDays, cancellationToken);
    return result is null
        ? TypedResults.Problem(statusCode: 404, title: "Performance report not available")
        : TypedResults.Ok(result);
});

api.MapGet("/system/freshness", async (IProboraQueryService queries, CancellationToken cancellationToken) =>
    Results.Ok(await queries.GetFreshnessAsync(cancellationToken)));

api.MapGet("/system/shadow-collector", async (IProboraQueryService queries, CancellationToken cancellationToken) =>
    Results.Ok(await queries.GetShadowCollectorDashboardAsync(cancellationToken)));

api.MapGet("/system/us-equity-shadow", async (IProboraQueryService queries, CancellationToken cancellationToken) =>
    Results.Ok(await queries.GetUsEquityShadowDashboardAsync(cancellationToken)));

api.MapGet("/system/shadow-predictions", async (IProboraQueryService queries, CancellationToken cancellationToken) =>
    Results.Ok(await queries.GetShadowPredictionDashboardAsync(cancellationToken)));

await app.RunAsync();

static async Task InitialiseDatabaseAsync(IServiceProvider services)
{
    using IServiceScope scope = services.CreateScope();
    DatabaseInitializer initializer = scope.ServiceProvider.GetRequiredService<DatabaseInitializer>();
    await initializer.InitialiseAsync(CancellationToken.None);
}

public partial class Program;
