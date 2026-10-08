# ARM CPU baseline — 2026-10-08

## Conditions

Raspberry Pi 4 Model B revision 1.4, ARM64, 8 GB RAM, four CPU cores,
reported maximum frequency 2 GHz, SD-backed filesystem. Existing workloads were
left running. These measurements describe this host/configuration, not all Pi 4s.

whisper.cpp release `v1.9.5`, commit
`d1be6fde11ac6e0407606b4e42fe72d34add8037`; GCC 14.2, Release build,
`GGML_OPENMP=OFF`, CPU-only. Commands ran at nice level 10; there were no concurrent
transcription jobs. The initial two-thread run may have overlapped final build
tasks; results are individual observations, not repeated controlled benchmarks.

## Observations

| Input | Model | Threads | Inference | Real-time factor | Child peak RSS |
| --- | --- | ---: | ---: | ---: | ---: |
| Bundled clean English sample, 11.0 s | multilingual base | 2 | 24.19 s | 2.20 | 282 MiB |
| Same sample | multilingual base | 4 | 13.77 s | 1.25 | 284 MiB |
| Same sample | multilingual small, Q5_0 | 2 | 53.09 s | 4.83 | 446 MiB |
| Synthetic English speech, 58.78 s | multilingual base | 2 | 96.68 s | 1.64 | 353 MiB |

Preparation took approximately 0.26–0.36 seconds per run. Recorded start/end
temperatures ranged from 43.3–53.1 °C. Separate firmware checks reported no
throttling flags (`0x0`). These are snapshots, not continuous thermal profiling.
Child peak RSS includes process-lifetime child high-water marks, potentially
preprocessing as well as inference; it is not total service memory consumption.

For the synthetic sample, the known reference yielded WER 0.014 under the harness's
case-folded, punctuation-stripped word normalization. This reflects only one
synthetic English fixture. It is **not** a meeting accuracy estimate. No reference
was supplied for the bundled sample. Recordings and generated transcripts are not
included in this repository.

## Provisional decision and remaining gates

Proceed with a single-worker asynchronous service and multilingual base as the
initial development candidate, using two recognition threads to preserve CPU
headroom. Four threads improved this short sample but consume the whole CPU;
expose an operator setting rather than use them silently. Keep quantized small as
an optional candidate, not the default based on these latency measurements.

Memory headroom is sufficient for these tested candidates; sustained throughput,
full pipeline overhead, Hindi/English quality, noisy audio, enhancement effects
and long meetings still need evaluation. Do not extrapolate a guaranteed ETA from
these samples. Validate realistic recordings with permission before enabling
Mamyda integration or choosing a production default. SSD-backed temporary storage
and admission/retention limits remain production requirements.

## Weight integrity

Downloaded models from the upstream whisper.cpp model downloader; hashes describe
the actual files used rather than claiming independent supplier verification.

```text
ggml-base.bin
60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe

ggml-small-q5_0.bin (locally quantized from multilingual small)
d952ad748a45d78449a6190970d43030f161f3515e220e06fc1dc6c1ee6607d2
```
