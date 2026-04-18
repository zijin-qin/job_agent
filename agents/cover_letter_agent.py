"""Calls Gemini to generate a tailored cover letter for a specific job."""
import logging

import config
from core import llm_client, cover_letter_builder
from core.models import JobPost

logger = logging.getLogger(__name__)


async def generate_for_job(job: JobPost, tailored_resume: dict) -> dict:
    """
    Generate a cover letter tailored to the given job using the already-tailored resume.
    Saves the result to data/outputs/{job.id}/cover_letter.json.
    Returns the cover letter dict with a 'paragraphs' list.
    """
    personal = {
        k: v for k, v in {
            "name": config.PERSONAL_NAME,
            "email": config.PERSONAL_EMAIL,
            "phone": config.PERSONAL_PHONE,
            "linkedin": config.PERSONAL_LINKEDIN,
            "github": config.PERSONAL_GITHUB,
            "location": config.PERSONAL_LOCATION,
        }.items() if v
    }

    description = job.description or f"{job.title} at {job.company}"

    logger.info("Generating cover letter for: %s @ %s (job_id=%s)", job.title, job.company, job.id)

    cover_letter = await llm_client.generate_cover_letter_async(
        tailored_resume=tailored_resume,
        personal=personal,
        job_description=description,
        job_title=job.title,
        company=job.company,
        job_id=job.id,
    )

    cover_letter_builder.save_cover_letter_json(cover_letter, job.id, job=job)
    return cover_letter