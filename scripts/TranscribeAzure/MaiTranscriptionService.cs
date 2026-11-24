using System.ClientModel;
using System.ClientModel.Primitives;
using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using Azure.AI.Speech.Transcription;

namespace TranscribeAzure;

public sealed class MaiTranscriptionService : IDisposable
{
    // Microsoft MAI guide: https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe
    // SDK 1.0.0 has no typed Model/ModelOptions. Use its public client pipeline
    // rather than silently falling back to the default enhanced model.
    public const string Definition = """
        {"locales":["nl"],"diarization":{"enabled":true},"enhancedMode":{"enabled":true,"model":"MAI-Transcribe-2","modelOptions":{"timestamps":"word","transcribeStyle":"verbatim"}}}
        """;
    readonly HttpClient http;
    readonly TranscriptionClient client;
    readonly Uri requestUri;

    public MaiTranscriptionService(Uri endpoint, string key, HttpMessageHandler? handler = null)
    {
        requestUri = new Uri(endpoint, "speechtotext/transcriptions:transcribe?api-version=2025-10-15");
        http = new HttpClient(handler ?? new SocketsHttpHandler
        {
            ConnectTimeout = TimeSpan.FromSeconds(60),
            AllowAutoRedirect = false
        }) { Timeout = Timeout.InfiniteTimeSpan };
        client = new TranscriptionClient(endpoint, new ApiKeyCredential(key), new TranscriptionClientOptions(
            TranscriptionClientOptions.ServiceVersion.V20251015)
        {
            Transport = new HttpClientPipelineTransport(http),
            NetworkTimeout = TimeSpan.FromHours(2),
            RetryPolicy = new ClientRetryPolicy(maxRetries: 0)
        });
    }

