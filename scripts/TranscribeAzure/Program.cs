using System.Diagnostics;
using System.Text;
using System.Text.Json.Nodes;
using TranscribeAzure;

Console.OutputEncoding = Encoding.UTF8;
using var shutdown = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; shutdown.Cancel(); };
try { return await RunAsync(args, shutdown.Token); }
catch (OperationCanceledException)
{
    Console.Error.WriteLine(shutdown.IsCancellationRequested ? "Cancelled." : "Request timed out.");
    return 1;
}
catch (Exception e) { Console.Error.WriteLine($"Error: {e.Message}"); return 1; }

static async Task<int> RunAsync(string[] args, CancellationToken ct)
{
    var cli = CommandLine.Parse(args);
    if (cli.Help) { Console.WriteLine(CommandLine.Usage); return 0; }
    string root = FindRoot();
    var (key, endpoint) = CommandLine.Credentials(root, cli);
    using var service = new MaiTranscriptionService(endpoint, key);
    if (cli.Probe)
    {
        Console.WriteLine($"Probing {endpoint.Host} with a one-second silent WAV and production MAI settings...");
        using var audio = MaiTranscriptionService.SilentWav();
        await service.TranscribeAsync(audio, "probe.wav", "audio/wav", TimeSpan.FromSeconds(60), ct);
        Console.WriteLine("HTTP 200: endpoint accepted MAI-Transcribe-2, Dutch, verbatim, word timestamps and diarization.");
        Console.WriteLine("Silence validates request acceptance; it does not measure recognition quality.");
        return 0;
    }
    var master = JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(root, "data", "episodes.json"), ct))!;
    var episodes = master["eps"]!.AsArray().Select(n => Episode.FromJson(n!)).ToDictionary(e => e.Key);
    string outputDir = Path.Combine(root, "data", "transcripts");
    Directory.CreateDirectory(outputDir);
    var keys = cli.Episode is { } selected ? new[] { selected }
        : episodes.Keys.Where(k => !File.Exists(Path.Combine(outputDir, k + ".json"))).ToArray();
    if (cli.AllMissing) Console.WriteLine($"{keys.Length} episodes missing transcripts");
    int failures = 0;
    using var downloads = new HttpClient(new SocketsHttpHandler { ConnectTimeout = TimeSpan.FromSeconds(30) })
        { Timeout = TimeSpan.FromMinutes(10) };
    foreach (string episodeKey in keys)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            if (!episodes.TryGetValue(episodeKey, out var episode))
                throw new InvalidOperationException($"Episode {episodeKey} not found in episodes.json");
            Console.WriteLine($"Transcribing #{episode.Key} — {episode.Title}");
            Console.WriteLine($"  nl | MAI-Transcribe-2 | verbatim | word timestamps | diarization; expected cast: {episode.ExpectedSpeakers}");
            if (string.IsNullOrWhiteSpace(episode.Audio)) throw new InvalidOperationException("No MP3 URL for this episode.");
            if (episode.DurationSeconds >= 7200) throw new InvalidOperationException("Audio must be shorter than two hours.");
            string audioPath = Path.Combine(root, "data", "mp3", episode.Key + ".mp3");
            await DownloadAsync(downloads, episode.Audio, audioPath, ct);
            var audioInfo = new FileInfo(audioPath);
            if (audioInfo.Length is <= 0 or >= 250_000_000)
                throw new InvalidOperationException("Audio must be nonempty and smaller than 250 MB.");
            using var audio = File.OpenRead(audioPath);
            var result = await service.TranscribeAsync(audio, audioInfo.Name, "audio/mpeg", TimeSpan.FromHours(2), ct);
            var transcript = TranscriptConverter.Convert(result, episode);
            string output = Path.Combine(outputDir, episode.Key + ".json");
            string temporary = output + ".tmp";
            try
            {
                await File.WriteAllTextAsync(temporary, transcript.ToJsonString(TranscriptConverter.JsonOptions), new UTF8Encoding(false), ct);
                File.Move(temporary, output, overwrite: true);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
            Console.WriteLine($"  Saved data/transcripts/{episode.Key}.json ({result.Phrases.Count} segments)");
            if (cli.Identify) await IdentifyAsync(root, episode.Key, ct);
            audio.Dispose();
            if (cli.DeleteMp3) { File.Delete(audioPath); Console.WriteLine("  Deleted cached MP3."); }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
        catch (Exception e) { failures++; Console.Error.WriteLine($"  Episode {episodeKey} failed: {e.Message}"); }
    }
    return failures == 0 ? 0 : 1;
}

static string FindRoot()
{
    foreach (string start in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        for (var dir = new DirectoryInfo(start); dir is not null; dir = dir.Parent)
            if (File.Exists(Path.Combine(dir.FullName, "data", "episodes.json"))) return dir.FullName;
    throw new InvalidOperationException("Cannot find repository data/episodes.json from current directory or executable location.");
}

static async Task DownloadAsync(HttpClient client, string url, string path, CancellationToken ct)
{
    if (File.Exists(path)) { Console.WriteLine("  Using cached MP3."); return; }
    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
    string partial = path + ".part";
    try
    {
        Console.WriteLine("  Downloading MP3...");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromMinutes(10));
        using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength >= 250_000_000)
            throw new InvalidOperationException("Audio must be smaller than 250 MB.");
        await using (var dest = File.Create(partial))
        await using (var source = await response.Content.ReadAsStreamAsync(timeout.Token))
        {
            byte[] buffer = new byte[65536];
            long total = 0;
            int read;
            while ((read = await source.ReadAsync(buffer, timeout.Token)) != 0)
            {
                total += read;
                if (total >= 250_000_000) throw new InvalidOperationException("Audio must be smaller than 250 MB.");
                await dest.WriteAsync(buffer.AsMemory(0, read), timeout.Token);
            }
            if (total == 0 || (response.Content.Headers.ContentLength is { } expected && total != expected))
                throw new IOException("Incomplete or empty MP3 download.");
        }
        File.Move(partial, path);
    }
    finally { if (File.Exists(partial)) File.Delete(partial); }
}

static async Task IdentifyAsync(string root, string key, CancellationToken ct)
{
    string profiles = Path.Combine(root, "data", "voice-profiles");
    if (!Directory.Exists(profiles) || !Directory.EnumerateFiles(profiles, "*.npy").Any())
    { Console.WriteLine("  --identify: no voice profiles found; skipping."); return; }
    string localPython = Path.Combine(root, ".venv", "Scripts", "python.exe");
    var start = new ProcessStartInfo(File.Exists(localPython) ? localPython : "python") { WorkingDirectory = root, UseShellExecute = false };
    foreach (string arg in new[] { Path.Combine(root, "scripts", "identify_speakers.py"), "--episode", key, "--apply" })
        start.ArgumentList.Add(arg);
    Console.WriteLine("  Running existing Python voice-profile identification...");
    using var process = Process.Start(start) ?? throw new InvalidOperationException("Cannot start speaker identification.");
    try { await process.WaitForExitAsync(ct); }
    catch (OperationCanceledException) { if (!process.HasExited) process.Kill(entireProcessTree: true); throw; }
    if (process.ExitCode != 0) throw new InvalidOperationException($"Speaker identification failed (exit {process.ExitCode}); transcript and MP3 retained.");
}
