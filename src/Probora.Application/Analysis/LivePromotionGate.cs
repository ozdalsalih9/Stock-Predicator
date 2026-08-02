namespace Probora.Application.Analysis;

public sealed record LivePromotionEvidence(
    int OutcomeCount,
    int EvaluationDays,
    int DownCount,
    int NeutralCount,
    int UpCount,
    double? BrierSkillScore,
    double? ExpectedCalibrationError,
    double? IntervalCoverage);

public sealed record LivePromotionVerdict(string State, IReadOnlyList<string> Blockers);

public static class LivePromotionGate
{
    public const int RequiredOutcomes = 100;
    public const int RequiredEvaluationDays = 20;
    public const int RequiredOutcomesPerClass = 10;

    public static LivePromotionVerdict Evaluate(LivePromotionEvidence evidence)
    {
        List<string> blockers = [];
        if (evidence.OutcomeCount < RequiredOutcomes)
        {
            blockers.Add($"En az {RequiredOutcomes} sonuçlanmış tahmin gerekli.");
        }
        if (evidence.EvaluationDays < RequiredEvaluationDays)
        {
            blockers.Add($"En az {RequiredEvaluationDays} farklı değerlendirme günü gerekli.");
        }
        if (Math.Min(evidence.DownCount, Math.Min(evidence.NeutralCount, evidence.UpCount)) < RequiredOutcomesPerClass)
        {
            blockers.Add($"Her yön sınıfında en az {RequiredOutcomesPerClass} gözlem gerekli.");
        }
        if (evidence.BrierSkillScore is null || evidence.BrierSkillScore < 0.05)
        {
            blockers.Add("Canlı Brier becerisi seçilmiş baseline'dan en az %5 iyi olmalı.");
        }
        if (evidence.ExpectedCalibrationError is null || evidence.ExpectedCalibrationError > 0.05)
        {
            blockers.Add("Canlı ECE en fazla 0,05 olmalı.");
        }
        if (evidence.IntervalCoverage is null || evidence.IntervalCoverage is < 0.75 or > 0.90)
        {
            blockers.Add("P10-P90 kapsaması %75-%90 aralığında olmalı.");
        }
        return new LivePromotionVerdict(
            blockers.Count == 0 ? "eligible_for_manual_review" : "collecting_evidence",
            blockers);
    }
}
