using System.ClientModel.Primitives;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using Azure.AI.Speech.Transcription;
using TranscribeAzure;

const string Fixture = """
    {"durationMilliseconds":4000,"combinedPhrases":[{"text":"Hallo wereld."}],"phrases":[
      {"speaker":8,"offsetMilliseconds":0,"durationMilliseconds":1000,"text":"David spreekt meer woorden.","words":[{},{},{},{}],"confidence":0},
      {"speaker":3,"offsetMilliseconds":1100,"durationMilliseconds":1000,"text":"Stefan spreekt woorden.","words":[{},{},{}],"confidence":0},
      {"speaker":7,"offsetMilliseconds":2500,"durationMilliseconds":1000,"text":"Gast spreekt.","words":[{},{}],"confidence":0},
      {"speaker":99,"offsetMilliseconds":3600,"durationMilliseconds":100,"text":"Intro","words":[{}],"confidence":0}]}
    """;

int checks = 0;
void Check(bool condition, string message)
{
    if (!condition) throw new Exception("FAILED: " + message);
    checks++;
}

var result = ModelReaderWriter.Read<TranscriptionResult>(BinaryData.FromString(Fixture))!;
var episode = new Episode("42", 42, "Test", "https://example.com/42.mp3", 4000, true, ["Gast A"]);
var transcript = TranscriptConverter.Convert(result, episode);
Check(transcript["speakers"]!.AsArray().Count == 3, "cast cap");
Check((string?)transcript["speakers"]![0]!["name"] == "David Boogerd", "host rank");
Check((string?)transcript["speakers"]![1]!["name"] == "Stefan Paas", "Paas rank");
Check((string?)transcript["speakers"]![2]!["name"] == "Gast A", "guest rank");
Check((string?)transcript["segments"]![3]!["speaker"] == "S1", "excess speaker fallback");
Check((double?)transcript["segments"]![1]!["start"] == 1.1, "milliseconds to seconds");
Check(transcript["events"]!.AsArray().Count == 2, "speaker transition events");
Check((string?)transcript["source"]!["model"] == "azure/mai-transcribe-2", "schema provenance");
var withoutPaas = TranscriptConverter.Convert(result, episode with { HasPaas = false, Guests = ["A", "B"] });
Check((string?)withoutPaas["speakers"]![1]!["name"] == "A", "guest without Paas");
var missingSpeaker = ModelReaderWriter.Read<TranscriptionResult>(BinaryData.FromString("""
    {"durationMilliseconds":10,"combinedPhrases":[],"phrases":[{"offsetMilliseconds":0,"durationMilliseconds":10,"text":"x","confidence":0}]}
    """))!;
Check(TranscriptConverter.Convert(missingSpeaker, episode)["speakers"]!.AsArray().Count == 1, "valid reference without diarization labels");
Check(Episode.FromJson(JsonNode.Parse("""{"n":null,"id":"5005"}""")!).Key == "x5005", "unnumbered episode key");
Check(CommandLine.Parse(["--episode", "42", "--delete-mp3", "--identify"]).Identify, "CLI parity");
try { CommandLine.Parse(["--episode", "42", "--all-missing"]); throw new Exception("Expected CLI rejection"); }
catch (ArgumentException) { checks++; }
string credentialRoot = Path.Combine(Path.GetTempPath(), "mai-credentials-" + Guid.NewGuid().ToString("N"));
string? previousKey = Environment.GetEnvironmentVariable("AZURE_SPEECH_KEY");
string? previousEndpoint = Environment.GetEnvironmentVariable("AZURE_SPEECH_ENDPOINT");
Directory.CreateDirectory(credentialRoot);
try
{
    Environment.SetEnvironmentVariable("AZURE_SPEECH_KEY", null);
    Environment.SetEnvironmentVariable("AZURE_SPEECH_ENDPOINT", null);
    File.WriteAllText(Path.Combine(credentialRoot, ".env"), "AZURE_SPEECH_KEY='file-key'\nAZURE_SPEECH_ENDPOINT=https://file.example/\n");
    var cli = CommandLine.Parse(["--probe"]);
    Check(CommandLine.Credentials(credentialRoot, cli).Key == "file-key", "dotenv fallback");
    Environment.SetEnvironmentVariable("AZURE_SPEECH_KEY", "environment-key");
    Environment.SetEnvironmentVariable("AZURE_SPEECH_ENDPOINT", "https://environment.example/");
    Check(CommandLine.Credentials(credentialRoot, cli).Key == "environment-key", "environment precedence");
    Check(CommandLine.Credentials(credentialRoot, cli with { Key = "cli-key" }).Key == "cli-key", "CLI credential precedence");
    Check(CommandLine.Credentials(credentialRoot, cli with { Endpoint = "https://cli.example/" }).Endpoint.Host == "cli.example", "CLI endpoint precedence");
    try { CommandLine.Credentials(credentialRoot, cli with { Endpoint = "https://example.com/speechtotext?api-version=x" }); throw new Exception("Expected endpoint rejection"); }
    catch (ArgumentException) { checks++; }
}
finally
{
    Environment.SetEnvironmentVariable("AZURE_SPEECH_KEY", previousKey);
    Environment.SetEnvironmentVariable("AZURE_SPEECH_ENDPOINT", previousEndpoint);
    File.Delete(Path.Combine(credentialRoot, ".env"));
    Directory.Delete(credentialRoot);
}
using (var wav = MaiTranscriptionService.SilentWav())
{
    using var reader = new BinaryReader(wav);
    Check(Encoding.ASCII.GetString(reader.ReadBytes(4)) == "RIFF", "probe WAV magic");
    Check(reader.ReadInt32() == wav.Length - 8, "probe WAV length");
}

