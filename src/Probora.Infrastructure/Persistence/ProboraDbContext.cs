using Microsoft.EntityFrameworkCore;
using Probora.Domain.Analysis;
using Probora.Domain.Markets;
using Probora.Domain.News;
using Probora.Domain.Operations;

namespace Probora.Infrastructure.Persistence;

public sealed class ProboraDbContext(DbContextOptions<ProboraDbContext> options) : DbContext(options)
{
    public DbSet<Asset> Assets => Set<Asset>();
    public DbSet<PriceBar> PriceBars => Set<PriceBar>();
    public DbSet<DerivativeDailySnapshot> DerivativeDailySnapshots => Set<DerivativeDailySnapshot>();
    public DbSet<FeatureSnapshot> FeatureSnapshots => Set<FeatureSnapshot>();
    public DbSet<ModelVersion> ModelVersions => Set<ModelVersion>();
    public DbSet<PredictionRecord> Predictions => Set<PredictionRecord>();
    public DbSet<IngestionRun> IngestionRuns => Set<IngestionRun>();
    public DbSet<DataQualityIssue> DataQualityIssues => Set<DataQualityIssue>();
    public DbSet<NewsArticle> NewsArticles => Set<NewsArticle>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.HasDefaultSchema("probora");

        modelBuilder.Entity<Asset>(entity =>
        {
            entity.ToTable("assets");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.Symbol).HasMaxLength(20);
            entity.Property(x => x.BaseAsset).HasMaxLength(20);
            entity.Property(x => x.QuoteAsset).HasMaxLength(20);
            entity.Property(x => x.AssetClass).HasMaxLength(24);
            entity.Property(x => x.Exchange).HasMaxLength(24);
            entity.Property(x => x.TradingCalendar).HasMaxLength(24);
            entity.HasIndex(x => x.Symbol).IsUnique();
            entity.HasIndex(x => new { x.AssetClass, x.IsActive, x.IsShadowEnabled });
        });

        modelBuilder.Entity<PriceBar>(entity =>
        {
            entity.ToTable("price_bars");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.Open).HasPrecision(28, 10);
            entity.Property(x => x.High).HasPrecision(28, 10);
            entity.Property(x => x.Low).HasPrecision(28, 10);
            entity.Property(x => x.Close).HasPrecision(28, 10);
            entity.Property(x => x.Volume).HasPrecision(36, 12);
            entity.Property(x => x.QuoteVolume).HasPrecision(36, 12);
            entity.Property(x => x.TakerBuyBaseVolume).HasPrecision(36, 12);
            entity.Property(x => x.TakerBuyQuoteVolume).HasPrecision(36, 12);
            entity.Property(x => x.Interval).HasMaxLength(8);
            entity.Property(x => x.Source).HasMaxLength(32);
            entity.Property(x => x.SourceChecksum).HasMaxLength(64);
            entity.HasOne(x => x.Asset).WithMany().HasForeignKey(x => x.AssetId);
            entity.HasIndex(x => new { x.AssetId, x.OpenTime, x.Interval, x.Source }).IsUnique();
            entity.HasIndex(x => new { x.AssetId, x.Interval, x.OpenTime });
        });

        modelBuilder.Entity<DerivativeDailySnapshot>(entity =>
        {
            entity.ToTable("derivative_daily_snapshots");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.Source).HasMaxLength(32);
            entity.Property(x => x.SourceChecksum).HasMaxLength(64);
            entity.HasOne(x => x.Asset).WithMany().HasForeignKey(x => x.AssetId);
            entity.HasIndex(x => new { x.AssetId, x.SnapshotTime, x.Source }).IsUnique();
            entity.HasIndex(x => new { x.AssetId, x.IsComplete, x.SnapshotTime });
        });

        modelBuilder.Entity<FeatureSnapshot>(entity =>
        {
            entity.ToTable("feature_snapshots");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.FeaturesJson).HasColumnType("jsonb");
            entity.HasOne<Asset>().WithMany().HasForeignKey(x => x.AssetId);
            entity.HasIndex(x => new { x.AssetId, x.SnapshotTime, x.FeatureSetVersion }).IsUnique();
        });

        modelBuilder.Entity<ModelVersion>(entity =>
        {
            entity.ToTable("model_versions");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.MetricsJson).HasColumnType("jsonb");
            entity.Property(x => x.AssetClass).HasMaxLength(24);
            entity.HasIndex(x => x.Version).IsUnique();
            entity.HasIndex(x => new { x.AssetClass, x.HorizonDays, x.IsProduction, x.IsShadowCandidate });
        });

        modelBuilder.Entity<PredictionRecord>(entity =>
        {
            entity.ToTable("predictions");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.PositiveFactorsJson).HasColumnType("jsonb");
            entity.Property(x => x.NegativeFactorsJson).HasColumnType("jsonb");
            entity.Property(x => x.LimitationsJson).HasColumnType("jsonb");
            entity.HasOne<Asset>().WithMany().HasForeignKey(x => x.AssetId);
            entity.HasOne<ModelVersion>().WithMany().HasForeignKey(x => x.ModelVersionId).OnDelete(DeleteBehavior.Restrict);
            entity.HasOne<FeatureSnapshot>().WithMany().HasForeignKey(x => x.FeatureSnapshotId).OnDelete(DeleteBehavior.Restrict);
            entity.HasIndex(x => new { x.AssetId, x.ModelVersionId, x.HorizonDays, x.AnalysisTime }).IsUnique();
            entity.HasIndex(x => new { x.ModelVersionId, x.IsShadow, x.AnalysisTime });
        });

        modelBuilder.Entity<IngestionRun>(entity =>
        {
            entity.ToTable("ingestion_runs");
            entity.HasKey(x => x.Id);
            entity.HasIndex(x => new { x.Source, x.Dataset, x.StartedAt });
        });

        modelBuilder.Entity<DataQualityIssue>(entity =>
        {
            entity.ToTable("data_quality_issues");
            entity.HasKey(x => x.Id);
            entity.HasOne<Asset>().WithMany().HasForeignKey(x => x.AssetId).OnDelete(DeleteBehavior.SetNull);
            entity.HasIndex(x => new { x.AssetId, x.DetectedAt });
        });

        modelBuilder.Entity<NewsArticle>(entity =>
        {
            entity.ToTable("news_articles");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.Title).HasMaxLength(1_000);
            entity.Property(x => x.SourceName).HasMaxLength(255);
            entity.Property(x => x.SourceUrl).HasMaxLength(2_048);
            entity.Property(x => x.Language).HasMaxLength(16);
            entity.Property(x => x.ContentHash).HasMaxLength(64);
            entity.Property(x => x.EventType).HasMaxLength(64);
            entity.HasOne<Asset>().WithMany().HasForeignKey(x => x.AssetId);
            entity.HasIndex(x => new { x.AssetId, x.ContentHash }).IsUnique();
            entity.HasIndex(x => new { x.AssetId, x.PublishedAt });
        });
    }
}
