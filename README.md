# mamyda-stt

Reusable, self-hosted speech-to-text API for Mamyda and other applications.

**Status:** early implementation. An authenticated discovery API, durable queue
core and CPU benchmark CLI are implemented. Upload/transcription HTTP routes and
the processing worker are not enabled yet; this is not a production STT service.

## Planned capabilities

- Resumable audio/video uploads with progress and asynchronous processing.
- Audio extraction, optional measured enhancement, voice activity detection,
  and timestamp-preserving segmentation.
- CPU Whisper inference and pluggable local or remote audio-capable providers.
- Fail-fast model capability checks and a short sample test before full jobs.
- Raw transcripts plus optional conservative LLM review, with explicit warnings.
- Application-scoped authentication, quotas, cancellation, and automatic deletion.
- Versioned HTTP API and reusable Python/TypeScript clients.

## Hardware

Start with an ARM64 Raspberry Pi 4 with 8 GB RAM, one processing worker, and
preferably SSD-backed temporary storage. A 4 GB Pi can be evaluated for smaller
workloads but has less headroom. No GPU is required for whisper.cpp; transcription
latency must be measured on representative recordings before choosing a default.
Larger inference and neural enhancement can run on a separate provider host.

See [Architecture and implementation plan](docs/architecture.md) and
[development/benchmark instructions](docs/development.md).

## Build and test

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/pytest -q
.venv/bin/ruff check .
```

CI tests Python 3.11, 3.13 and 3.14. Model inference is benchmarked separately on
the target host; unit tests do not download weights or call paid providers.

## Development approach

Implement in small TDD increments: benchmark and API contract, secure job/upload
foundation, audio pipeline, provider adapters/review, then client integration.
Do not commit credentials, recordings, generated transcripts, or model weights.
Use consented or synthetic fixtures with documented redistribution rights.

## License

Copyright 2026 Incorpify LLC contributors. Project code and documentation are
licensed under [Apache License 2.0](LICENSE). External engines, dependencies,
and model weights retain their own licenses; review them before redistribution.
