using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Microsoft.EntityFrameworkCore;
using Probora.Domain.Analysis;
using Probora.Domain.Markets;
using Probora.Infrastructure.Persistence;
using Probora.ML.Runtime.Training;
using Probora.Worker.MarketData;
using Quartz;

namespace Probora.Worker.Models;

[DisallowConcurrentExecution]
public sealed class PredictionOutcomeJob(
    ProboraDbContext dbContext,
    TimeProvider timeProvider,
    ILogger<PredictionOutcomeJob> logger) : IJob
{
    private const int BatchSize = 1_000;

    public async Task Execute(IJobExecutionContext context)
    {
        CancellationToken cancellationToken = context.CancellationToken;
        DateTimeOffset now = timeProvider.GetUtcNow();
        DateTimeOffset youngestPossibleMaturity = now.AddDays(-30);
        List<PredictionRecord> predictions = await dbContext.Predictions.AsNoTracking()
            .Where(prediction =>
                prediction.AnalysisTime <= youngestPossibleMaturity &&
                prediction.NeutralBandThreshold != null &&
                prediction.BaselineDownProbability != null &&
                prediction.BaselineNeutralProbability != null &&
                prediction.BaselineUpProbability != null &&
                !dbContext.PredictionOutcomes.Any(outcome => outcome.PredictionId == prediction.Id))
            .OrderBy(prediction => prediction.AnalysisTime)
            .Take(BatchSize)
            .ToListAsync(cancellationToken);
        if (predictions.Count == 0)
        {
            logger.LogInformation("No mature prediction outcome is waiting for resolution.");
            return;
        }

        Dictionary<Guid, ModelVersion> models = await dbContext.ModelVersions.AsNoTracking()
            .Where(model => predictions.Select(prediction => prediction.ModelVersionId).Contains(model.Id))
            .ToDictionaryAsync(model => model.Id, cancellationToken);
        Dictionary<Guid, Asset> assets = await dbContext.Assets.AsNoTracking()
            .Where(asset => predictions.Select(prediction => prediction.AssetId).Contains(asset.Id))
            .ToDictionaryAsync(asset => asset.Id, cancellationToken);

        int resolved = 0;
        foreach (PredictionRecord prediction in predictions)
        {
            if (!models.TryGetValue(prediction.ModelVersionId, out ModelVersion? model) ||
                !assets.TryGetValue(prediction.AssetId, out Asset? asset))
            {
                continue;
            }
            OutcomeSeries? series = model.AssetClass switch
            {
                AssetClasses.Crypto => await LoadCryptoSeriesAsync(prediction, cancellationToken),
                AssetClasses.UsEquity => await LoadEquitySeriesAsync(prediction, cancellationToken),
                _ => null
            };
            if (series is null)
            {
                continue;
            }

            double currentClose = series.Closes[0];
            double targetClose = series.Closes[^1];
            double realizedReturn = Math.Log(targetClose / currentClose);
            DirectionLabel realizedDirection = TargetLabeler.Label(
                currentClose,
                targetClose,
                prediction.NeutralBandThreshold!.Value);
            double realizedVolatility = OutcomeScoring.AnnualizedVolatility(
                series.Closes.Skip(1).ToArray(),
                model.AssetClass == AssetClasses.UsEquity ? 252 : 365);
            double modelBrier = OutcomeScoring.MulticlassBrier(
                prediction.DownProbability,
                prediction.NeutralProbability,
                prediction.UpProbability,
                realizedDirection);
            double baselineBrier = OutcomeScoring.MulticlassBrier(
                prediction.BaselineDownProbability!.Value,
                prediction.BaselineNeutralProbability!.Value,
                prediction.BaselineUpProbability!.Value,
                realizedDirection);
            dbContext.PredictionOutcomes.Add(new PredictionOutcome
            {
                PredictionId = prediction.Id,
                TargetTime = series.TargetTime,
                CurrentClose = currentClose,
                TargetClose = targetClose,
                RealizedReturn = realizedReturn,
                RealizedDirection = (int)realizedDirection,
                RealizedVolatility = realizedVolatility,
                DirectionBrierScore = modelBrier,
                BaselineBrierScore = baselineBrier,
                IntervalCovered = realizedReturn >= prediction.ReturnP10 && realizedReturn <= prediction.ReturnP90,
                QuantilePinballLoss = OutcomeScoring.MeanQuantilePinball(
                    realizedReturn,
                    prediction.ReturnP10,
                    prediction.ReturnP50,
                    prediction.ReturnP90),
                RiskAbsoluteError = Math.Abs(
                    prediction.RiskScore - OutcomeScoring.RiskTarget(realizedVolatility)),
                SourceDataSha256 = series.SourceDataSha256,
                ResolvedAt = now
            });
            resolved++;
        }

        await dbContext.SaveChangesAsync(cancellationToken);
        logger.LogInformation(
            "Resolved {ResolvedCount} of {CandidateCount} mature prediction outcomes.",
            resolved,
            predictions.Count);
    }

    private async Task<OutcomeSeries?> LoadCryptoSeriesAsync(
        PredictionRecord prediction,
        CancellationToken cancellationToken)
    {
        DateTimeOffset endExclusive = prediction.AnalysisTime.AddDays(prediction.HorizonDays);
        List<PriceBar> bars = await dbContext.PriceBars.AsNoTracking()
            .Where(bar => bar.AssetId == prediction.AssetId && bar.Interval == "1h" && bar.IsFinal &&
                          bar.OpenTime >= prediction.AnalysisTime.AddDays(-1) &&
                          bar.OpenTime < endExclusive)
            .OrderBy(bar => bar.OpenTime)
            .ToListAsync(cancellationToken);
        List<(DateTimeOffset Time, double Close)> daily = bars
            .GroupBy(bar => new DateTimeOffset(
                bar.OpenTime.Year,
                bar.OpenTime.Month,
                bar.OpenTime.Day,
                0,
                0,
                0,
                TimeSpan.Zero))
            .OrderBy(group => group.Key)
            .Select(group => (group.Key, Bars: group.OrderBy(bar => bar.OpenTime).ToArray()))
            .Where(value => IsCompleteUtcDay(value.Key, value.Bars))
            .Select(value => (value.Key.AddDays(1), (double)value.Bars[^1].Close))
            .ToList();
        if (daily.Count != prediction.HorizonDays + 1 ||
            daily[0].Time != prediction.AnalysisTime ||
            daily[^1].Time != prediction.AnalysisTime.AddDays(prediction.HorizonDays))
        {
            return null;
        }
        return new OutcomeSeries(
            daily.Select(value => value.Close).ToArray(),
            daily[^1].Time,
            HashBars(bars));
    }

    private async Task<OutcomeSeries?> LoadEquitySeriesAsync(
        PredictionRecord prediction,
        CancellationToken cancellationToken)
    {
        List<PriceBar> bars = await dbContext.PriceBars.AsNoTracking()
            .Where(bar => bar.AssetId == prediction.AssetId && bar.Interval == "1d" && bar.IsFinal &&
                          bar.Source == TwelveDataOptions.Source &&
                          bar.OpenTime >= prediction.AnalysisTime.AddDays(-1))
            .OrderBy(bar => bar.OpenTime)
            .Take(prediction.HorizonDays + 1)
            .ToListAsync(cancellationToken);
        if (bars.Count != prediction.HorizonDays + 1 || bars[0].OpenTime.AddDays(1) != prediction.AnalysisTime)
        {
            return null;
        }
        return new OutcomeSeries(
            bars.Select(bar => (double)bar.Close).ToArray(),
            bars[^1].OpenTime.AddDays(1),
            HashBars(bars));
    }

    private static bool IsCompleteUtcDay(DateTimeOffset day, IReadOnlyList<PriceBar> bars)
    {
        if (bars.Count != 24)
        {
            return false;
        }
        for (int hour = 0; hour < 24; hour++)
        {
            if (bars[hour].OpenTime != day.AddHours(hour) || bars[hour].CloseTime >= day.AddDays(1))
            {
                return false;
            }
        }
        return true;
    }

    private static string HashBars(IEnumerable<PriceBar> bars)
    {
        string identity = string.Join('|', bars.Select(bar => string.Join(':',
            bar.Id.ToString(CultureInfo.InvariantCulture),
            bar.OpenTime.ToString("O", CultureInfo.InvariantCulture),
            bar.Close.ToString(CultureInfo.InvariantCulture),
            bar.SourceChecksum ?? string.Empty)));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant();
    }

    private sealed record OutcomeSeries(
        IReadOnlyList<double> Closes,
        DateTimeOffset TargetTime,
        string SourceDataSha256);
}
