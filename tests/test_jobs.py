import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from mamyda_stt.jobs import Conflict, JobStore, NotFound


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs.sqlite3")


def submit(store, **overrides):
    options = dict(
        application="mamyda",
        subject="user-1",
        idempotency_key="one",
        payload={"upload_id": "upload-1", "model": "whisper-base"},
        now=100,
        retention_seconds=3600,
    )
    options.update(overrides)
    return store.submit(**options)


def test_persistence_and_idempotent_submission(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    job = submit(JobStore(path))
    reopened = JobStore(path)
    assert submit(reopened)["id"] == job["id"]
    assert reopened.get(job["id"], "mamyda", "user-1", now=101)["state"] == "queued"


def test_idempotency_rejects_changed_input(store):
    submit(store)
    with pytest.raises(Conflict):
        submit(store, payload={"upload_id": "different", "model": "whisper-base"})


@pytest.mark.parametrize("application,subject", [("other", "user-1"), ("mamyda", "other")])
def test_isolation(store, application, subject):
    job = submit(store)
    with pytest.raises(NotFound):
        store.get(job["id"], application, subject, now=101)
    independent = submit(store, application=application, subject=subject)
    assert independent["id"] != job["id"]


def test_expired_jobs_are_not_readable_or_leased(store):
    job = submit(store)
    with pytest.raises(NotFound):
        store.get(job["id"], "mamyda", "user-1", now=3700)
    assert store.claim("worker", now=3700, lease_seconds=60) is None
    assert store.expire(now=3700) == [job["id"]]


def test_one_active_worker_and_recovery_after_restart(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    store = JobStore(path)
    job = submit(store)
    submit(store, idempotency_key="two")
    claimed = store.claim("worker-1", now=101, lease_seconds=60)
    assert claimed["id"] == job["id"]
    assert store.claim("worker-2", now=102, lease_seconds=60) is None
    recovered = JobStore(path).claim("worker-2", now=161, lease_seconds=60)
    assert recovered["id"] == job["id"]
    assert recovered["state"] == "failed"
    assert recovered["error"] == "worker_interrupted"
    # Do not silently repeat an external/billable request after a worker crash.
    assert store.claim("worker-2", now=162, lease_seconds=60)["id"] != job["id"]


def test_stale_worker_cannot_finish_after_recovery(store):
    job = submit(store)
    store.claim("old", now=101, lease_seconds=60)
    store.claim("new", now=161, lease_seconds=60)
    with pytest.raises(Conflict):
        store.finish(job["id"], "old", {"text": "late result"}, now=162)


def test_finish_requires_live_lease_and_owner(store):
    job = submit(store)
    store.claim("worker", now=101, lease_seconds=60)
    with pytest.raises(Conflict):
        store.finish(job["id"], "other", {}, now=102)
    store.heartbeat(job["id"], "worker", now=150, lease_seconds=60)
    store.finish(job["id"], "worker", {"text": "hello"}, now=180)
    assert store.get(job["id"], "mamyda", "user-1", now=181)["result"] == {"text": "hello"}


def test_cancel_is_idempotent_and_discards_result(store):
    job = submit(store)
    store.claim("worker", now=101, lease_seconds=60)
    store.finish(job["id"], "worker", {"text": "private"}, now=102)
    store.cancel(job["id"], "mamyda", "user-1", now=103)
    store.cancel(job["id"], "mamyda", "user-1", now=104)
    cancelled = store.get(job["id"], "mamyda", "user-1", now=105)
    assert cancelled["state"] == "cancelled"
    assert cancelled["result"] is None


@pytest.mark.parametrize("retention", [0, -1, 15 * 86400 + 1])
def test_retention_bounds(store, retention):
    with pytest.raises(ValueError):
        submit(store, retention_seconds=retention)


def test_sqlite_uses_wal(store):
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_concurrent_submission_is_deduplicated(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    stores = [JobStore(path) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(submit, stores))
    assert len({job["id"] for job in jobs}) == 1


def test_concurrent_claims_allow_one_worker(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    stores = [JobStore(path) for _ in range(8)]
    for i in range(8):
        submit(stores[0], idempotency_key=str(i))
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(
            pool.map(
                lambda i: stores[i].claim(f"worker-{i}", now=101, lease_seconds=60),
                range(8),
            )
        )
    assert sum(job is not None for job in claims) == 1


def test_cancel_running_job_invalidates_worker_lease(store):
    job = submit(store)
    store.claim("worker", now=101, lease_seconds=60)
    store.cancel(job["id"], "mamyda", "user-1", now=102)
    with pytest.raises(Conflict):
        store.finish(job["id"], "worker", {"text": "must not survive"}, now=103)


def test_expired_worker_cannot_extend_lease(store):
    job = submit(store)
    store.claim("worker", now=101, lease_seconds=60)
    with pytest.raises(Conflict):
        store.heartbeat(job["id"], "worker", now=161, lease_seconds=60)
