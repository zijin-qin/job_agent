"""
Handshake scraper using Playwright.

First run: launches a visible browser so you can log in via UCSD SSO.
           Session is saved to data/handshake_session.json automatically.
Subsequent runs: headless, uses the saved session.

Enable by setting USE_HANDSHAKE=true in your .env file.
Disable or remove by setting USE_HANDSHAKE=false (or just deleting this file).
"""
import asyncio
import logging
from datetime import datetime, timezone

from playwright.async_api import async_playwright

import config
from config import DATA_DIR
from core.models import JobPost

logger = logging.getLogger(__name__)

SESSION_PATH = DATA_DIR / "handshake_session.json"
HANDSHAKE_JOBS_URL = "https://app.joinhandshake.com/stu/jobs"


async def _ensure_logged_in(page) -> bool:
    """
    Navigate to Handshake jobs. If redirected to login, prompt user to log in
    interactively and save the session. Returns True if logged in successfully.
    """
    await page.goto(HANDSHAKE_JOBS_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    if "sign_in" in page.url or "login" in page.url or "shibboleth" in page.url:
        if SESSION_PATH.exists():
            logger.warning("Handshake session expired — need to log in again.")
            SESSION_PATH.unlink()
        print("\n[Handshake] Browser opened — please log in via UCSD SSO.")
        print("[Handshake] The scraper will continue automatically once you're on the jobs page.\n")
        try:
            await page.wait_for_url("**/stu/jobs**", timeout=120000)
        except Exception:
            logger.warning("Handshake login timed out.")
            return False

    return True


async def _search_role(page, role: str, hours_old: int) -> list[dict]:
    """
    Search Handshake for a role and intercept the JSON API response.
    Returns raw job dicts from Handshake's internal API.
    """
    captured: list[dict] = []

    async def handle_response(response):
        url = response.url
        if "/jobs.json" in url or "/postings" in url:
            try:
                data = await response.json()
                items = data.get("jobs") or data.get("postings") or (data if isinstance(data, list) else [])
                captured.extend(items)
            except Exception:
                pass

    page.on("response", handle_response)

    search_url = (
        f"{HANDSHAKE_JOBS_URL}"
        f"?query={role.replace(' ', '+')}"
        f"&sort_direction=desc&sort_column=posted_at"
        f"&employment_type_names[]=Full-Time"
        f"&employment_type_names[]=Part-Time"
    )
    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)
    page.remove_listener("response", handle_response)

    return captured


def _parse_job(raw: dict) -> JobPost | None:
    """Convert a raw Handshake job dict to a JobPost."""
    try:
        job_id = str(raw.get("id", ""))
        title = str(raw.get("title") or raw.get("job_title") or "")
        employer = raw.get("employer") or raw.get("company") or {}
        company = str(employer.get("name") or employer if isinstance(employer, str) else "")
        location = str(raw.get("city") or raw.get("location") or "")
        if raw.get("state_info"):
            location = f"{location}, {raw['state_info'].get('name', '')}".strip(", ")
        job_url = f"https://app.joinhandshake.com/stu/jobs/{job_id}"
        posted_at = raw.get("created_at") or raw.get("posted_at") or ""
        date_posted = posted_at[:10] if posted_at else None
        is_remote = bool(raw.get("remote") or raw.get("is_remote"))

        if not (job_id and title and company):
            return None

        return JobPost(
            source="handshake",
            title=title,
            company=company,
            location=location or None,
            is_remote=is_remote,
            job_url=job_url,
            application_url=job_url,
            description=str(raw.get("description") or ""),
            date_posted=date_posted,
        )
    except Exception as exc:
        logger.debug("Failed to parse Handshake job: %s", exc)
        return None


async def scrape_handshake() -> list[JobPost]:
    """
    Main entry point. Returns a list of JobPost objects from Handshake.
    Skips silently if USE_HANDSHAKE is not enabled.
    """
    if not config.USE_HANDSHAKE:
        return []

    headless = SESSION_PATH.exists()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_kwargs = {}
        if SESSION_PATH.exists():
            context_kwargs["storage_state"] = str(SESSION_PATH)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        logged_in = await _ensure_logged_in(page)
        if not logged_in:
            await browser.close()
            logger.warning("Handshake scrape skipped — could not log in.")
            return []

        # Save/refresh session
        await context.storage_state(path=str(SESSION_PATH))

        all_raw: list[dict] = []
        for role in config.TARGET_ROLES:
            try:
                raw = await _search_role(page, role, config.HOURS_OLD)
                logger.info("Handshake: role '%s' returned %d raw results", role, len(raw))
                all_raw.extend(raw)
            except Exception as exc:
                logger.warning("Handshake scrape failed for role '%s': %s", role, exc)

        await browser.close()

    jobs = [j for raw in all_raw if (j := _parse_job(raw)) is not None]
    # Deduplicate by URL within this batch
    seen_urls: set[str] = set()
    unique_jobs = []
    for job in jobs:
        if job.job_url not in seen_urls:
            seen_urls.add(job.job_url)
            unique_jobs.append(job)

    unique_jobs.sort(key=lambda j: j.date_posted or "", reverse=True)
    logger.info("Handshake: %d unique jobs after dedup", len(unique_jobs))
    return unique_jobs
