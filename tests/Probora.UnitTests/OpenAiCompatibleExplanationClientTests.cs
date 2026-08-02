using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;
using Probora.Worker.News;

namespace Probora.UnitTests;

public sealed class OpenAiCompatibleExplanationClientTests
{
    [Fact]
    public async Task ExplainAsync_FiltersHallucinatedSourceUrlsAndSendsBearerToken()
    {
        string output = JsonSerializer.Serialize(new
        {
            summary = "Model yatay olasılığa yakın bir dağılım üretiyor.",
            supportingFactors = new[] { "Momentum" },
            riskFactors = new[] { "Volatilite" },
            contradictions = Array.Empty<string>(),
            uncertaintyNotes = new[] { "Olasılıklar birbirine yakın." },
            newsAssessment = new object[]
            {
                new { sourceUrl = "https://allowed.example/news", impact = "supporting", rationale = "İzinli kaynak." },
                new { sourceUrl = "https://invented.example/news", impact = "opposing", rationale = "Uydurma kaynak." }
            },
            disclaimer = "Yatırım tavsiyesi değildir."
        });
        string envelope = JsonSerializer.Serialize(new
        {
            choices = new[] { new { message = new { content = output } } }
        });
        RecordingHandler handler = new(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(envelope, Encoding.UTF8, "application/json")
        });
        HttpClient httpClient = new(handler) { BaseAddress = new Uri("https://api.example/v1/") };
        OpenAiCompatibleExplanationClient client = new(
            httpClient,
            Options.Create(new LlmExplanationOptions { ApiKey = "test-secret", Model = "test-model" }));

        PredictionExplanationOutput result = await client.ExplainAsync(
            "{}",
            new HashSet<string> { "https://allowed.example/news" },
            CancellationToken.None);

        PredictionNewsAssessment assessment = Assert.Single(result.NewsAssessment);
        Assert.Equal("https://allowed.example/news", assessment.SourceUrl);
        Assert.Equal("Bearer test-secret", handler.Authorization);
        Assert.Equal("https://api.example/v1/chat/completions", handler.RequestUri?.AbsoluteUri);
        Assert.DoesNotContain("test-secret", handler.Body);
    }

    private sealed class RecordingHandler(HttpResponseMessage response) : HttpMessageHandler
    {
        public Uri? RequestUri { get; private set; }
        public string? Authorization { get; private set; }
        public string Body { get; private set; } = string.Empty;

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            RequestUri = request.RequestUri;
            Authorization = request.Headers.Authorization?.ToString();
            Body = request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken);
            return response;
        }
    }
}
