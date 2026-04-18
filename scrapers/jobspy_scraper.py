"""Wraps python-jobspy to scrape multiple job boards concurrently."""
import asyncio
import logging
import random
from typing import Optional

from jobspy import scrape_jobs
import pandas as pd

import config
from config import HOURS_OLD, RESULTS_PER_ROLE, LOCATION, REMOTE_ONLY, SCRAPE_SITES, PROXY_URL
from core.models import JobPost

logger = logging.getLogger(__name__)


def _scrape_role_with_hours(role: str, hours_old: int) -> list[JobPost]:
    return _scrape_role(role, hours_old)


def _scrape_role(role: str, hours_old: int = HOURS_OLD) -> list[JobPost]:
    """Blocking call to jobspy for a single role. Run in a thread."""
    proxies = [PROXY_URL] if PROXY_URL else None
    try:
        df: pd.DataFrame = scrape_jobs(
            site_name=SCRAPE_SITES,
            search_term=role,
            location=LOCATION,
            results_wanted=RESULTS_PER_ROLE,
            hours_old=hours_old,
            is_remote=REMOTE_ONLY or False,
            proxies=proxies,
            linkedin_fetch_description=True,
            verbose=0,
        )
    except Exception as exc:
        logger.warning("jobspy scrape failed for role '%s': %s", role, exc)
        return []

    if df is None or df.empty:
        return []

    jobs: list[JobPost] = []
    for _, row in df.iterrows():
        try:
            job = JobPost(
                source=str(row.get("site", "unknown")),
                title=str(row.get("title", "")),
                company=str(row.get("company", "")),
                location=str(row.get("location", "")) or None,
                is_remote=bool(row.get("is_remote", False)),
                job_url=_clean_url(row.get("job_url")),
                application_url=_clean_url(row.get("job_url_direct")) or str(row.get("job_url", "")),
                description=str(row.get("description", "")) or None,
                date_posted=_clean_date(row.get("date_posted")),
                salary_min=_safe_int(row.get("min_amount")),
                salary_max=_safe_int(row.get("max_amount")),
                salary_currency=str(row.get("currency", "USD")) or "USD",
            )
            if job.title and job.company and job.job_url:
                jobs.append(job)
        except Exception as exc:
            logger.debug("Skipping malformed row: %s", exc)

    return jobs


def _clean_url(val) -> str:
    """Return a valid URL string, or empty string if val is NaN/None/invalid."""
    if val is None:
        return ""
    s = str(val).strip()
    return s if s.startswith("http") else ""


def _clean_date(val) -> Optional[str]:
    """Return a clean date string, or None if val is NaN/NaT/None/invalid."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "nat", "", "none"):
        return None
    return s


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val and not pd.isna(val) else None
    except (TypeError, ValueError):
        return None


async def scrape_all_roles(hours_old: int = HOURS_OLD) -> list[JobPost]:
    """
    Scrape all TARGET_ROLES sequentially with a short delay between each.
    Sequential (not concurrent) to avoid LinkedIn 429 rate limiting.
    """
    roles = config.TARGET_ROLES
    all_jobs: list[JobPost] = []

    for i, role in enumerate(roles):
        if i > 0:
            await asyncio.sleep(random.uniform(3, 8))
        try:
            jobs = await asyncio.to_thread(_scrape_role_with_hours, role, hours_old)
            logger.info("Role '%s': found %d postings", role, len(jobs))
            all_jobs.extend(jobs)
        except Exception as exc:
            logger.error("Error scraping role '%s': %s", role, exc)

    # Sort by date_posted descending (most recent first), nulls last
    all_jobs.sort(key=lambda j: j.date_posted or "", reverse=True)
    return all_jobs
