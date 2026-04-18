"""Calls Gemini to tailor the master resume for a specific job description."""
import json
import logging
from pathlib import Path

import config
from config import MASTER_RESUME_PATH
from core import llm_client, resume_builder
from core.models import JobPost

logger = logging.getLogger(__name__)


def _load_master_resume() -> dict:
    if not MASTER_RESUME_PATH.exists():
        raise FileNotFoundError(
            f"Master resume not found at {MASTER_RESUME_PATH}. "
            "Copy data/master_resume.example.json to data/master_resume.json and fill in your content."
        )
    data = json.loads(MASTER_RESUME_PATH.read_text())
    data.pop("_instructions", None)

    # Overlay personal info from env vars (keeps PII out of the JSON file)
    personal_from_env = {
        k: v for k, v in {
            "name": config.PERSONAL_NAME,
            "email": config.PERSONAL_EMAIL,
            "phone": config.PERSONAL_PHONE,
            "linkedin": config.PERSONAL_LINKEDIN,
            "github": config.PERSONAL_GITHUB,
            "location": config.PERSONAL_LOCATION,
            "citizenship": config.PERSONAL_CITIZENSHIP,
        }.items() if v  # only override if the env var is set
    }
    if personal_from_env:
        data.setdefault("personal", {}).update(personal_from_env)

    return data


async def tailor_for_job(job: JobPost) -> dict:
    """
    Tailor the master resume for the given job.
    Saves the result to data/outputs/{job.id}/tailored_resume.json.
    Returns the tailored resume dict.

    NEVER modifies master_resume.json.
    """
    master = _load_master_resume()

    description = job.description or f"{job.title} at {job.company}"

    logger.info("Tailoring resume for: %s @ %s (job_id=%s)", job.title, job.company, job.id)

    tailored = await llm_client.tailor_resume_async(
        master_resume=master,
        job_description=description,
        job_title=job.title,
        company=job.company,
        job_id=job.id,
    )

    # Persist to disk (pre-approval; PDF not yet generated)
    resume_builder.save_tailored_json(tailored, job.id, job=job)

    return tailored
