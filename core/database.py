"""SQLite persistence layer. All DB access goes through this module."""
import aiosqlite
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DB_PATH
from core.models import JobPost


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    is_remote       BOOLEAN DEFAULT 0,
    job_url         TEXT NOT NULL,
    application_url TEXT,
    description     TEXT,
    date_posted     TEXT,
    discovered_at   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'discovered',
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_currency TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    applied_at          TEXT NOT NULL,
    resume_path         TEXT NOT NULL,
    cover_letter_path   TEXT,
    confirmation_text   TEXT,
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS seen_jobs (
    url_hash    TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL
);
"""

# Valid job status values
STATUS_DISCOVERED   = "discovered"
STATUS_APPROVED     = "approved"
STATUS_TAILORING    = "tailoring"
STATUS_REVIEWING    = "reviewing"
STATUS_FORM_READY   = "form_ready"
STATUS_SKIPPED      = "skipped"
STATUS_APPLIED      = "applied"
STATUS_FAILED       = "failed"
# Post-application statuses (set manually via --update)
STATUS_PHONE_SCREEN = "phone_screen"
STATUS_INTERVIEW    = "interview"
STATUS_OFFER        = "offer"
STATUS_REJECTED     = "rejected"
STATUS_GHOSTED      = "ghosted"
STATUS_WITHDRAWN    = "withdrawn"

POST_APP_STATUSES = {
    "phone":      STATUS_PHONE_SCREEN,
    "interview":  STATUS_INTERVIEW,
    "offer":      STATUS_OFFER,
    "rejected":   STATUS_REJECTED,
    "ghosted":    STATUS_GHOSTED,
    "withdrawn":  STATUS_WITHDRAWN,
}


async def init_db() -> None:
    """Create tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()


async def is_already_seen(job_url: str) -> bool:
    h = _url_hash(job_url)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM seen_jobs WHERE url_hash = ?", (h,)) as cur:
            return await cur.fetchone() is not None


async def mark_seen(job_url: str) -> None:
    h = _url_hash(job_url)
    now = datetime.utcnow().isoformat() + "Z"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_jobs (url_hash, first_seen) VALUES (?, ?)",
            (h, now),
        )
        await db.commit()


async def insert_discovered_job(job: JobPost) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO jobs
               (id, source, title, company, location, is_remote, job_url,
                application_url, description, date_posted, discovered_at,
                status, salary_min, salary_max, salary_currency)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.id, job.source, job.title, job.company, job.location,
                job.is_remote, job.job_url, job.application_url,
                job.description, job.date_posted, now,
                STATUS_DISCOVERED, job.salary_min, job.salary_max, job.salary_currency,
            ),
        )
        await db.commit()
    await mark_seen(job.job_url)


async def update_job_status(job_id: str, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        await db.commit()


async def mark_applied(
    job_id: str,
    resume_path: str,
    cover_letter_path: str = "",
    confirmation_text: Optional[str] = None,
) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO applications
               (job_id, applied_at, resume_path, cover_letter_path, confirmation_text)
               VALUES (?,?,?,?,?)""",
            (job_id, now, resume_path, cover_letter_path or "", confirmation_text),
        )
        await db.execute(
            "UPDATE jobs SET status = ? WHERE id = ?", (STATUS_APPLIED, job_id)
        )
        await db.commit()


async def get_all_applications() -> list[dict]:
    """Return all applied jobs with their current status, newest first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT j.id, j.title, j.company, j.location, j.is_remote,
                      j.source, j.job_url, j.status, j.date_posted,
                      j.salary_min, j.salary_max, j.salary_currency,
                      a.applied_at, a.notes
               FROM jobs j
               LEFT JOIN applications a ON a.job_id = j.id
               WHERE j.status NOT IN ('discovered','approved','tailoring','reviewing','skipped','failed')
               ORDER BY a.applied_at DESC""",
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_application_status(job_id: str, status: str, notes: str = "") -> bool:
    """Update status (and optionally notes) for an application. Returns False if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        if notes:
            await db.execute(
                "UPDATE applications SET notes = ? WHERE job_id = ?", (notes, job_id)
            )
        await db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        await db.commit()
        async with db.execute("SELECT changes()") as cur:
            row = await cur.fetchone()
    return bool(row and row[0])


async def export_applications_csv() -> Path:
    """Write all applications to data/applications.csv. Returns the path."""
    from config import DATA_DIR
    apps = await get_all_applications()
    out = DATA_DIR / "applications.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "title", "company", "location", "remote",
            "source", "date_posted", "applied_at", "status",
            "job_url", "notes"
        ])
        writer.writeheader()
        for app in apps:
            writer.writerow({
                "id":          app.get("id", "")[:8],
                "title":       app.get("title", ""),
                "company":     app.get("company", ""),
                "location":    app.get("location", ""),
                "remote":      "Yes" if app.get("is_remote") else "No",
                "source":      app.get("source", ""),
                "date_posted": (app.get("date_posted") or "")[:10],
                "applied_at":  (app.get("applied_at") or "")[:10],
                "status":      app.get("status", ""),
                "job_url":     app.get("job_url", ""),
                "notes":       app.get("notes") or "",
            })
    return out


async def get_daily_approved_count() -> int:
    """Count jobs approved at CP1 today (across all runs)."""
    today = datetime.utcnow().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM jobs WHERE DATE(discovered_at) = ? AND status != ?",
            (today, STATUS_DISCOVERED),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def get_daily_stats() -> dict:
    today = datetime.utcnow().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, COUNT(*) as n FROM jobs WHERE DATE(discovered_at) = ? GROUP BY status",
            (today,),
        ) as cur:
            rows = await cur.fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    total = sum(counts.values())
    return {"date": today, "total_discovered": total, **counts}
