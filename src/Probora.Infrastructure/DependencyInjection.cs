using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Probora.Application.Abstractions;
using Probora.Infrastructure.Persistence;
using Probora.Infrastructure.Queries;

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
        services.AddSingleton(TimeProvider.System);
        return services;
    }
}
