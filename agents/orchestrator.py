"""
Top-level agentic loop.
Pipeline: discover → [CP1 job list] → for each job: tailor resume + cover letter → [CP2 review] → build PDFs → confirm applied → record.
"""
import asyncio
import logging
from datetime import date
from pathlib import Path

from config import JOBS_PER_DAY
from core import database as db
from core.models import JobPost
from core import resume_builder, cover_letter_builder
from agents import discovery_agent, tailoring_agent, cover_letter_agent
from review import cli_review

logger = logging.getLogger(__name__)


async def process_single_job(job: JobPost) -> bool:
    """
    Run the full tailoring + review + confirm pipeline for one job.
    Returns True if the user confirmed they applied, False if skipped/failed.
    Assumes the job is already in the DB with STATUS_APPROVED.
    """
    print(f"\n[job_agent] Processing: {job.title} @ {job.company}")

    await db.update_job_status(job.id, db.STATUS_TAILORING)

    # ── Tailor resume ──────────────────────────────────────────────────────────
    try:
        tailored_resume = await tailoring_agent.tailor_for_job(job)
    except Exception as exc:
        logger.error("Resume tailoring failed for job %s: %s", job.id, exc)
        await db.update_job_status(job.id, db.STATUS_FAILED)
        return False

    # ── Generate cover letter ─────────────────────────────────────────────────
    cover_letter: dict = {}
    try:
        cover_letter = await cover_letter_agent.generate_for_job(job, tailored_resume)
    except Exception as exc:
        logger.warning("Cover letter generation failed for job %s: %s", job.id, exc)
        # Non-fatal: pipeline continues with an empty cover letter

    await db.update_job_status(job.id, db.STATUS_REVIEWING)

    # ── Checkpoint 2: Per-job review (resume + cover letter) ──────────────────
    action, edited_cover_letter = await cli_review.checkpoint_2_per_job(
        job, tailored_resume, cover_letter
    )

    if action == "quit":
        print("[job_agent] Session quit by user.")
        return False

    if action == "retailor":
        print(f"[job_agent] Re-tailoring {job.title}...")
        try:
            tailored_resume = await tailoring_agent.tailor_for_job(job)
            cover_letter = await cover_letter_agent.generate_for_job(job, tailored_resume)
            action, edited_cover_letter = await cli_review.checkpoint_2_per_job(
                job, tailored_resume, cover_letter
            )
        except Exception as exc:
            logger.error("Re-tailoring failed: %s", exc)
            action = "skip"

    if action not in ("approved",):
        print(f"[job_agent] Skipped: {job.title} @ {job.company}")
        await db.update_job_status(job.id, db.STATUS_SKIPPED)
        return False

    # Apply cover letter edits from CP2
    if edited_cover_letter and "paragraphs" in cover_letter:
        cover_letter["paragraphs"] = edited_cover_letter

    # ── Build PDFs ─────────────────────────────────────────────────────────────
    try:
        pdf_path = await asyncio.to_thread(resume_builder.build_pdf, tailored_resume, job.id, job)
        cl_pdf_path: Path | None = None
        if cover_letter.get("paragraphs"):
            cover_letter_with_date = {**cover_letter, "date": date.today().strftime("%B %d, %Y")}
            cl_pdf_path = await asyncio.to_thread(
                cover_letter_builder.build_cover_letter_pdf, cover_letter_with_date, job.id, job
            )
    except Exception as exc:
        logger.error("PDF generation failed for job %s: %s", job.id, exc)
        await db.update_job_status(job.id, db.STATUS_FAILED)
        return False

    await db.update_job_status(job.id, db.STATUS_FORM_READY)

    # ── Manual apply confirm ───────────────────────────────────────────────────
    apply_url = job.application_url or job.job_url
    print(f"\n[job_agent] Documents ready for: {job.title} @ {job.company}")
    print(f"  Resume       : {pdf_path}")
    if cl_pdf_path:
        print(f"  Cover Letter : {cl_pdf_path}")
    print(f"  Apply at     : {apply_url}")
    print()

    confirm = input("  Press Enter after you've applied (or type 's' to skip): ").strip().lower()
    if confirm == "s":
        print(f"[job_agent] Skipped: {job.title} @ {job.company}")
        await db.update_job_status(job.id, db.STATUS_SKIPPED)
        return False

    await db.mark_applied(
        job_id=job.id,
        resume_path=str(pdf_path),
        cover_letter_path=str(cl_pdf_path) if cl_pdf_path else "",
        confirmation_text="Applied manually by user",
    )
    print(f"[job_agent] Recorded: {job.title} @ {job.company}")
    await db.export_applications_csv()
    return True


async def run_daily_pipeline(dry_run: bool = False) -> None:
    """Full daily pipeline: discover → CP1 → per-job loop."""
    await db.init_db()

    # ── Step 1: Discovery ──────────────────────────────────────────────────────
    print("\n[job_agent] Discovering new job postings...")
    jobs = await discovery_agent.discover_jobs()

    if not jobs:
        print("[job_agent] No new unseen jobs found. Try again tomorrow or use --limit to increase batch size.")
        return

    print(f"[job_agent] Found {len(jobs)} net-new postings. Opening review...")

    # ── Checkpoint 1: Job List Approval ───────────────────────────────────────
    approved_jobs = await cli_review.checkpoint_1_job_list(jobs)

    if not approved_jobs:
        print("[job_agent] No jobs approved or session quit. Exiting.")
        return

    print(f"[job_agent] {len(approved_jobs)} jobs approved for processing.")

    for job in approved_jobs:
        await db.insert_discovered_job(job)
        await db.update_job_status(job.id, db.STATUS_APPROVED)

    # ── Step 2: Per-Job Loop ───────────────────────────────────────────────────
    applied_count = 0
    skipped_count = 0

    for i, job in enumerate(approved_jobs, 1):
        print(f"\n[job_agent] Job {i}/{len(approved_jobs)}")

        if dry_run:
            print(f"[DRY RUN] Would process: {job.title} @ {job.company}")
            applied_count += 1
            continue

        applied = await process_single_job(job)
        if applied:
            applied_count += 1
        else:
            skipped_count += 1

    # ── Daily Summary ──────────────────────────────────────────────────────────
    stats = await db.get_daily_stats()
    print(f"\n{'─'*50}")
    print(f"[job_agent] Daily Summary — {stats['date']}")
    print(f"  Discovered : {stats.get('total_discovered', 0)}")
    print(f"  Applied    : {stats.get('applied', 0)}")
    print(f"  Skipped    : {stats.get('skipped', 0)}")
    print(f"  Failed     : {stats.get('failed', 0)}")
    print(f"{'─'*50}\n")
