"""Tests for deduplication logic."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, patch
from core.models import JobPost
from core import deduplicator


def make_job(title: str, company: str, url: str) -> JobPost:
    return JobPost(source="test", title=title, company=company, job_url=url)


@pytest.mark.asyncio
async def test_filter_removes_seen_jobs():
    jobs = [
        make_job("Data Analyst", "ACME", "https://example.com/job/1"),
        make_job("Data Scientist", "Beta", "https://example.com/job/2"),
    ]
    # First job is already seen, second is not
    with patch("core.deduplicator.db.is_already_seen", new=AsyncMock(side_effect=[True, False])):
        result = await deduplicator.filter_new_jobs(jobs)

    assert len(result) == 1
    assert result[0].title == "Data Scientist"


@pytest.mark.asyncio
async def test_filter_removes_within_batch_duplicates():
    job = make_job("Data Analyst", "ACME", "https://example.com/job/3")
    duplicate = make_job("Data Analyst", "ACME", "https://example.com/job/3")
    duplicate.id = job.id  # Force same ID

    with patch("core.deduplicator.db.is_already_seen", new=AsyncMock(return_value=False)):
        result = await deduplicator.filter_new_jobs([job, duplicate])

    assert len(result) == 1


@pytest.mark.asyncio
async def test_all_new_jobs_pass_through():
    jobs = [make_job(f"Job {i}", "Company", f"https://example.com/job/{i}") for i in range(5)]
    with patch("core.deduplicator.db.is_already_seen", new=AsyncMock(return_value=False)):
        result = await deduplicator.filter_new_jobs(jobs)
    assert len(result) == 5
