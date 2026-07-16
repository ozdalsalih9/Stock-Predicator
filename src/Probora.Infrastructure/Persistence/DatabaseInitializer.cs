using Microsoft.EntityFrameworkCore;

namespace Probora.Infrastructure.Persistence;

public sealed class DatabaseInitializer(ProboraDbContext dbContext)
{
    public async Task InitialiseAsync(CancellationToken cancellationToken)
    {
        // API and Worker may start together on a clean deployment. PostgreSQL's
        // session-level advisory lock ensures that only one process applies EF
        // migrations while the other waits and then observes the completed schema.
        const long migrationLockId = 5_266_179_220_260_713_001;
        await dbContext.Database.OpenConnectionAsync(cancellationToken);

        try
        {
            await dbContext.Database.ExecuteSqlRawAsync(
                $"SELECT pg_advisory_lock({migrationLockId})",
                cancellationToken);
            await dbContext.Database.MigrateAsync(cancellationToken);
        }
        finally
        {
            await dbContext.Database.ExecuteSqlRawAsync(
                $"SELECT pg_advisory_unlock({migrationLockId})",
                cancellationToken);
            await dbContext.Database.CloseConnectionAsync();
        }
    }
}
