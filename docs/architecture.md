# Speech-to-text service architecture

Status: proposed; benchmark before installing a production service.

## Deployment boundary

Deploy independently of Mamyda. The service owns its authenticated API, persistent
queue, temporary media, preprocessing and provider adapters. Applications forward
streamed uploads and job requests; they do not perform heavy conversion.

Use an 8 GB Raspberry Pi 4 as the initial host rather than a 4 GB Pi already
running another workload. Both are CPU-only machines of the same generation:
more RAM does not imply faster recognition. Start with one worker, bounded
subprocesses and configurable CPU/memory/disk budgets. Prefer SSD storage.
Offload larger models and expensive neural enhancement to a suitable inference
host. Never claim real-time performance without measuring it.

## Pipeline and correctness

1. Authenticate, reserve disk, and validate actual format, duration, size and
   audio presence. Reject unsupported models before costly work.
2. Extract audio with FFmpeg. Use model-compatible PCM; preserve speaker channels
   when appropriate and retain original timestamps.
3. Offer standard and enhanced profiles. Compare enhancement against originals;
   denoising can damage speech and should not be assumed beneficial.
4. Segment with voice activity detection and padding. Apply provider-specific
   chunk limits and explicit overlap deduplication.
5. Transcribe with multilingual whisper.cpp initially; benchmark base and a
   quantized small candidate on consented clean/noisy/mixed-language fixtures.
6. Run structural checks and optional conservative LLM review. Preserve raw text,
   proposed edits, source segments and warnings separately.
7. Return timestamped text, stage timings, model provenance and review status.

Text-only review cannot prove agreement with audio. Use `checks_passed`,
`needs_review`, or `unverified`; protect names, numbers, dates and quotations.
An optional reviewer failure must not discard a successful raw transcript.

## API and durable jobs

Python orchestration with importable pipeline/provider interfaces and OpenAPI
documentation. SQLite WAL with transactional worker leases is sufficient for an
initial single-host queue. Version routes under `/v1`:

- `GET /models`: availability, capabilities, limits and readiness.
- `POST /tests`: bounded short sample test with transcript and timings.
- `POST /uploads`, `PUT /uploads/{id}/chunks/{index}`, and
  `POST /uploads/{id}/complete`: resumable, authenticated uploads.
- `POST /transcriptions`: return HTTP 202 and a job ID.
- `GET /transcriptions/{id}` and `/result`: progress and results.
- `DELETE /transcriptions/{id}`: cancellation and deletion.

Expose separate liveness/readiness endpoints. Use idempotency keys, persistent
stage state, explicit failures and restart recovery. Report actual stages and
completed segments; only offer ETA when measurements justify it.

## Security and data lifecycle

Use HTTPS and application-scoped credentials, tenant/user isolation and quotas.
Service credentials remain in client backends. Register provider endpoints under
operator control to prevent arbitrary internal network access. Generic chat
compatibility is not proof of speech capability: validate and run a real sample.
Never automatically fall back to paid providers or blindly retry billed requests.

Mamyda initially allows 300 MiB/four-hour recordings and a maximum 15-day review
window; other clients may request smaller limits or shorter retention. Keep media
in private local temporary storage, not the application's permanent object store.
Delete all originals, derivatives and sample artifacts on acceptance or expiry.
Expired results become inaccessible immediately; cleanup runs on startup and
periodically. Exclude recordings/transcripts from logs and media from backups.
The client is responsible for saving and encrypting accepted minutes.

## Delivery gates (TDD)

1. Benchmark CPU, peak RAM, temperature, real-time factor and quality on short
   and long multilingual recordings. Choose an engine and resource limits.
2. Test authentication, ownership, resumable uploads, inspection, durable jobs,
   cancellation, disk exhaustion, crash recovery and retention before foundation
   implementation.
3. Test extraction, timestamp preservation, segmentation, overlap handling and
   enhancement regressions before integrating local Whisper.
4. Test capability rejection, provider timeouts, billing-safe behavior and
   hallucination-sensitive review before adding remote adapters.
5. Add SDKs and a test-and-choose UI with sample playback, latency, warnings and
   explicit cost disclosure. Integrate Mamyda, drain its old worker, then validate
   reuse with a second application.

## References

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)
