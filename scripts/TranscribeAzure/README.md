# Azure MAI transcription with .NET

Targets the installed .NET 10 SDK (developed and built with 10.0.101). Uses
Microsoft's `Azure.AI.Speech.Transcription` 1.0.0 SDK and .NET networking/JSON
libraries. The existing Python transcriber and scheduled workflows are unchanged.

From the repository root:

```powershell
dotnet run --project scripts/TranscribeAzure -- --probe
dotnet run --project scripts/TranscribeAzure -- --episode 42 --delete-mp3
dotnet run --project scripts/TranscribeAzure -- --all-missing --delete-mp3 --identify
```

All original options are available: `--episode`, `--all-missing`, `--probe`,
`--key`, `--endpoint`, `--delete-mp3`, and `--identify`. Choose one operation.
An explicit episode overwrites that episode's transcript after success;
`--all-missing` skips existing transcript files. Failures produce a nonzero exit
code; processing continues to the next episode in a batch. Ctrl+C cancels.

Credentials use the same precedence as Python: command-line overrides, then
`AZURE_SPEECH_KEY` / `AZURE_SPEECH_ENDPOINT` environment variables, then the
repository `.env`. The endpoint must be the HTTPS resource base URL, such as
`https://RESOURCE.cognitiveservices.azure.com/`, without an API path or query.
Keys are never printed. The documentation's `AZURE_SPEECH_API_KEY` variable is
not used: the original project's `AZURE_SPEECH_KEY` name is preserved.

## Settings and output compatibility

The request uses API version `2025-10-15`, locale `nl`, diarization enabled,
enhanced mode enabled, model `MAI-Transcribe-2`, word timestamps, and verbatim
style. No translation, custom prompt, phrase list, channel separation or explicit
profanity setting is added. The exact request definition is in
`MaiTranscriptionService.Definition`.

The Python script does **not** send a fixed speaker count. It caps its name
mapping afterward at one host + Stefan Paas when `p` is true + the guests in `g`.
This version preserves that cap and the word-count ranking: David Boogerd,
Stefan Paas when present, then guests in feed order. Extra clusters fall back to
S1 as in Python. These names are heuristic guesses. The existing transition-gap
heuristic also produces `overlap` events; it is not acoustic overlap detection.

Output is the same `data/transcripts/{key}.json` schema with seconds, Dutch
speaker roles, source provenance and empty analysis containers. Unnumbered
episodes retain their `x{id}` keys and null episode numbers. Writes use a
temporary file and replace the destination only after successful serialization.
MP3s are cached in `data/mp3/`; incomplete downloads use `.part` files and are
discarded. Files must be nonempty and smaller than 250 MB; known episode duration
must be shorter than two hours. Azure remains authoritative about actual audio
duration and any tighter model/diarization limits.

`--identify` invokes the existing `scripts/identify_speakers.py --episode KEY
--apply` helper, preferring `.venv/Scripts/python.exe`. Only this optional voice
embedding stage requires Python and its existing voice dependencies. With no
profiles, it skips as before. If identification fails, the saved transcript and
MP3 remain. Manual correction files are not automatically applied, matching the
current Python `main` (its correction helper is not called there).

## Microsoft implementation references

- [MAI-Transcribe model configuration](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe)
- [Microsoft's C# quickstart and SDK setup](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/llm-speech?pivots=programming-language-csharp)
- [Azure SDK C# samples](https://github.com/Azure/azure-sdk-for-net/tree/main/sdk/transcription/Azure.AI.Speech.Transcription/samples)
- [Transcribe REST contract and limits](https://learn.microsoft.com/en-us/rest/api/speechtotext/transcriptions/transcribe?view=rest-speechtotext-2025-10-15)
- [System.ClientModel pipeline customization](https://learn.microsoft.com/en-us/dotnet/api/system.clientmodel.primitives.clientpipeline)

The quickstart's typed `EnhancedModeProperties` in SDK 1.0.0 exposes task, target
language and prompt, but lacks MAI's `model` and `modelOptions`. Its protocol
overload is internal. This implementation uses the SDK's public authenticated
`TranscriptionClient.Pipeline` with .NET `MultipartFormDataContent` and
`StreamContent` to carry the documented MAI definition, then reads the response
with the SDK's `ModelReaderWriter` into `TranscriptionResult`. It avoids reflection,
private SDK members, manually encoded multipart boundaries and whole-file buffers.

Connect timeout is 60 seconds; the complete transcription operation has a
two-hour deadline, including any retry. The probe deadline is 60 seconds.
Only HTTP 429 is retried, once, using `Retry-After` seconds or HTTP date (default
60 seconds). Each retry rewinds the input and creates new multipart content.
Other failures report HTTP status, Azure response details and request ID when
available. Upload completion and a 15-second heartbeat distinguish sending audio
from waiting for the synchronous transcription response.

The probe uses a correctly sized, one-second, mono 16 kHz PCM silent WAV and the
same definition as transcription. Only HTTP 200 counts as acceptance; a 400
does not establish model support. Silence does not verify transcription accuracy.
Region and account availability must still support MAI-Transcribe-2.

## Verification

```powershell
dotnet build scripts/TranscribeAzure --no-restore
dotnet run --project tests/TranscribeAzure.Tests
```

The dependency-free check executable uses a simulated HTTP transport through the
real Azure SDK pipeline. It verifies authentication, endpoint/API version,
multipart bytes and length, exact model/language/style/timing/diarization fields,
retry replay, status diagnostics, timeout, schema conversion, speaker ranking,
excess speakers, missing speaker labels, unnumbered keys and probe WAV validity.
