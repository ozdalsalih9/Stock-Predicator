using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Probora.Application.Abstractions;
using Probora.Infrastructure.Persistence;
using Probora.Infrastructure.Queries;
using Probora.Infrastructure.Research;

namespace Probora.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddProboraInfrastructure(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        string connectionString = configuration.GetConnectionString("Probora")
            ?? throw new InvalidOperationException("ConnectionStrings:Probora is required.");

        services.AddDbContext<ProboraDbContext>(options =>
            options.UseNpgsql(connectionString, npgsql =>
            {
                // Keep the migration ledger outside the application default
                // schema so every process resolves the same table on first boot.
                npgsql.MigrationsHistoryTable("__EFMigrationsHistory", "public");
                npgsql.EnableRetryOnFailure(5);
            }));
        services.AddScoped<DatabaseInitializer>();
        services.AddScoped<IProboraQueryService, ProboraQueryService>();
        services.AddScoped<IPriceBarWriter, PriceBarWriter>();
        IConfigurationSection research = configuration.GetSection(ResearchPipelineOptions.SectionName);
        services.Configure<ResearchPipelineOptions>(options =>
        {
            options.StatePath = research[nameof(options.StatePath)] ?? options.StatePath;
            options.CoveragePath = research[nameof(options.CoveragePath)] ?? options.CoveragePath;
            options.FrozenUniverseSize = ReadInt(research, nameof(options.FrozenUniverseSize), options.FrozenUniverseSize);
            options.CurrentUniverseSize = ReadInt(research, nameof(options.CurrentUniverseSize), options.CurrentUniverseSize);
            options.BatchSize = ReadInt(research, nameof(options.BatchSize), options.BatchSize);
            options.BatchCount = ReadInt(research, nameof(options.BatchCount), options.BatchCount);
            options.RequiredDailyCoverage = ReadDouble(
                research,
                nameof(options.RequiredDailyCoverage),
                options.RequiredDailyCoverage);
        });
        services.AddSingleton<IResearchPipelineStatusReader, ResearchPipelineStatusReader>();
        services.AddSingleton(TimeProvider.System);
        return services;
    }

    private static int ReadInt(IConfiguration section, string key, int fallback) =>
        int.TryParse(section[key], out int value) ? value : fallback;

    private static double ReadDouble(IConfiguration section, string key, double fallback) =>
        double.TryParse(section[key], System.Globalization.CultureInfo.InvariantCulture, out double value) ? value : fallback;
}
