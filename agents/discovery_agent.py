"""Discovers new job postings and deduplicates against previously seen jobs."""
import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import config
from core import deduplicator
from core.models import JobPost
from scrapers import jobspy_scraper, fallback_scraper, handshake_scraper

logger = logging.getLogger(__name__)

_LAST_RUN_PATH = config.DATA_DIR / "last_run.txt"


def _get_hours_since_last_run() -> int:
    """Return hours elapsed since the last scrape run. Defaults to 24 on first run."""
    if not _LAST_RUN_PATH.exists():
        return 24
    try:
        last = datetime.fromisoformat(_LAST_RUN_PATH.read_text().strip())
        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        hours = max(1, int(elapsed) + 1)  # round up, minimum 1
        return min(hours, config.MAX_HOURS_OLD)
    except Exception:
        return 24


def record_run_time() -> None:
    _LAST_RUN_PATH.write_text(datetime.now(timezone.utc).isoformat())


_OVEREXP_RE = re.compile(
    r'\b([5-9]|\d{2,})\+?\s*(?:or more\s*)?years?\s*(?:of\s*)?(?:experience|exp)\b'
    r'|minimum\s+(?:of\s+)?([5-9]|\d{2,})\s*(?:\+)?\s*years?',
    re.IGNORECASE,
)

def _filter_overqualified(jobs: list[JobPost]) -> list[JobPost]:
    kept, removed = [], 0
    for job in jobs:
        desc = (job.description or "") + " " + job.title
        if _OVEREXP_RE.search(desc):
            removed += 1
        else:
            kept.append(job)
    if removed:
        print(f"[discovery] Filtered out {removed} job(s) requiring 5+ years experience.")
    return kept


_SCAM_RE = re.compile(
    r'commission[\s-]*only'
    r'|unlimited\s+(?:earning|income|compensation)\s+potential'
    r'|be\s+your\s+own\s+boss'
    r'|own\s+your\s+own\s+(?:business|practice)'
    r'|network\s+marketing'
    r'|multi[\s-]?level\s+marketing'
    r'|\bmlm\b'
    r'|(?:life|health)\s+insurance\s+(?:sales\s+)?agent'  # classic MLM disguised as "Financial Analyst"
    r'|insurance\s+sales\s+representative'
    r'|independent\s+(?:insurance\s+)?agent\s+(?:opportunity|position)'
    r'|recruit\s+(?:and\s+)?train\s+(?:your\s+own\s+)?(?:team|agents)'
    r'|make\s+\$[\d,]+\s*(?:per\s+(?:week|day)|\/(?:wk|day))\s+(?:from\s+home|working)',
    re.IGNORECASE,
)

def _filter_scams(jobs: list[JobPost]) -> list[JobPost]:
    kept, removed = [], 0
    for job in jobs:
        desc = (job.description or "") + " " + job.title
        if _SCAM_RE.search(desc):
            removed += 1
            logger.debug("Scam-filtered: %s @ %s", job.title, job.company)
        else:
            kept.append(job)
    if removed:
        print(f"[discovery] Filtered out {removed} likely-scam job(s).")
    return kept


async def discover_jobs() -> list[JobPost]:
    """
    1. Scrape all roles from all job boards via jobspy.
    2. Supplement with fallback scraper if needed.
    3. Deduplicate against seen_jobs table.
    4. Return up to JOBS_PER_DAY net-new jobs, sorted by recency.
    """
    hours = _get_hours_since_last_run()
    print(f"[discovery] Searching jobs posted in the last {hours}h (since last run).")

    logger.info("Starting job discovery for %d target roles...", len(config.TARGET_ROLES))

    # Primary scrape
    raw_jobs = await jobspy_scraper.scrape_all_roles(hours_old=hours)
    logger.info("jobspy returned %d raw postings", len(raw_jobs))

    # Handshake (optional, enabled via USE_HANDSHAKE=true in .env)
    if config.USE_HANDSHAKE:
        try:
            hs_jobs = await asyncio.wait_for(handshake_scraper.scrape_handshake(), timeout=180)
            logger.info("Handshake returned %d postings", len(hs_jobs))
            raw_jobs.extend(hs_jobs)
        except asyncio.TimeoutError:
            print("[Handshake] Login timed out — skipping Handshake this run.")
        except Exception as exc:
            logger.warning("Handshake scrape failed, skipping: %s", exc)

    # Fallback if primary is thin
    if len(raw_jobs) < config.JOBS_PER_DAY:
        logger.info("jobspy returned fewer than %d results, running fallback scraper...", config.JOBS_PER_DAY)
        fallback_jobs = await fallback_scraper.scrape_fallback_all_roles(
            needed=config.JOBS_PER_DAY,
            already_found=len(raw_jobs),
        )
        logger.info("Fallback scraper returned %d additional postings", len(fallback_jobs))
        raw_jobs.extend(fallback_jobs)

    # Filter out jobs requiring 5+ years experience
    raw_jobs = _filter_overqualified(raw_jobs)

    # Filter out obvious scam / MLM postings
    raw_jobs = _filter_scams(raw_jobs)

    # Deduplicate against all previously seen jobs
    new_jobs = await deduplicator.filter_new_jobs(raw_jobs)
    logger.info("%d net-new jobs after deduplication (from %d raw)", len(new_jobs), len(raw_jobs))

    new_jobs = new_jobs[:config.JOBS_PER_DAY]
    return new_jobs
