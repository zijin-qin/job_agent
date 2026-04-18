"""Deduplication logic — filters job lists to net-new postings only."""
import asyncio
from typing import Sequence

from core.models import JobPost
from core import database as db


async def filter_new_jobs(jobs: Sequence[JobPost]) -> list[JobPost]:
    """
    Remove jobs already present in seen_jobs table.
    Also remove within-batch duplicates (same id).
    Returns net-new jobs, preserving input order.
    """
    seen_ids: set[str] = set()
    results: list[JobPost] = []

    checks = await asyncio.gather(*[db.is_already_seen(job.job_url) for job in jobs])

    for job, already_seen in zip(jobs, checks):
        if already_seen:
            continue
        if job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        results.append(job)

    return results
