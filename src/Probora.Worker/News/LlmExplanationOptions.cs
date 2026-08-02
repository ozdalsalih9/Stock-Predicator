namespace Probora.Worker.News;

public sealed class LlmExplanationOptions
{
    public const string SectionName = "LlmExplanations";
    public bool Enabled { get; set; }
    public string Provider { get; set; } = "openai";
    public string BaseUrl { get; set; } = "https://api.openai.com/v1/";
    public string ApiKey { get; set; } = string.Empty;
    public string Model { get; set; } = "gpt-5.6-luna";
    public string PromptVersion { get; set; } = "probora-explanation-v1";
    public int MaxPredictionsPerRun { get; set; } = 4;
    public int NewsLookbackHours { get; set; } = 72;
    public int MaxNewsArticles { get; set; } = 8;
    public int RetryFailedAfterHours { get; set; } = 6;
}
