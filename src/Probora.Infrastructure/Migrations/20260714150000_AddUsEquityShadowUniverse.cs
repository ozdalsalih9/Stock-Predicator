using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Probora.Infrastructure.Persistence;

#nullable disable

namespace Probora.Infrastructure.Migrations;

[DbContext(typeof(ProboraDbContext))]
[Migration("20260714150000_AddUsEquityShadowUniverse")]
public sealed class AddUsEquityShadowUniverse : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            ALTER TABLE probora.assets ADD COLUMN "AssetClass" varchar(24) NOT NULL DEFAULT 'crypto';
            ALTER TABLE probora.assets ADD COLUMN "Exchange" varchar(24) NOT NULL DEFAULT 'BINANCE';
            ALTER TABLE probora.assets ADD COLUMN "TradingCalendar" varchar(24) NOT NULL DEFAULT '24x7';
            ALTER TABLE probora.assets ADD COLUMN "IsShadowEnabled" boolean NOT NULL DEFAULT true;
            CREATE INDEX "IX_assets_shadow_universe"
              ON probora.assets ("AssetClass", "IsActive", "IsShadowEnabled");
            ALTER TABLE probora.model_versions ADD COLUMN "AssetClass" varchar(24) NOT NULL DEFAULT 'crypto';
            DROP INDEX IF EXISTS probora."IX_model_versions_production";
            CREATE INDEX "IX_model_versions_asset_production"
              ON probora.model_versions ("AssetClass", "HorizonDays", "IsProduction");

            INSERT INTO probora.assets
              ("Id", "Symbol", "BaseAsset", "QuoteAsset", "DisplayName", "DataStartsAt", "IsActive",
               "AssetClass", "Exchange", "TradingCalendar", "IsShadowEnabled")
            VALUES
              ('00000000-0000-0000-0000-000000000101', 'SPY', 'SPY', 'USD', 'SPDR S&P 500 ETF', '1993-01-29T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000102', 'QQQ', 'QQQ', 'USD', 'Invesco QQQ Trust', '1999-03-10T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000103', 'IWM', 'IWM', 'USD', 'iShares Russell 2000 ETF', '2000-05-22T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000104', 'DIA', 'DIA', 'USD', 'SPDR Dow Jones Industrial Average ETF', '1998-01-20T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000105', 'XLK', 'XLK', 'USD', 'Technology Select Sector SPDR', '1998-12-22T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000106', 'XLF', 'XLF', 'USD', 'Financial Select Sector SPDR', '1998-12-22T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000107', 'XLE', 'XLE', 'USD', 'Energy Select Sector SPDR', '1998-12-22T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000108', 'XLV', 'XLV', 'USD', 'Health Care Select Sector SPDR', '1998-12-22T00:00:00Z', false, 'us_equity', 'ARCA', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000109', 'AAPL', 'AAPL', 'USD', 'Apple', '1980-12-12T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000110', 'MSFT', 'MSFT', 'USD', 'Microsoft', '1986-03-13T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000111', 'NVDA', 'NVDA', 'USD', 'NVIDIA', '1999-01-22T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000112', 'AMZN', 'AMZN', 'USD', 'Amazon', '1997-05-15T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000113', 'GOOGL', 'GOOGL', 'USD', 'Alphabet', '2004-08-19T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000114', 'META', 'META', 'USD', 'Meta Platforms', '2012-05-18T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000115', 'TSLA', 'TSLA', 'USD', 'Tesla', '2010-06-29T00:00:00Z', false, 'us_equity', 'NASDAQ', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000116', 'JPM', 'JPM', 'USD', 'JPMorgan Chase', '1980-01-02T00:00:00Z', false, 'us_equity', 'NYSE', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000117', 'V', 'V', 'USD', 'Visa', '2008-03-19T00:00:00Z', false, 'us_equity', 'NYSE', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000118', 'XOM', 'XOM', 'USD', 'Exxon Mobil', '1980-01-02T00:00:00Z', false, 'us_equity', 'NYSE', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000119', 'UNH', 'UNH', 'USD', 'UnitedHealth Group', '1984-10-17T00:00:00Z', false, 'us_equity', 'NYSE', 'XNYS', true),
              ('00000000-0000-0000-0000-000000000120', 'WMT', 'WMT', 'USD', 'Walmart', '1980-01-02T00:00:00Z', false, 'us_equity', 'NYSE', 'XNYS', true);
            """);
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql(
            """
            DELETE FROM probora.assets WHERE "AssetClass" = 'us_equity';
            DROP INDEX IF EXISTS probora."IX_model_versions_asset_production";
            ALTER TABLE probora.model_versions DROP COLUMN IF EXISTS "AssetClass";
            CREATE INDEX "IX_model_versions_production"
              ON probora.model_versions ("HorizonDays", "IsProduction");
            DROP INDEX IF EXISTS probora."IX_assets_shadow_universe";
            ALTER TABLE probora.assets DROP COLUMN IF EXISTS "IsShadowEnabled";
            ALTER TABLE probora.assets DROP COLUMN IF EXISTS "TradingCalendar";
            ALTER TABLE probora.assets DROP COLUMN IF EXISTS "Exchange";
            ALTER TABLE probora.assets DROP COLUMN IF EXISTS "AssetClass";
            """);
    }
}
