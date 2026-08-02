using System.Text.Json;
using Probora.ML.Runtime.Inference;

namespace Probora.UnitTests;

public sealed class ArtifactRuntimeParityTests
{
    [Fact]
    public void GeneratedArtifacts_MatchPythonOnnxAndDotNet_WhenArtifactRootIsProvided()
    {
        string? root = Environment.GetEnvironmentVariable("PROBORA_PARITY_ARTIFACT_ROOT");
        if (string.IsNullOrWhiteSpace(root))
        {
            return;
        }

        string[] fixtures = Directory.EnumerateFiles(root, "runtime_parity.json", SearchOption.AllDirectories)
            .OrderBy(path => path, StringComparer.Ordinal)
            .ToArray();
        Assert.NotEmpty(fixtures);
        foreach (string fixture in fixtures)
        {
            string directory = Path.GetDirectoryName(fixture)!;
            ModelManifest manifest = JsonSerializer.Deserialize<ModelManifest>(
                File.ReadAllText(Path.Combine(directory, "manifest.json")),
                new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
            Assert.Equal("v1", manifest.RuntimeParityContractVersion);
            using OnnxModelBundle bundle = OnnxModelBundle.Load(directory);
            bundle.VerifyRuntimeParity(fixture);
        }
    }
}