var handler = new StubHandler(async (request, index, ct) =>
{
    Check(request.Method == HttpMethod.Post, "POST");
    Check(request.RequestUri!.AbsolutePath == "/speechtotext/transcriptions:transcribe", "SDK path");
    Check(request.RequestUri.Query == "?api-version=2025-10-15", "API version");
    Check(request.Headers.GetValues("Ocp-Apim-Subscription-Key").Single() == "test-key", "SDK authentication");
    byte[] body = await request.Content!.ReadAsByteArrayAsync(ct);
    Check(request.Content.Headers.ContentLength == body.Length, "content length matches encoded multipart");
    string mime = Encoding.UTF8.GetString(body);
    Check(mime.Contains("probe.wav") && mime.Contains("RIFF"), "audio part");
    Check(mime.Contains(MaiTranscriptionService.Definition), "exact MAI definition survives SDK pipeline");
    var definition = JsonNode.Parse(MaiTranscriptionService.Definition)!;
    Check((string?)definition["locales"]![0] == "nl", "Dutch");
    Check((string?)definition["enhancedMode"]!["model"] == "MAI-Transcribe-2", "MAI model");
    Check((string?)definition["enhancedMode"]!["modelOptions"]!["timestamps"] == "word", "word timing");
    Check((string?)definition["enhancedMode"]!["modelOptions"]!["transcribeStyle"] == "verbatim", "verbatim");
    Check((bool?)definition["diarization"]!["enabled"] == true, "diarization enabled");
    Check(definition["diarization"]!["maxSpeakers"] is null, "no new API speaker constraint");
    var response = Reply(index == 0 ? 429 : 200, index == 0 ? "{\"error\":\"limited\"}" : Fixture);
    response.Headers.TryAddWithoutValidation("Retry-After", "0");
    return response;
});
using (var service = new MaiTranscriptionService(new Uri("https://test.cognitiveservices.azure.com/"), "test-key", handler))
using (var wav = MaiTranscriptionService.SilentWav())
{
    var received = await service.TranscribeAsync(wav, "probe.wav", "audio/wav", TimeSpan.FromSeconds(5), default);
    Check(received.Phrases.Count == 4 && handler.Count == 2, "429 retries once with a complete request");
    Check(wav.CanRead, "caller retains input ownership");
}

foreach (int status in new[] { 400, 401, 404, 429, 503 })
{
    var errors = new StubHandler((_, _, _) =>
    {
        var response = Reply(status, "{\"error\":{\"message\":\"specific-error\"}}");
        response.Headers.TryAddWithoutValidation("Retry-After", "0");
        response.Headers.TryAddWithoutValidation("apim-request-id", "test-id");
        return Task.FromResult(response);
    });
    using var service = new MaiTranscriptionService(new Uri("https://test.cognitiveservices.azure.com/"), "key", errors);
    using var wav = MaiTranscriptionService.SilentWav();
    try { await service.TranscribeAsync(wav, "probe.wav", "audio/wav", TimeSpan.FromSeconds(5), default); throw new Exception("Expected error"); }
    catch (IOException e)
    {
        Check(e.Message.Contains($"HTTP {status}") && e.Message.Contains("specific-error") && e.Message.Contains("test-id"), $"HTTP {status} diagnostics");
        Check(errors.Count == (status == 429 ? 2 : 1), $"HTTP {status} retry count");
    }
}

var slow = new StubHandler(async (_, _, ct) => { await Task.Delay(10000, ct); return Reply(200, Fixture); });
using (var service = new MaiTranscriptionService(new Uri("https://test.cognitiveservices.azure.com/"), "key", slow))
using (var wav = MaiTranscriptionService.SilentWav())
{
    try { await service.TranscribeAsync(wav, "probe.wav", "audio/wav", TimeSpan.FromMilliseconds(50), default); throw new Exception("Expected timeout"); }
    catch (TimeoutException) { checks++; }
}
var cancelled = new StubHandler(async (_, _, ct) => { await Task.Delay(10000, ct); return Reply(200, Fixture); });
using (var service = new MaiTranscriptionService(new Uri("https://test.cognitiveservices.azure.com/"), "key", cancelled))
using (var wav = MaiTranscriptionService.SilentWav())
using (var cancel = new CancellationTokenSource(TimeSpan.FromMilliseconds(50)))
{
    try { await service.TranscribeAsync(wav, "probe.wav", "audio/wav", TimeSpan.FromSeconds(5), cancel.Token); throw new Exception("Expected cancellation"); }
    catch (OperationCanceledException) { checks++; }
}
Console.WriteLine($"Passed {checks} checks.");

static HttpResponseMessage Reply(int code, string json) => new((HttpStatusCode)code) { Content = new StringContent(json, Encoding.UTF8, "application/json") };

sealed class StubHandler(Func<HttpRequestMessage, int, CancellationToken, Task<HttpResponseMessage>> respond) : HttpMessageHandler
{
    public int Count { get; private set; }
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) => respond(request, Count++, ct);
}
