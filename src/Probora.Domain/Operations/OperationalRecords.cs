namespace Probora.Domain.Operations;

public sealed class IngestionRun
{
    public Guid Id { get; set; }
    public string Source { get; set; } = string.Empty;
    public string Dataset { get; set; } = string.Empty;
    public DateTimeOffset StartedAt { get; set; }
    public DateTimeOffset? CompletedAt { get; set; }
    public string Status { get; set; } = "running";
    public long RecordsRead { get; set; }
    public long RecordsWritten { get; set; }
    public string? Error { get; set; }
}

public sealed class DataQualityIssue
{
    public long Id { get; set; }
    public Guid? AssetId { get; set; }
    public string Code { get; set; } = string.Empty;
    public string Severity { get; set; } = "warning";
    public string Description { get; set; } = string.Empty;
    public DateTimeOffset? DataTime { get; set; }
    public DateTimeOffset DetectedAt { get; set; }
    public bool IsResolved { get; set; }
}
