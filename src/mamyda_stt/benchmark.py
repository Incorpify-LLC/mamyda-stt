"""One-shot CPU benchmark; audio and transcript stay in the supplied output directory."""

import argparse
import json
import platform
import re
import resource
import subprocess
import tempfile
import time
from pathlib import Path


def real_time_factor(elapsed_seconds: float, audio_seconds: float) -> float:
    if audio_seconds <= 0 or elapsed_seconds < 0:
        raise ValueError("Positive audio duration and nonnegative elapsed time required")
    return elapsed_seconds / audio_seconds


def word_error_rate(reference: str, hypothesis: str) -> float:
    # Unicode words; normalization is explicit, not a universal multilingual quality measure.
    expected = re.findall(r"\w+", reference.casefold())
    actual = re.findall(r"\w+", hypothesis.casefold())
    if not expected:
        raise ValueError("A nonempty reference is required")
    previous = list(range(len(actual) + 1))
    for i, word in enumerate(expected, 1):
        current = [i]
        for j, candidate in enumerate(actual, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (word != candidate))
            )
        previous = current
    return previous[-1] / len(expected)


def _temperature():
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return None


def run_benchmark(
    *,
    binary: Path,
    model: Path,
    audio: Path,
    output: Path,
    threads: int = 2,
    timeout: int = 1800,
    language: str = "auto",
    reference: Path | None = None,
):
    if not 1 <= threads <= 4 or timeout <= 0:
        raise ValueError("Use 1–4 threads and a positive timeout")
    for path in (binary, model, audio):
        if not path.is_file():
            raise ValueError(f"Required file missing: {path.name}")
    if output.exists():
        raise ValueError("Output directory already exists; use a new directory for each run")
    output.mkdir(parents=True, mode=0o700)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if not 0 < duration <= 4 * 3600:
        raise ValueError("Audio duration must be positive and no longer than four hours")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=output) as scratch:
        normalized = Path(scratch) / "normalized.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(audio),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(normalized),
            ],
            check=True,
            capture_output=True,
            timeout=min(timeout, 300),
        )
        preparation_seconds = time.monotonic() - started
        temperature_start = _temperature()
        cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        recognition_start = time.monotonic()
        with (output / "engine.log").open("w") as log:
            subprocess.run(
                [
                    str(binary.resolve()),
                    "-m",
                    str(model.resolve()),
                    "-f",
                    str(normalized.resolve()),
                    "-t",
                    str(threads),
                    "-l",
                    language,
                    "-otxt",
                    "-oj",
                    "-of",
                    str((output / "transcript").resolve()),
                ],
                check=True,
                stdout=log,
                stderr=log,
                timeout=timeout,
            )
        elapsed = time.monotonic() - recognition_start
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "machine": platform.machine(),
        "model": model.name,
        "threads": threads,
        "audio_seconds": duration,
        "preparation_seconds": preparation_seconds,
        "inference_seconds": elapsed,
        "real_time_factor": real_time_factor(elapsed, duration),
        "child_cpu_seconds": (
            usage.ru_utime + usage.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime
        ),
        # Linux ru_maxrss is KiB and is a process-lifetime high-water mark. Run once per process.
        "child_peak_rss_mib": usage.ru_maxrss / 1024,
        "temperature_start_c": temperature_start,
        "temperature_end_c": _temperature(),
        "word_error_rate": None,
    }
    if reference:
        result["word_error_rate"] = word_error_rate(
            reference.read_text(),
            (output / "transcript.txt").read_text(),
        )
    (output / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("binary", "model", "audio", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    try:
        result = run_benchmark(**vars(args))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        parser.exit(1, f"Benchmark failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
