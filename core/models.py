"""Pydantic models shared across all modules."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel
from datetime import datetime
import hashlib


class JobPost(BaseModel):
    """A single job posting returned by a scraper."""
    id: str = ""                    # sha256 fingerprint — set by deduplicator
    source: str                     # linkedin | indeed | glassdoor | zip_recruiter
    title: str
    company: str
    location: Optional[str] = None
    is_remote: bool = False
    job_url: str
    application_url: Optional[str] = None
    description: Optional[str] = None
    date_posted: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = "USD"

    def compute_id(self) -> str:
        raw = f"{self.title.lower().strip()}|{self.company.lower().strip()}|{self.job_url.strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self.compute_id()


class TailoringMetadata(BaseModel):
    job_id: str
    job_title: str
    company: str
    changes_summary: str
    tailored_at: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.tailored_at:
            self.tailored_at = datetime.utcnow().isoformat() + "Z"


class TailoredResume(BaseModel):
    """Claude's tailored version of the master resume. Same schema, reordered/rephrased only."""
    _tailoring_metadata: Optional[TailoringMetadata] = None
    personal: dict[str, Any]
    summary: str
    education: list[dict[str, Any]]
    experience: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    skills: dict[str, Any]
    certifications: list[str] = []
    volunteer: list[Any] = []
    languages_spoken: list[str] = []
