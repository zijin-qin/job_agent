"""
Playwright-based fallback scraper for job boards not covered by jobspy,
or when jobspy returns fewer results than expected.
Currently targets: Wellfound (AngelList), and direct Greenhouse/Lever/Workday boards.
"""
import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import async_playwright, Page

import config
from config import RESULTS_PER_ROLE
from core.models import JobPost

logger = logging.getLogger(__name__)

WELLFOUND_BASE = "https://wellfound.com/jobs"


async def _safe_text(page: Page, selector: str) -> Optional[str]:
    try:
        el = await page.query_selector(selector)
        return (await el.inner_text()).strip() if el else None
    except Exception:
        return None


async def scrape_wellfound(role: str, limit: int = RESULTS_PER_ROLE) -> list[JobPost]:
    """Scrape Wellfound for a single role. Returns up to `limit` jobs."""
    jobs: list[JobPost] = []
    search_query = role.replace(" ", "%20")
    url = f"{WELLFOUND_BASE}?q={search_query}&role=data"

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
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Wellfound job cards
            cards = await page.query_selector_all("[data-test='JobListing']")
            if not cards:
                cards = await page.query_selector_all(".job-listing")

            for card in cards[:limit]:
                try:
                    title_el = await card.query_selector("a[data-test='job-title'], h2 a, .job-title a")
                    company_el = await card.query_selector("[data-test='company-name'], .company-name")
                    location_el = await card.query_selector("[data-test='location'], .location")
                    link_el = await card.query_selector("a[href*='/jobs/']")

                    title = (await title_el.inner_text()).strip() if title_el else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""
                    location = (await location_el.inner_text()).strip() if location_el else None
                    href = await link_el.get_attribute("href") if link_el else ""
                    job_url = f"https://wellfound.com{href}" if href and href.startswith("/") else href

                    if title and company and job_url:
                        jobs.append(JobPost(
                            source="wellfound",
                            title=title,
                            company=company,
                            location=location,
                            is_remote="remote" in (location or "").lower(),
                            job_url=job_url,
                            application_url=job_url,
                        ))
                except Exception as exc:
                    logger.debug("Wellfound card parse error: %s", exc)

        except Exception as exc:
            logger.warning("Wellfound scrape failed for '%s': %s", role, exc)
        finally:
            await browser.close()

    return jobs


async def scrape_fallback_all_roles(needed: int = 50, already_found: int = 0) -> list[JobPost]:
    """
    Called when jobspy doesn't return enough results.
    `needed` = how many more jobs we still need.
    """
    if already_found >= needed:
        return []

    per_role = max(5, (needed - already_found) // len(config.TARGET_ROLES))
    tasks = [scrape_wellfound(role, limit=per_role) for role in config.TARGET_ROLES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_jobs: list[JobPost] = []
    for role, result in zip(config.TARGET_ROLES, results):
        if isinstance(result, Exception):
            logger.error("Fallback scrape error for '%s': %s", role, result)
        else:
            all_jobs.extend(result)

    return all_jobs
