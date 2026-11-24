namespace TranscribeAzure;

public sealed record CommandLine(string? Episode, bool AllMissing, bool Probe, string? Key,
    string? Endpoint, bool DeleteMp3, bool Identify, bool Help)
{
    public const string Usage = """
        Transcribe episodes with Azure MAI-Transcribe-2 (.NET 10).
        dotnet run --project scripts/TranscribeAzure -- --episode N [--delete-mp3] [--identify]
        dotnet run --project scripts/TranscribeAzure -- --all-missing [--delete-mp3] [--identify]
        dotnet run --project scripts/TranscribeAzure -- --probe
        Optional: --key KEY --endpoint https://RESOURCE.cognitiveservices.azure.com/
        Credentials: CLI > AZURE_SPEECH_KEY / AZURE_SPEECH_ENDPOINT environment > repository .env.
        --identify runs the existing Python voice-profile helper; transcription itself is .NET.
        """;

    public static CommandLine Parse(string[] args)
    {
        string? episode = null, key = null, endpoint = null;
        bool all = false, probe = false, delete = false, identify = false, help = false;
        for (int i = 0; i < args.Length; i++)
        {
            string Value() => i + 1 < args.Length && !args[i + 1].StartsWith("--")
                ? args[++i] : throw new ArgumentException($"Missing value for {args[i]}.");
            switch (args[i])
            {
                case "--episode": episode = Value(); break;
                case "--key": key = Value(); break;
                case "--endpoint": endpoint = Value(); break;
                case "--all-missing": all = true; break;
                case "--probe": probe = true; break;
                case "--delete-mp3": delete = true; break;
                case "--identify": identify = true; break;
                case "--help" or "-h": help = true; break;
                default: throw new ArgumentException($"Unknown argument: {args[i]}\n{Usage}");
            }
        }
        if (!help && (episode is null ? 0 : 1) + (all ? 1 : 0) + (probe ? 1 : 0) != 1)
            throw new ArgumentException($"Choose exactly one of --episode, --all-missing, or --probe.\n{Usage}");
        return new(episode, all, probe, key, endpoint, delete, identify, help);
    }

    public static (string Key, Uri Endpoint) Credentials(string root, CommandLine cli)
    {
        var dotenv = new Dictionary<string, string>();
        string file = Path.Combine(root, ".env");
        if (File.Exists(file))
            foreach (string line in File.ReadLines(file))
            {
                if (line.TrimStart().StartsWith('#')) continue;
                int split = line.IndexOf('=');
                if (split > 0) dotenv.TryAdd(line[..split].Trim(), line[(split + 1)..].Trim().Trim('"', '\''));
            }
        string? Resolve(string? explicitValue, string name) =>
            new[] { explicitValue, Environment.GetEnvironmentVariable(name), dotenv.GetValueOrDefault(name) }
                .FirstOrDefault(v => !string.IsNullOrWhiteSpace(v));
        string key = Resolve(cli.Key, "AZURE_SPEECH_KEY") ?? throw new ArgumentException("Set AZURE_SPEECH_KEY or pass --key.");
        string endpoint = Resolve(cli.Endpoint, "AZURE_SPEECH_ENDPOINT") ?? throw new ArgumentException("Set AZURE_SPEECH_ENDPOINT or pass --endpoint.");
        if (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) || uri.Scheme != "https" ||
            uri.AbsolutePath != "/" || uri.Query.Length != 0 || uri.Fragment.Length != 0 || uri.UserInfo.Length != 0)
            throw new ArgumentException("Endpoint must be an HTTPS resource base URL, without an API path, query or credentials.");
        return (key, uri);
    }
}
