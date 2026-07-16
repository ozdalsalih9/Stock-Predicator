using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Probora.Infrastructure.Persistence;

#nullable disable

namespace Probora.Infrastructure.Migrations;

[DbContext(typeof(ProboraDbContext))]
[Migration("20260715121000_AddModelOutputEligibility")]
public sealed class AddModelOutputEligibility : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            ALTER TABLE probora.model_versions
              ADD COLUMN "DirectionEligible" boolean NOT NULL DEFAULT false,
              ADD COLUMN "ScenarioEligible" boolean NOT NULL DEFAULT false;

            UPDATE probora.model_versions
            SET "DirectionEligible" = true,
                "ScenarioEligible" = true
            WHERE "IsProduction" = true;
            """);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            ALTER TABLE probora.model_versions
              DROP COLUMN IF EXISTS "DirectionEligible",
              DROP COLUMN IF EXISTS "ScenarioEligible";
            """);
    }
}
