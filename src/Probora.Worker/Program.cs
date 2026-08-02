using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using Probora.Infrastructure;
using Probora.Infrastructure.Persistence;
using Probora.Worker.MarketData;
using Probora.Worker.Models;
using Probora.Worker.News;
using Quartz;
using Serilog;

HostApplicationBuilder builder = Host.CreateApplicationBuilder(args);
builder.Services.AddSerilog(configuration => configuration
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console());
builder.Services.AddProboraInfrastructure(builder.Configuration);
builder.Services.Configure<BinanceOptions>(builder.Configuration.GetSection(BinanceOptions.SectionName));
builder.Services.Configure<BinanceFuturesOptions>(builder.Configuration.GetSection(BinanceFuturesOptions.SectionName));
builder.Services.Configure<TwelveDataOptions>(builder.Configuration.GetSection(TwelveDataOptions.SectionName));
builder.Services.Configure<ModelOptions>(builder.Configuration.GetSection(ModelOptions.SectionName));
builder.Services.Configure<GdeltOptions>(builder.Configuration.GetSection(GdeltOptions.SectionName));
builder.Services.Configure<MacroNewsOptions>(builder.Configuration.GetSection(MacroNewsOptions.SectionName));
builder.Services.Configure<LlmExplanationOptions>(builder.Configuration.GetSection(LlmExplanationOptions.SectionName));
builder.Services.Configure<FinnhubNewsOptions>(builder.Configuration.GetSection(FinnhubNewsOptions.SectionName));
builder.Services.AddHttpClient<BinanceRestClient>((provider, client) =>
{
    BinanceOptions options = provider.GetRequiredService<Microsoft.Extensions.Options.IOptions<BinanceOptions>>().Value;
    client.BaseAddress = new Uri(options.RestBaseUrl);
    client.Timeout = TimeSpan.FromSeconds(20);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/1.0 market-data-research");
});
builder.Services.AddHttpClient<BinanceFuturesRestClient>((provider, client) =>
{
    BinanceFuturesOptions options = provider.GetRequiredService<Microsoft.Extensions.Options.IOptions<BinanceFuturesOptions>>().Value;
    client.BaseAddress = new Uri(options.RestBaseUrl);
    client.Timeout = TimeSpan.FromSeconds(30);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/2.0 derivatives-shadow-research");
});
builder.Services.AddHttpClient<TwelveDataMarketDataClient>((provider, client) =>
{
    TwelveDataOptions options = provider.GetRequiredService<Microsoft.Extensions.Options.IOptions<TwelveDataOptions>>().Value;
    client.BaseAddress = new Uri(options.BaseUrl);
    client.Timeout = TimeSpan.FromSeconds(60);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/3.0 us-equity-shadow-research");
});
builder.Services.AddHttpClient<GdeltNewsJob>((provider, client) =>
{
    GdeltOptions options = provider.GetRequiredService<Microsoft.Extensions.Options.IOptions<GdeltOptions>>().Value;
    client.BaseAddress = new Uri(options.BaseUrl);
    client.Timeout = TimeSpan.FromSeconds(30);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/1.0 news-shadow-research");
});
builder.Services.AddHttpClient<MacroRssNewsJob>(client =>
{
    client.Timeout = TimeSpan.FromSeconds(30);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/4.0 macro-news-research");
});
builder.Services.AddHttpClient<FinnhubNewsJob>((provider, client) =>
{
    FinnhubNewsOptions options = provider
        .GetRequiredService<Microsoft.Extensions.Options.IOptions<FinnhubNewsOptions>>().Value;
    string baseUrl = options.BaseUrl.EndsWith('/') ? options.BaseUrl : options.BaseUrl + "/";
    client.BaseAddress = new Uri(baseUrl);
    client.Timeout = TimeSpan.FromSeconds(30);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/4.0 finnhub-news-research");
});
builder.Services.AddHttpClient<ILlmExplanationClient, OpenAiCompatibleExplanationClient>((provider, client) =>
{
    LlmExplanationOptions options = provider
        .GetRequiredService<Microsoft.Extensions.Options.IOptions<LlmExplanationOptions>>().Value;
    string baseUrl = options.BaseUrl.EndsWith('/') ? options.BaseUrl : options.BaseUrl + "/";
    client.BaseAddress = new Uri(baseUrl);
    client.Timeout = TimeSpan.FromSeconds(90);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("Probora/4.0 prediction-explanation-sidecar");
});
builder.Services.AddQuartz(quartz =>
{
    string connectionString = builder.Configuration.GetConnectionString("Probora")
        ?? throw new InvalidOperationException("ConnectionStrings:Probora is required.");
    quartz.SchedulerId = "ProboraWorker";
    quartz.SchedulerName = "Probora durable scheduler";
    quartz.UsePersistentStore(store =>
    {
        store.UseProperties = true;
        store.UsePostgres(connectionString);
        store.UseSystemTextJsonSerializer();
    });
    JobKey jobKey = new("binance-hourly-sync");
    quartz.AddJob<BinanceSyncJob>(options => options.WithIdentity(jobKey));
    quartz.AddTrigger(options => options
        .ForJob(jobKey)
        .WithIdentity("binance-hourly-sync-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule.WithIntervalInMinutes(10).RepeatForever()));
    JobKey promotionJob = new("model-registry-sync");
    quartz.AddJob<ModelPromotionJob>(options => options.WithIdentity(promotionJob));
    quartz.AddTrigger(options => options
        .ForJob(promotionJob)
        .WithIdentity("model-registry-sync-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule.WithIntervalInHours(1).RepeatForever()));
    JobKey predictionJob = new("daily-prediction");
    quartz.AddJob<DailyPredictionJob>(options => options.WithIdentity(predictionJob));
    quartz.AddTrigger(options => options
        .ForJob(predictionJob)
        .WithIdentity("daily-prediction-trigger")
        .WithCronSchedule("0 10-55/5 0 ? * *", schedule => schedule.InTimeZone(TimeZoneInfo.Utc)));
    quartz.AddTrigger(options => options
        .ForJob(predictionJob)
        .WithIdentity("daily-prediction-startup-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule
            .WithIntervalInMinutes(5)
            .WithRepeatCount(5)));
    quartz.AddTrigger(options => options
        .ForJob(predictionJob)
        .WithIdentity("us-equity-post-collector-prediction-trigger")
        .WithCronSchedule("0 45 5,7,9 ? * MON-SAT", schedule => schedule.InTimeZone(TimeZoneInfo.Utc)));
    JobKey outcomeJob = new("prediction-outcome-resolution");
    quartz.AddJob<PredictionOutcomeJob>(options => options.WithIdentity(outcomeJob));
    quartz.AddTrigger(options => options
        .ForJob(outcomeJob)
        .WithIdentity("prediction-outcome-resolution-trigger")
        .StartNow()
        .WithCronSchedule("0 20 * ? * *", schedule => schedule.InTimeZone(TimeZoneInfo.Utc)));
    JobKey derivativeJob = new("derivative-shadow-collector");
    quartz.AddJob<DerivativeShadowCollectorJob>(options => options.WithIdentity(derivativeJob));
    quartz.AddTrigger(options => options
        .ForJob(derivativeJob)
        .WithIdentity("derivative-shadow-collector-trigger")
        .WithCronSchedule("0 5-50/5 0 ? * *", schedule => schedule.InTimeZone(TimeZoneInfo.Utc)));
    JobKey newsJob = new("gdelt-news-shadow");
    quartz.AddJob<GdeltNewsJob>(options => options.WithIdentity(newsJob));
    quartz.AddTrigger(options => options
        .ForJob(newsJob)
        .WithIdentity("gdelt-news-shadow-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule.WithIntervalInHours(2).RepeatForever()));
    JobKey finnhubNewsJob = new("finnhub-news-shadow");
    quartz.AddJob<FinnhubNewsJob>(options => options.WithIdentity(finnhubNewsJob));
    quartz.AddTrigger(options => options
        .ForJob(finnhubNewsJob)
        .WithIdentity("finnhub-news-shadow-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule.WithIntervalInHours(1).RepeatForever()));
    JobKey macroNewsJob = new("macro-rss-news-shadow");
    quartz.AddJob<MacroRssNewsJob>(options => options.WithIdentity(macroNewsJob));
    quartz.AddTrigger(options => options
        .ForJob(macroNewsJob)
        .WithIdentity("macro-rss-news-shadow-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule.WithIntervalInHours(1).RepeatForever()));
    JobKey explanationJob = new("prediction-explanation-sidecar");
    quartz.AddJob<PredictionExplanationJob>(options => options.WithIdentity(explanationJob));
    quartz.AddTrigger(options => options
        .ForJob(explanationJob)
        .WithIdentity("prediction-explanation-sidecar-trigger")
        .StartNow()
        .WithSimpleSchedule(schedule => schedule.WithIntervalInMinutes(15).RepeatForever()));
    JobKey usEquityJob = new("us-equity-shadow-collector");
    quartz.AddJob<UsEquityShadowCollectorJob>(options => options.WithIdentity(usEquityJob));
    quartz.AddTrigger(options => options
        .ForJob(usEquityJob)
        .WithIdentity("us-equity-shadow-collector-trigger")
        .StartNow()
        .WithCronSchedule("0 15 5,7,9 ? * MON-SAT", schedule => schedule.InTimeZone(TimeZoneInfo.Utc)));
});
builder.Services.AddQuartzHostedService(options => options.WaitForJobsToComplete = true);
builder.Services.AddHostedService<BinanceWebSocketService>();
builder.Services.AddOpenTelemetry()
    .ConfigureResource(resource => resource.AddService("Probora.Worker"))
    .WithTracing(tracing => tracing.AddHttpClientInstrumentation().AddOtlpExporter())
    .WithMetrics(metrics => metrics.AddRuntimeInstrumentation().AddOtlpExporter());

using IHost host = builder.Build();
await InitialiseDatabaseAsync(host.Services);
await host.RunAsync();

static async Task InitialiseDatabaseAsync(IServiceProvider services)
{
    using IServiceScope scope = services.CreateScope();
    DatabaseInitializer initializer = scope.ServiceProvider.GetRequiredService<DatabaseInitializer>();
    await initializer.InitialiseAsync(CancellationToken.None);
}
