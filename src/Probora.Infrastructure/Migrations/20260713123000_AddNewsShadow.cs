using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Probora.Infrastructure.Persistence;

#nullable disable

namespace Probora.Infrastructure.Migrations;

[DbContext(typeof(ProboraDbContext))]
[Migration("20260713123000_AddNewsShadow")]
public sealed class AddNewsShadow : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            CREATE TABLE probora.news_articles (
              "Id" uuid PRIMARY KEY,
              "AssetId" uuid NOT NULL REFERENCES probora.assets ("Id") ON DELETE CASCADE,
              "Title" varchar(1000) NOT NULL,
              "SourceName" varchar(255) NOT NULL,
              "SourceUrl" varchar(2048) NOT NULL,
              "PublishedAt" timestamptz NOT NULL,
              "RetrievedAt" timestamptz NOT NULL,
              "Language" varchar(16) NOT NULL,
              "ContentHash" varchar(64) NOT NULL,
              "SourceReliabilityScore" double precision NOT NULL,
              "RelevanceScore" double precision NOT NULL,
              "SentimentScore" double precision NULL,
              "EventType" varchar(64) NOT NULL,
              "NoveltyScore" double precision NOT NULL,
              "ShadowOnly" boolean NOT NULL
            );
            CREATE UNIQUE INDEX "IX_news_articles_identity" ON probora.news_articles ("AssetId", "ContentHash");
            CREATE INDEX "IX_news_articles_time" ON probora.news_articles ("AssetId", "PublishedAt");
            """);
    }

    protected override void Down(MigrationBuilder migrationBuilder) =>
        migrationBuilder.Sql("DROP TABLE IF EXISTS probora.news_articles;");
}
