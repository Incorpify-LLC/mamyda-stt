import json
import subprocess
from types import SimpleNamespace

import pytest

from mamyda_stt.benchmark import real_time_factor, run_benchmark, word_error_rate


def test_real_time_factor():
    assert real_time_factor(60, 30) == 2


@pytest.mark.parametrize("duration", [0, -1])
def test_reject_invalid_duration(duration):
    with pytest.raises(ValueError):
        real_time_factor(10, duration)


def test_reference_based_word_error_rate():
    assert word_error_rate("Hello, world!", "hello world") == 0
    assert word_error_rate("one two three", "one four three") == pytest.approx(1 / 3)
    assert word_error_rate("one two", "one") == 0.5
    assert word_error_rate("one", "one two three") == 2


def test_no_reference_means_no_accuracy_claim():
    with pytest.raises(ValueError):
        word_error_rate("", "invented speech")


def benchmark_options(tmp_path):
    files = {name: tmp_path / name for name in ("binary", "model", "audio")}
    for path in files.values():
        path.touch()
    return {**files, "output": tmp_path / "results", "threads": 2, "timeout": 120}


def test_benchmark_measures_without_exposing_transcript(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps({"format": {"duration": "10"}}))
        if "-otxt" in command:
            (tmp_path / "results" / "transcript.txt").write_text("private speech")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_benchmark(**benchmark_options(tmp_path))
    assert result["audio_seconds"] == 10
    assert result["word_error_rate"] is None
    assert "private speech" not in json.dumps(result)
    assert len(calls) == 3
    assert all(call[1]["timeout"] > 0 for call in calls)
    assert not list((tmp_path / "results").glob("prepare-*"))


def test_timeout_is_not_reported_as_success(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps({"format": {"duration": "10"}}))
        raise subprocess.TimeoutExpired(command, 120)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        run_benchmark(**benchmark_options(tmp_path))
    assert not (tmp_path / "results" / "metrics.json").exists()
    assert not list((tmp_path / "results").glob("prepare-*"))


def test_benchmark_refuses_to_overwrite_results(tmp_path):
    options = benchmark_options(tmp_path)
    options["output"].mkdir()
    with pytest.raises(ValueError, match="already exists"):
        run_benchmark(**options)
