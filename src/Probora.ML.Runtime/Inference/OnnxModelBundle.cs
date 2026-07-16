using System.Text.Json;
using Microsoft.ML.OnnxRuntime;
using Probora.ML.Runtime.Features;

namespace Probora.ML.Runtime.Inference;

public sealed class OnnxModelBundle : IDisposable
{
    private readonly string _artifactDirectory;
    private readonly ModelManifest _manifest;
    private readonly IReadOnlyList<string> _featureNames;
    private readonly List<InferenceSession> _directionSessions;
    private readonly Dictionary<string, InferenceSession> _quantileSessions;
    private readonly InferenceSession _riskSession;

    private OnnxModelBundle(
        string artifactDirectory,
        ModelManifest manifest,
        IReadOnlyList<string> featureNames,
        List<InferenceSession> directionSessions,
        Dictionary<string, InferenceSession> quantileSessions,
        InferenceSession riskSession)
    {
        _artifactDirectory = artifactDirectory;
        _manifest = manifest;
        _featureNames = featureNames;
        _directionSessions = directionSessions;
        _quantileSessions = quantileSessions;
        _riskSession = riskSession;
    }

    public ModelManifest Manifest => _manifest;
    public IReadOnlyList<string> FeatureNames => _featureNames;

    public static OnnxModelBundle Load(string artifactDirectory)
    {
        string manifestPath = Path.Combine(artifactDirectory, "manifest.json");
        ModelManifest manifest = JsonSerializer.Deserialize<ModelManifest>(File.ReadAllText(manifestPath), new JsonSerializerOptions(JsonSerializerDefaults.Web))
            ?? throw new InvalidDataException("Invalid model manifest.");
        string schemaPath = Path.Combine(artifactDirectory, "feature_schema.json");
        FeatureSchemaDocument schema = JsonSerializer.Deserialize<FeatureSchemaDocument>(
            File.ReadAllText(schemaPath),
            new JsonSerializerOptions(JsonSerializerDefaults.Web))
            ?? throw new InvalidDataException("Invalid feature schema.");
        if (!string.Equals(manifest.FeatureSetVersion, schema.Version, StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Feature schema mismatch. Manifest has {manifest.FeatureSetVersion}, schema has {schema.Version}.");
        }
        if (schema.Features.Count == 0)
        {
            throw new InvalidDataException("Feature schema is empty.");
        }

        List<InferenceSession> direction = manifest.DirectionModels
            .Select(path => new InferenceSession(Path.Combine(artifactDirectory, path)))
            .ToList();
        Dictionary<string, InferenceSession> quantiles = manifest.QuantileModels
            .ToDictionary(pair => pair.Key, pair => new InferenceSession(Path.Combine(artifactDirectory, pair.Value)));
        InferenceSession risk = new(Path.Combine(artifactDirectory, manifest.RiskModel));
        return new OnnxModelBundle(artifactDirectory, manifest, schema.Features, direction, quantiles, risk);
    }

    public RuntimePrediction Predict(FeatureVector features)
    {
        float[] values = _featureNames.Select(name =>
        {
            if (!features.Values.TryGetValue(name, out double value))
            {
                throw new InvalidDataException($"Feature '{name}' is missing from the inference vector.");
            }
            return (float)value;
        }).ToArray();
        using OrtValue input = OrtValue.CreateTensorValueFromMemory<float>(values, [1, values.Length]);
        Dictionary<string, OrtValue> inputs = new()
        {
            [_manifest.InputName] = input
        };

        double[] probabilities = [0, 0, 0];
        foreach (InferenceSession session in _directionSessions)
        {
            string outputName = session.OutputNames.Contains(_manifest.OutputName, StringComparer.Ordinal)
                ? _manifest.OutputName
                : session.OutputNames.Last();
            using IDisposableReadOnlyCollection<OrtValue> results = session.Run(new RunOptions(), inputs, [outputName]);
            ReadOnlySpan<float> output = results[0].GetTensorDataAsSpan<float>();
            for (int index = 0; index < probabilities.Length; index++)
            {
                probabilities[index] += output[index] / _directionSessions.Count;
            }
        }

        probabilities = TemperatureScale(probabilities, _manifest.Temperature);
        if (_manifest.ClassPrior is { Count: 3 })
        {
            double weight = Math.Clamp(_manifest.ProbabilityBlendWeight, 0, 1);
            probabilities = probabilities.Select(
                (value, index) => weight * value + (1 - weight) * _manifest.ClassPrior[index])
                .ToArray();
        }
        double p10 = RunScalar(_quantileSessions["p10"], inputs);
        double p50 = RunScalar(_quantileSessions["p50"], inputs);
        double p90 = RunScalar(_quantileSessions["p90"], inputs);
        double[] orderedQuantiles = [p10, p50, p90];
        Array.Sort(orderedQuantiles);
        double conformalAdjustment = ConformalIntervalCalibration.ResolveAdjustment(
            _manifest, features.Values);
        orderedQuantiles[0] -= conformalAdjustment;
        orderedQuantiles[2] += conformalAdjustment;
        double risk = Math.Clamp(RunScalar(_riskSession, inputs), 0, 1);
        return new RuntimePrediction(probabilities[2], probabilities[1], probabilities[0], orderedQuantiles[0], orderedQuantiles[1], orderedQuantiles[2], risk);
    }

    private static double RunScalar(InferenceSession session, IReadOnlyDictionary<string, OrtValue> inputs)
    {
        using IDisposableReadOnlyCollection<OrtValue> results = session.Run(new RunOptions(), inputs, [session.OutputNames.First()]);
        return results[0].GetTensorDataAsSpan<float>()[0];
    }

    private static double[] TemperatureScale(double[] probabilities, double temperature)
    {
        double safeTemperature = Math.Max(temperature, 0.01);
        double[] logits = probabilities.Select(value => Math.Log(Math.Max(value, 1e-12)) / safeTemperature).ToArray();
        double max = logits.Max();
        double[] exponentials = logits.Select(value => Math.Exp(value - max)).ToArray();
        double total = exponentials.Sum();
        return exponentials.Select(value => value / total).ToArray();
    }

    public void Dispose()
    {
        foreach (InferenceSession session in _directionSessions)
        {
            session.Dispose();
        }
        foreach (InferenceSession session in _quantileSessions.Values)
        {
            session.Dispose();
        }
        _riskSession.Dispose();
        GC.SuppressFinalize(this);
    }
}

internal sealed record FeatureSchemaDocument(string Version, IReadOnlyList<string> Features);