    public async Task<TranscriptionResult> TranscribeAsync(Stream audio, string filename, string mediaType,
        TimeSpan timeout, CancellationToken ct)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(timeout);
        try
        {
            for (int attempt = 0; ; attempt++)
            {
                audio.Position = 0;
                using var multipart = new MultipartFormDataContent();
                // Leave the input open so a single 429 retry can rewind and resend it.
                var file = new StreamContent(new NonOwningStream(audio));
                file.Headers.ContentType = new MediaTypeHeaderValue(mediaType);
                multipart.Add(file, "audio", filename);
                multipart.Add(new StringContent(Definition, Encoding.UTF8, "application/json"), "definition");
                using var body = new MultipartBody(multipart);
                try
                {
                    using var heartbeat = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token);
                    Task status = ReportWaitingAsync(heartbeat.Token);
                    try
                    {
                        using var message = client.Pipeline.CreateMessage();
                        message.Apply(new RequestOptions { CancellationToken = deadline.Token });
                        message.Request.Method = "POST";
                        message.Request.Uri = requestUri;
                        message.Request.Headers.Set("Content-Type", multipart.Headers.ContentType!.ToString());
                        message.Request.Content = body;
                        await client.Pipeline.SendAsync(message);
                        // Keep error response alive for diagnostics and Retry-After handling.
                        using var raw = message.ExtractResponse() ?? throw new IOException("Azure returned no HTTP response.");
                        if (raw.Status != 200) throw new ClientResultException(raw);
                        var result = ModelReaderWriter.Read<TranscriptionResult>(raw.Content)
                            ?? throw new InvalidDataException("Azure returned no transcription result.");
                        Console.WriteLine($"  Azure returned {result.Phrases.Count} phrases.");
                        return result;
                    }
                    finally { heartbeat.Cancel(); await status; }
                }
                catch (ClientResultException e) when (e.Status == 429 && attempt == 0)
                {
                    using var response = e.GetRawResponse();
                    TimeSpan delay = RetryDelay(response);
                    Console.WriteLine($"  Rate limited; retrying once after {delay.TotalSeconds:0} seconds.");
                    await Task.Delay(delay, deadline.Token);
                }
                catch (ClientResultException e)
                {
                    using var response = e.GetRawResponse();
                    string detail = response?.Content.ToString() ?? e.Message;
                    string hint = e.Status switch
                    {
                        401 or 403 => "Check the key, resource access and resource endpoint.",
                        404 => "Check that this is a Speech resource base endpoint.",
                        400 => "Check audio limits, request settings and MAI availability in the resource region.",
                        429 => "Still rate limited after one retry.",
                        _ => "Check Azure service health and resource region support."
                    };
                    string requestId = response is not null && response.Headers.TryGetValue("apim-request-id", out var id) ? $" Request ID: {id}." : "";
                    throw new IOException($"Azure HTTP {e.Status}. {hint}{requestId}\n{detail[..Math.Min(detail.Length, 2000)]}", e);
                }
            }
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        { throw new TimeoutException($"Azure request exceeded {timeout.TotalSeconds:0} seconds (including upload and any rate-limit wait)."); }
        catch (HttpRequestException e)
        { throw new IOException($"Could not reach Azure: {e.Message}", e); }
    }

    static TimeSpan RetryDelay(PipelineResponse? response)
    {
        if (response is not null && response.Headers.TryGetValue("Retry-After", out string? value))
        {
            if (int.TryParse(value, out int seconds)) return TimeSpan.FromSeconds(Math.Max(0, seconds));
            if (DateTimeOffset.TryParse(value, out var date)) return date > DateTimeOffset.UtcNow ? date - DateTimeOffset.UtcNow : TimeSpan.Zero;
        }
        return TimeSpan.FromSeconds(60);
    }

    static async Task ReportWaitingAsync(CancellationToken ct)
    {
        var watch = Stopwatch.StartNew();
        try
        {
            while (true)
            {
                await Task.Delay(TimeSpan.FromSeconds(15), ct);
                Console.WriteLine($"  Request in progress ({watch.Elapsed.TotalSeconds:0}s elapsed); Ctrl+C to cancel.");
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
    }

    public static MemoryStream SilentWav()
    {
        var stream = new MemoryStream();
        using (var writer = new BinaryWriter(stream, Encoding.ASCII, leaveOpen: true))
        {
            writer.Write("RIFF"u8); writer.Write(36 + 32000); writer.Write("WAVEfmt "u8);
            writer.Write(16); writer.Write((short)1); writer.Write((short)1); writer.Write(16000);
            writer.Write(32000); writer.Write((short)2); writer.Write((short)16);
            writer.Write("data"u8); writer.Write(32000); writer.Write(new byte[32000]);
        }
        stream.Position = 0;
        return stream;
    }

    public void Dispose() => http.Dispose();
}

// Let .NET encode multipart and stream it directly through the SDK pipeline.
// No hand-built MIME boundaries or whole-audio buffering.
sealed class MultipartBody(MultipartFormDataContent content) : BinaryContent
{
    public override bool TryComputeLength(out long length)
    {
        length = content.Headers.ContentLength ?? 0;
        return content.Headers.ContentLength.HasValue;
    }
    public override async Task WriteToAsync(Stream stream, CancellationToken cancellationToken)
    {
        Console.WriteLine($"  Uploading {content.Headers.ContentLength / 1_000_000.0:0.0} MB...");
        await content.CopyToAsync(stream, cancellationToken);
        Console.WriteLine("  Upload finished; waiting for Azure transcription...");
    }
    public override void WriteTo(Stream stream, CancellationToken cancellationToken) => WriteToAsync(stream, cancellationToken).GetAwaiter().GetResult();
    public override void Dispose() { }
}

sealed class NonOwningStream(Stream inner) : Stream
{
    public override bool CanRead => inner.CanRead;
    public override bool CanSeek => inner.CanSeek;
    public override bool CanWrite => false;
    public override long Length => inner.Length;
    public override long Position { get => inner.Position; set => inner.Position = value; }
    public override int Read(byte[] buffer, int offset, int count) => inner.Read(buffer, offset, count);
    public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken ct = default) => inner.ReadAsync(buffer, ct);
    public override long Seek(long offset, SeekOrigin origin) => inner.Seek(offset, origin);
    public override void Flush() => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
}
