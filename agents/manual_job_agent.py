"""
Manual apply mode: given one or more job posting URLs, extract job info,
run the tailoring pipeline (resume + cover letter), let the user review,
then record the application after they confirm.

Usage:  python main.py --apply-url https://...  [https://... ...]
"""
import asyncio
import logging
from datetime import date

from core import database as db, llm_client
from core.models import JobPost
from agents import orchestrator

logger = logging.getLogger(__name__)


async def _fetch_page_text(url: str) -> str:
    """Fetch rendered page text via Playwright (handles JS-heavy SPAs like ADP/Workday)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(4000)  # extra wait for SPA content to render
            text = await page.inner_text("body")
        finally:
            await browser.close()
    return text


async def _extract_job_from_url(url: str) -> dict:
    """Fetch page and call Gemini to extract structured job info."""
    print(f"  Fetching page content...")
    page_text = await _fetch_page_text(url)
    print(f"  Extracting job details via AI...")
    return await llm_client.extract_job_info_from_html_async(page_text, url)


def _prompt_correct(label: str, current: str) -> str:
    """Show current value, let user press Enter to keep or type a correction."""
    display = current or "(not found)"
    entered = input(f"    {label} [{display}]: ").strip()
    return entered if entered else current


def _confirm_job_info(job_data: dict, url: str) -> JobPost | None:
    """Show extracted job info — user can correct any field or skip."""
    title = job_data.get("title") or ""
    company = job_data.get("company") or ""
    location = job_data.get("location") or ""
    is_remote = job_data.get("is_remote", False)
    application_url = job_data.get("application_url") or url

    print(f"\n  Extracted job info (press Enter to keep, or type a correction):")
    title = _prompt_correct("Title", title)
    company = _prompt_correct("Company", company)
    location = _prompt_correct("Location", location)

    if not title or not company:
        print("  Skipping — title and company are required.")
        return None

    confirm = input("\n  Proceed with tailoring? [Y/n]: ").strip().lower()
    if confirm == "n":
        return None

    return JobPost(
        source="manual",
        title=title,
        company=company,
        location=location or None,
        is_remote=is_remote,
        job_url=url,
        application_url=application_url if application_url != url else None,
        description=job_data.get("description") or "",
        date_posted=date.today().isoformat(),
    )


async def process_manual_jobs(urls: list[str]) -> None:
    """
    Main entry point for --apply-url mode.
    For each URL: extract job → confirm with user → run tailoring pipeline.
    """
    await db.init_db()

    total = len(urls)
    applied_count = 0
    skipped_count = 0

    for i, url in enumerate(urls, 1):
        print(f"\n{'─'*50}")
        print(f"[job_agent] URL {i}/{total}: {url}")

        try:
            job_data = await _extract_job_from_url(url)
        except Exception as exc:
            logger.error("Failed to extract job from %s: %s", url, exc)
            print(f"  Error fetching/extracting job info: {exc}")
            skipped_count += 1
            continue

        job = _confirm_job_info(job_data, url)
        if not job:
            skipped_count += 1
            continue

        await db.insert_discovered_job(job)
        await db.update_job_status(job.id, db.STATUS_APPROVED)

        applied = await orchestrator.process_single_job(job)
        if applied:
            applied_count += 1
        else:
            skipped_count += 1

    print(f"\n{'─'*50}")
    print(f"[job_agent] Manual Apply Summary")
    print(f"  Applied : {applied_count}")
    print(f"  Skipped : {skipped_count}")
    print(f"{'─'*50}\n")
