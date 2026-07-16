using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Probora.Infrastructure.Persistence;

#nullable disable

namespace Probora.Infrastructure.Migrations;

[DbContext(typeof(ProboraDbContext))]
[Migration("20260716113000_RenameLegacySchemaToProbora")]
public sealed class RenameLegacySchemaToProbora : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'parai')
                 AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'probora') THEN
                ALTER SCHEMA parai RENAME TO probora;
              END IF;
            END
            $$;
            """);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'probora')
                 AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'parai') THEN
                ALTER SCHEMA probora RENAME TO parai;
              END IF;
            END
            $$;
            """);
    }
}
