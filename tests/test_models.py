"""Tests for Pydantic models."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import JobPost, TailoredResume


def test_job_post_id_computed():
    job = JobPost(source="linkedin", title="Data Analyst", company="ACME", job_url="https://example.com/job/1")
    assert job.id
    assert len(job.id) == 16


def test_job_post_same_inputs_same_id():
    j1 = JobPost(source="linkedin", title="Data Analyst", company="ACME", job_url="https://example.com/job/1")
    j2 = JobPost(source="indeed", title="  Data Analyst  ", company="acme", job_url="https://example.com/job/1")
    assert j1.id == j2.id
