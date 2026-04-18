"""Renders a cover letter JSON into a PDF using Playwright + Jinja2."""
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import config
from config import COVER_LETTER_TEMPLATE_PATH, OUTPUTS_DIR
from core.models import JobPost


def _slug(text: str, max_len: int = 25) -> str:
    s = re.sub(r"[^\w\s-]", "", text).strip()
    s = re.sub(r"[\s_]+", "-", s)
    return s[:max_len].rstrip("-")


def output_dir_for(job: JobPost) -> Path:
    date = (job.date_posted or "")[:10] or "unknown-date"
    company = _slug(job.company)
    title = _slug(job.title)
    short_id = job.id[:6]
    return OUTPUTS_DIR / f"{date}_{company}_{title}_{short_id}"


def build_cover_letter_pdf(cover_letter: dict, job_id: str, job: JobPost = None) -> Path:
    """Render the cover letter to a PDF. Returns path to the PDF file."""
    output_dir = output_dir_for(job) if job else OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    name = config.PERSONAL_NAME or "Applicant"
    pdf_filename = re.sub(r"\s+", "_", name.strip()) + "_Cover_Letter.pdf"
    pdf_path = output_dir / pdf_filename

    template_dir = COVER_LETTER_TEMPLATE_PATH.parent
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template(COVER_LETTER_TEMPLATE_PATH.name)

    cl_data = {k: v for k, v in cover_letter.items() if not k.startswith("_")}
    personal = {
        "name": config.PERSONAL_NAME,
        "email": config.PERSONAL_EMAIL,
        "phone": config.PERSONAL_PHONE,
        "linkedin": config.PERSONAL_LINKEDIN,
        "location": config.PERSONAL_LOCATION,
    }

    html_content = template.render(personal=personal, job=job, **cl_data)
    from core.resume_builder import _html_to_pdf
    _html_to_pdf(html_content, pdf_path)
    return pdf_path


def save_cover_letter_json(cover_letter: dict, job_id: str, job: JobPost = None) -> Path:
    output_dir = output_dir_for(job) if job else OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "cover_letter.json"
    path.write_text(json.dumps(cover_letter, indent=2))
    return path