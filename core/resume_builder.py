"""Renders a TailoredResume JSON into a PDF using Playwright + Jinja2."""
from pathlib import Path
import json
import re

from jinja2 import Environment, FileSystemLoader

import config
from config import RESUME_TEMPLATE_PATH, OUTPUTS_DIR
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


def _html_to_pdf(html_content: str, output_path: Path) -> None:
    """Render HTML to PDF via Playwright (Chromium). No system GTK/Cairo deps needed."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        page.pdf(
            path=str(output_path),
            format="Letter",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()


def build_pdf(tailored_resume: dict, job_id: str, job: JobPost = None) -> Path:
    """
    Render the tailored resume to a PDF.
    Only call this after the user has approved the tailored content.
    """
    output_dir = output_dir_for(job) if job else OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    name = config.PERSONAL_NAME or "Resume"
    pdf_path = output_dir / (re.sub(r"\s+", "_", name.strip()) + "_Resume.pdf")

    template_dir = RESUME_TEMPLATE_PATH.parent
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template(RESUME_TEMPLATE_PATH.name)

    resume_data = {k: v for k, v in tailored_resume.items() if not k.startswith("_")}
    html_content = template.render(**resume_data)

    _html_to_pdf(html_content, pdf_path)
    return pdf_path


def save_tailored_json(tailored_resume: dict, job_id: str, job: JobPost = None) -> Path:
    output_dir = output_dir_for(job) if job else OUTPUTS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "tailored_resume.json"
    path.write_text(json.dumps(tailored_resume, indent=2))
    return path
