using Probora.Domain.Markets;
using Probora.ML.Runtime.Features;

namespace Probora.Worker.Models;

public static class DerivativeHistoryReadiness
{
    public static bool TryCreate(
        IReadOnlyCollection<DerivativeDailySnapshot> snapshots,
        DateTimeOffset cutoff,
        DateTimeOffset inferenceTime,
        int requiredDays,
        out DerivativeObservation[] observations,
        out string reason)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(requiredDays, 1);
        DerivativeDailySnapshot[] ordered = snapshots
            .Where(x => x.IsComplete && x.SnapshotTime <= cutoff)
            .OrderBy(x => x.SnapshotTime)
            .TakeLast(requiredDays)
            .ToArray();
        if (ordered.Length != requiredDays)
        {
            observations = [];
            reason = $"Only {ordered.Length}/{requiredDays} complete derivative days are available.";
            return false;
        }

        for (int index = 0; index < ordered.Length; index++)
        {
            DateTimeOffset expected = cutoff.AddDays(index - requiredDays + 1);
            DerivativeDailySnapshot snapshot = ordered[index];
            if (snapshot.SnapshotTime != expected)
            {
                observations = [];
                reason = $"Derivative history has a gap at {expected:O}.";
                return false;
            }
            if (snapshot.AvailableAt > inferenceTime || snapshot.SourceMaxEventTime >= snapshot.SnapshotTime)
            {
                observations = [];
                reason = $"Derivative day {snapshot.SnapshotTime:O} violates the as-of availability boundary.";
                return false;
            }
        }

        observations = ordered.Select(x => new DerivativeObservation(
            x.SnapshotTime,
            x.FundingRate,
            x.Premium,
            x.FuturesQuoteVolume,
            x.FuturesTakerBuyRatio,
            x.OpenInterestValue,
            x.LongShortRatio,
            x.TakerLongShortRatio)).ToArray();
        reason = string.Empty;
        return true;
    }
}
