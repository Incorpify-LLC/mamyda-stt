# Development and benchmark guide

## Foundation status

Implemented: authenticated model discovery, liveness, protected OpenAPI, a durable
SQLite queue core, and a reproducible CPU benchmark CLI. The HTTP upload/job and
worker pipelines are **not yet implemented**. Readiness deliberately returns 503;
installed model files alone do not prove transcription works.

## Local development

Requires Python 3.11+, FFmpeg/ffprobe for benchmarks, and a separately installed
whisper.cpp binary and multilingual model. Install in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Set `STT_API_KEYS` to a JSON mapping of cryptographically random secrets (at least
32 bytes each) to application identifiers. Generate secrets with
`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` and configure them
through your secret manager; never commit the values. Optional configuration:
`STT_DATA_DIR`, `STT_WHISPER_BINARY`, and `STT_WHISPER_MODEL`.

```sh
.venv/bin/uvicorn mamyda_stt.api:create_app --factory --host 127.0.0.1 --port 8095
```

Only `GET /health/live` is anonymous. Send `Authorization: Bearer <key>` for
`/v1/models`, `/health/ready`, `/openapi.json`, and `/docs`. Keep this development
server bound to loopback; a later production deployment needs authenticated HTTPS,
service supervision, quotas and resource limits. There is no public endpoint yet.

## Benchmark

Build whisper.cpp from a pinned revision; record its commit and model hash. For
the initial ARM64 check use release `v1.9.5` and multilingual `base`, then compare
quantized `small`. Build with two jobs to preserve host headroom. Configure
`GGML_OPENMP=OFF` if the host lacks the OpenMP toolchain. This can affect speed;
record it with the results. No root installation is required.

```sh
mamyda-stt-benchmark \
  --binary /path/to/whisper-cli --model /path/to/ggml-base.bin \
  --audio /path/to/private-recording.wav \
  --output benchmark-results/base-run-1 --threads 2 --language auto
```

Every run needs a new output directory. Results include duration, preparation and
inference time, real-time factor, child-process peak RSS, CPU time and temperature.
Run one benchmark per process: Linux child RSS is a lifetime high-water mark and
can include preprocessing. Real-time factor 2 means processing took twice the
recording duration. It is not a guaranteed long-recording ETA.

Audio is normalized to mono 16 kHz PCM for this baseline; multi-speaker channel
handling and optional enhancement remain pipeline work. Use `--reference` only
with known reference text; reported WER uses case-folded Unicode words with
punctuation removed, not a universal multilingual metric. Without a reference,
no accuracy number is produced. Inspect the private transcript and logs directly.

Use clean, noisy, Hindi/English and long recordings with permission. Test the same
clip and model repeatedly before choosing defaults. Do not publish recordings,
transcripts, internal host addresses or credentials. Public reports should contain
only sanitized hardware/configuration and aggregate results.

## Queue semantics

The queue binds jobs to application and subject, deduplicates matching requests,
permits one active lease, and makes expired jobs inaccessible. A missed lease
marks the job `failed/worker_interrupted`; it does not automatically replay work
that might already have incurred external charges. Callers explicitly submit a new
request after reviewing that failure. Cancellation removes stored results and
invalidates the lease. The future worker must terminate its subprocess and delete
all media derivatives; queue state alone is not filesystem cleanup.
