using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using Azure.AI.Speech.Transcription;

namespace TranscribeAzure;

public sealed record Episode(string Key, int? Number, string Title, string Audio, double DurationSeconds, bool HasPaas, string[] Guests)
{
    public int ExpectedSpeakers => 1 + (HasPaas ? 1 : 0) + Guests.Length;
    public static Episode FromJson(JsonNode n)
    {
        int? number = n["n"]?.GetValue<int>();
        string key = number?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "x" + n["id"]!.GetValue<string>();
        if (key.Length == 0 || key.Any(c => !char.IsAsciiLetterOrDigit(c))) throw new InvalidDataException("Unsafe episode key.");
        return new(key, number, n["t"]?.GetValue<string>() ?? "", n["mp3"]?.GetValue<string>() ?? "",
            n["s"]?.GetValue<double>() ?? 0, n["p"]?.GetValue<bool>() ?? false,
            n["g"]?.AsArray().Select(g => g!.GetValue<string>()).ToArray() ?? []);
    }
}

public static class TranscriptConverter
{
    public static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    public static JsonObject Convert(TranscriptionResult result, Episode episode)
    {
        // Preserve the word-count heuristic and expected-cast cap, not an API speaker limit.
        var ranked = result.Phrases.Where(p => p.Speaker.HasValue).GroupBy(p => p.Speaker!.Value)
            .OrderByDescending(g => g.Sum(p => p.Words.Count == 0 ? 1 : p.Words.Count))
            .Take(episode.ExpectedSpeakers).Select(g => g.Key).ToArray();
        var mapping = new Dictionary<int, string>();
        var speakers = new JsonArray();
        for (int i = 0; i < ranked.Length; i++)
        {
            string id = $"S{i + 1}";
            int guestIndex = i - 1 - (episode.HasPaas ? 1 : 0);
            string name = i == 0 ? "David Boogerd" : i == 1 && episode.HasPaas ? "Stefan Paas" : episode.Guests[guestIndex];
            string role = i == 0 ? "Presentator" : i == 1 && episode.HasPaas ? "Vaste gast" : "Gast";
            mapping[ranked[i]] = id;
            speakers.Add(new JsonObject { ["id"] = id, ["name"] = name, ["role"] = role });
        }
        // Python assigns unranked/unknown clusters to S1. Ensure that reference exists.
        if (speakers.Count == 0 && result.Phrases.Count > 0)
            speakers.Add(new JsonObject { ["id"] = "S1", ["name"] = "Spreker onbekend", ["role"] = "Gast" });
        var segments = new JsonArray();
        var events = new JsonArray();
        string? previous = null;
        long previousEnd = 0;
        foreach (var phrase in result.Phrases)
        {
            string id = phrase.Speaker is { } speaker ? mapping.GetValueOrDefault(speaker, "S1") : "S1";
            long start = (long)phrase.Offset.TotalMilliseconds;
            long end = start + (long)phrase.Duration.TotalMilliseconds;
            if (previous is not null && previous != id && start - previousEnd < 300)
                events.Add(new JsonObject { ["t"] = Seconds(previousEnd), ["type"] = "overlap", ["speakers"] = new JsonArray(previous, id) });
            segments.Add(new JsonObject { ["start"] = Seconds(start), ["end"] = Seconds(end), ["speaker"] = id, ["text"] = phrase.Text });
            previous = id;
            previousEnd = end;
        }
        return new JsonObject
        {
            ["episode"] = episode.Number,
            ["source"] = new JsonObject { ["audio"] = episode.Audio, ["model"] = "azure/mai-transcribe-2", ["created"] = DateTime.Today.ToString("yyyy-MM-dd") },
            ["speakers"] = speakers, ["segments"] = segments, ["events"] = events,
            ["summary"] = new JsonObject { ["tldr"] = "", ["points"] = new JsonArray() },
            ["chapters"] = new JsonArray(), ["highlights"] = new JsonArray(), ["mentions"] = new JsonArray(), ["bible"] = new JsonArray()
        };
    }

    static double Seconds(long milliseconds) => Math.Round(milliseconds / 1000.0, 3);
}
