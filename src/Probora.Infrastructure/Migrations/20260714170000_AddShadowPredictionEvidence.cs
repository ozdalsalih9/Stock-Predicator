using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Probora.Infrastructure.Persistence;

#nullable disable

namespace Probora.Infrastructure.Migrations;

[DbContext(typeof(ProboraDbContext))]
[Migration("20260714170000_AddShadowPredictionEvidence")]
public sealed class AddShadowPredictionEvidence : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            ALTER TABLE probora.model_versions
              ADD COLUMN "IsShadowCandidate" boolean NOT NULL DEFAULT false;
            ALTER TABLE probora.predictions
              ADD COLUMN "IsShadow" boolean NOT NULL DEFAULT false;

            DROP INDEX IF EXISTS probora."IX_model_versions_asset_production";
            CREATE INDEX "IX_model_versions_asset_channel"
              ON probora.model_versions
              ("AssetClass", "HorizonDays", "IsProduction", "IsShadowCandidate");

            DROP INDEX IF EXISTS probora."IX_predictions_identity";
            CREATE UNIQUE INDEX "IX_predictions_model_identity"
              ON probora.predictions
              ("AssetId", "ModelVersionId", "HorizonDays", "AnalysisTime");
            CREATE INDEX "IX_predictions_shadow_lookup"
              ON probora.predictions ("ModelVersionId", "IsShadow", "AnalysisTime");

            WITH ranked AS (
              SELECT "Id",
                     row_number() OVER (
                       PARTITION BY "AssetClass", "HorizonDays"
                       ORDER BY "TrainedAt" DESC, "Version" DESC
                     ) AS row_rank
              FROM probora.model_versions
              WHERE "AssetClass" = 'crypto' AND NOT "IsProduction"
            )
            UPDATE probora.model_versions AS model
            SET "IsShadowCandidate" = true
            FROM ranked
            WHERE model."Id" = ranked."Id" AND ranked.row_rank = 1;
            """);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            DROP INDEX IF EXISTS probora."IX_predictions_shadow_lookup";
            DROP INDEX IF EXISTS probora."IX_predictions_model_identity";
            CREATE UNIQUE INDEX "IX_predictions_identity"
              ON probora.predictions ("AssetId", "HorizonDays", "AnalysisTime");
            ALTER TABLE probora.predictions DROP COLUMN IF EXISTS "IsShadow";

            DROP INDEX IF EXISTS probora."IX_model_versions_asset_channel";
            ALTER TABLE probora.model_versions DROP COLUMN IF EXISTS "IsShadowCandidate";
            CREATE INDEX "IX_model_versions_asset_production"
              ON probora.model_versions ("AssetClass", "HorizonDays", "IsProduction");
            """);
    }
}
