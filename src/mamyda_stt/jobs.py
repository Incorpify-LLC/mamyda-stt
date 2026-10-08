"""Single-worker durable queue. Worker interruption fails closed, never re-bills."""

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


class NotFound(Exception):
    """Missing, expired or not owned; intentionally indistinguishable."""


class Conflict(Exception):
    """Conflicting idempotency input or invalid worker lease."""


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=10, isolation_level=None)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, application TEXT NOT NULL, subject TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL
                  CHECK(state IN ('queued','running','complete','failed','cancelled')),
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                worker TEXT, lease_until REAL, result TEXT, error TEXT,
                UNIQUE(application, subject, idempotency_key))""")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state, created_at)")
        self.path.chmod(0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _record(row):
        record = dict(row)
        for field in ("payload", "result"):
            record[field] = json.loads(record[field]) if record[field] is not None else None
        return record

    def submit(self, *, application, subject, idempotency_key, payload, now, retention_seconds):
        if not 0 < retention_seconds <= 15 * 86400:
            raise ValueError("Retention must be between 1 second and 15 days")
        if not application or not subject or not idempotency_key:
            raise ValueError("Application, subject and idempotency key are required")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._db() as db:
            existing = db.execute(
                "SELECT * FROM jobs WHERE application=? AND subject=? AND idempotency_key=?",
                (application, subject, idempotency_key),
            ).fetchone()
            if existing:
                if existing["expires_at"] <= now:
                    raise Conflict("Idempotency key expired; explicitly submit a new request")
                if existing["payload"] != encoded:
                    raise Conflict("Idempotency key already used with different input")
                return self._record(existing)
            job_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO jobs(id,application,subject,idempotency_key,payload,state,
                   created_at,expires_at) VALUES(?,?,?,?,?,'queued',?,?)""",
                (
                    job_id,
                    application,
                    subject,
                    idempotency_key,
                    encoded,
                    now,
                    now + retention_seconds,
                ),
            )
            return self._record(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get(self, job_id, application, subject, *, now):
        with self._db() as db:
            row = self._owned(db, job_id, application, subject, now)
            return self._record(row)

    @staticmethod
    def _owned(db, job_id, application, subject, now):
        row = db.execute(
            "SELECT * FROM jobs WHERE id=? AND application=? AND subject=? AND expires_at>?",
            (job_id, application, subject, now),
        ).fetchone()
        if row is None:
            raise NotFound()
        return row

    def claim(self, worker, *, now, lease_seconds):
        if not worker or not 0 < lease_seconds <= 3600:
            raise ValueError("A worker identity and bounded positive lease are required")
        with self._db() as db:
            # Only one active lease across this service, including concurrent connections.
            active = db.execute(
                "SELECT * FROM jobs WHERE state='running' AND expires_at>? LIMIT 1",
                (now,),
            ).fetchone()
            if active:
                if active["lease_until"] > now:
                    return None
                db.execute(
                    """UPDATE jobs SET state='failed',error='worker_interrupted',
                       worker=NULL,lease_until=NULL WHERE id=?""",
                    (active["id"],),
                )
                return self._record(
                    db.execute("SELECT * FROM jobs WHERE id=?", (active["id"],)).fetchone()
                )
            row = db.execute(
                """SELECT * FROM jobs WHERE state='queued' AND expires_at>?
                   ORDER BY created_at,rowid LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET state='running',worker=?,lease_until=? WHERE id=?",
                (worker, min(now + lease_seconds, row["expires_at"]), row["id"]),
            )
            claimed = db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            return self._record(claimed)

    def _worker_update(self, job_id, worker, now, assignments, values):
        with self._db() as db:
            changed = db.execute(
                f"UPDATE jobs SET {assignments} WHERE id=? AND worker=? AND state='running' "
                "AND lease_until>? AND expires_at>?",
                (*values, job_id, worker, now, now),
            ).rowcount
            if changed != 1:
                raise Conflict("Lease expired, cancelled, interrupted or owned by another worker")

    def heartbeat(self, job_id, worker, *, now, lease_seconds):
        if not 0 < lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        self._worker_update(
            job_id,
            worker,
            now,
            "lease_until=MIN(?,expires_at)",
            (now + lease_seconds,),
        )

    def finish(self, job_id, worker, result, *, now):
        encoded = json.dumps(result, allow_nan=False)
        self._worker_update(
            job_id,
            worker,
            now,
            "state='complete',result=?,worker=NULL,lease_until=NULL",
            (encoded,),
        )

    def cancel(self, job_id, application, subject, *, now):
        with self._db() as db:
            self._owned(db, job_id, application, subject, now)
            db.execute(
                """UPDATE jobs SET state='cancelled',result=NULL,worker=NULL,lease_until=NULL
                   WHERE id=?""",
                (job_id,),
            )

    def expire(self, *, now):
        with self._db() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM jobs WHERE expires_at<=?", (now,))]
            db.execute("DELETE FROM jobs WHERE expires_at<=?", (now,))
            return ids
