#!/usr/bin/env python3
"""
job_agent — Personal job application automation tool.

Usage:
  python main.py                            Run the full daily pipeline
  python main.py --dry-run                  Discover + tailor + review only (no records written)
  python main.py --limit 10                 Process at most 10 jobs this session
  python main.py --roles "Data Analyst,..."  Override target roles
  python main.py --apply-url URL [URL ...]  Tailor + apply for manually found job URLs
  python main.py --status                   Show all tracked applications
  python main.py --update <job_id> <status> [notes]   Update post-application status
  python main.py --export                   Export applications to CSV
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import MASTER_RESUME_PATH, JOBS_PER_DAY, TARGET_ROLES
import config as cfg
from agents.orchestrator import run_daily_pipeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="job_agent: AI-assisted job application automation with human-in-the-loop review."
    )
    parser.add_argument("--dry-run", action="store_true",
        help="Run discovery, tailoring, and review steps, but skip actual form submission.")
    parser.add_argument("--limit", type=int, default=JOBS_PER_DAY,
        help=f"Maximum number of jobs to process this session (default: {JOBS_PER_DAY})")
    parser.add_argument("--roles", type=str, default=None,
        help="Comma-separated list of job roles to search for (overrides config.py TARGET_ROLES)")
    parser.add_argument("--verbose", action="store_true",
        help="Enable verbose logging output.")
    parser.add_argument("--status", action="store_true",
        help="Show a table of all tracked applications and exit.")
    parser.add_argument("--update", nargs="+", metavar=("JOB_ID", "STATUS"),
        help="Update post-application status. Usage: --update <job_id> <status> [notes]"
             " | Statuses: phone, interview, offer, rejected, ghosted, withdrawn")
    parser.add_argument("--export", action="store_true",
        help="Export all applications to data/applications.csv")
    parser.add_argument("--apply-url", nargs="+", metavar="URL",
        help="One or more job posting URLs to tailor and apply to manually.")
    return parser.parse_args()


def show_status():
    """Print a tracking table of all applications."""
    from rich.console import Console
    from rich.table import Table
    from core import database as db

    apps = asyncio.run(db.get_all_applications())

    console = Console()

    if not apps:
        console.print("\n[yellow]No applications tracked yet.[/yellow]\n")
        return

    STATUS_STYLE = {
        "applied":      "cyan",
        "phone_screen": "blue",
        "interview":    "magenta",
        "offer":        "bold green",
        "rejected":     "red",
        "ghosted":      "dim",
        "withdrawn":    "dim",
        "form_ready":   "yellow",
    }

    table = Table(title="Job Application Tracker", show_lines=True)
    table.add_column("ID (first 8)", style="dim", no_wrap=True)
    table.add_column("Title", max_width=28)
    table.add_column("Company", max_width=20)
    table.add_column("Applied", no_wrap=True)
    table.add_column("Status")
    table.add_column("URL", max_width=40, overflow="fold")
    table.add_column("Notes", max_width=28)

    for app in apps:
        job_id = app["id"][:8]
        applied = (app.get("applied_at") or "")[:10]
        status = app.get("status", "")
        style = STATUS_STYLE.get(status, "white")
        table.add_row(
            job_id,
            app.get("title", ""),
            app.get("company", ""),
            applied,
            f"[{style}]{status}[/{style}]",
            app.get("job_url", ""),
            app.get("notes") or "",
        )

    console.print()
    console.print(table)

    # Summary line
    from collections import Counter
    counts = Counter(a["status"] for a in apps)
    parts = []
    for s, n in sorted(counts.items()):
        style = STATUS_STYLE.get(s, "white")
        parts.append(f"[{style}]{n} {s}[/{style}]")
    console.print("  " + "  ·  ".join(parts) + "\n")


def export_csv():
    from core import database as db
    out = asyncio.run(db.export_applications_csv())
    print(f"Exported → {out}")


def update_status(args_update: list[str]):
    """Update a job's post-application status."""
    from core import database as db

    if len(args_update) < 2:
        print("Usage: --update <job_id_prefix> <status> [notes]")
        print("Statuses:", ", ".join(db.POST_APP_STATUSES.keys()))
        sys.exit(1)

    job_id_prefix, status_key, *notes_parts = args_update
    notes = " ".join(notes_parts)

    if status_key not in db.POST_APP_STATUSES:
        print(f"Unknown status '{status_key}'. Choose from: {', '.join(db.POST_APP_STATUSES.keys())}")
        sys.exit(1)

    status = db.POST_APP_STATUSES[status_key]

    # Look up full job_id by prefix
    async def _run():
        from core.database import DB_PATH
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db_conn:
            async with db_conn.execute(
                "SELECT id, title, company FROM jobs WHERE id LIKE ?",
                (f"{job_id_prefix}%",)
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            print(f"No job found with ID starting with '{job_id_prefix}'")
            sys.exit(1)
        if len(rows) > 1:
            print(f"Ambiguous ID prefix — matches {len(rows)} jobs. Use more characters.")
            sys.exit(1)
        job_id, title, company = rows[0]
        await db.update_application_status(job_id, status, notes)
        print(f"Updated: {title} @ {company}  →  {status}" + (f"  [{notes}]" if notes else ""))

    asyncio.run(_run())


def cleanup_outputs(days: int = 30) -> None:
    """Delete output folders older than `days` days, keeping applied ones."""
    import shutil
    import time
    from config import OUTPUTS_DIR, DB_PATH
    from core import database as db

    if not OUTPUTS_DIR.exists():
        return

    # Get job IDs that were actually applied to — never delete those
    applied_ids = set()
    try:
        apps = asyncio.run(db.get_all_applications())
        applied_ids = {a["id"] for a in apps}
    except Exception:
        pass

    cutoff = time.time() - days * 86400
    removed = 0
    for folder in OUTPUTS_DIR.iterdir():
        if not folder.is_dir():
            continue
        # Keep folder if any applied job ID matches the folder name
        if any(job_id[:6] in folder.name for job_id in applied_ids):
            continue
        if folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder)
            removed += 1

    if removed:
        print(f"[job_agent] Cleaned up {removed} old output folder(s) (>{days} days).")


def check_prerequisites():
    """Fail fast with clear messages before the pipeline starts."""
    errors = []

    if not cfg.GEMINI_API_KEY:
        errors.append(
            "GEMINI_API_KEY is not set. Add it to your .env file:\n"
            "  GEMINI_API_KEY=AIza..."
        )

    if not MASTER_RESUME_PATH.exists():
        errors.append(
            f"Master resume not found at: {MASTER_RESUME_PATH}\n"
            "  Copy the example file and fill in your content:\n"
            "    cp data/master_resume.example.json data/master_resume.json"
        )
    else:
        import json
        try:
            json.loads(MASTER_RESUME_PATH.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"data/master_resume.json is not valid JSON: {exc}")

    # Personal info must come from env vars
    missing_personal = [
        var for var, val in [
            ("PERSONAL_NAME", cfg.PERSONAL_NAME),
            ("PERSONAL_EMAIL", cfg.PERSONAL_EMAIL),
            ("PERSONAL_LINKEDIN", cfg.PERSONAL_LINKEDIN),
        ] if not val
    ]
    if missing_personal:
        errors.append(
            "Missing personal info in your .env file:\n"
            + "".join(f"  {v}=...\n" for v in missing_personal)
            + "  See .env.example for the full list."
        )

    if errors:
        print("\n[job_agent] Cannot start — please fix the following:\n")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}\n")
        sys.exit(1)


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Side commands — no pipeline needed
    if args.status:
        show_status()
        return

    if args.export:
        export_csv()
        return

    if args.update:
        update_status(args.update)
        return

    if args.apply_url:
        check_prerequisites()
        from agents.manual_job_agent import process_manual_jobs
        asyncio.run(process_manual_jobs(args.apply_url))
        return

    # Apply CLI overrides to config
    if args.roles:
        cfg.TARGET_ROLES = [r.strip() for r in args.roles.split(",")]
    if args.limit != JOBS_PER_DAY:
        cfg.JOBS_PER_DAY = args.limit

    check_prerequisites()
    cleanup_outputs(days=30)

    print(f"\n{'═'*50}")
    print("  job_agent — Daily Job Application Pipeline")
    print(f"{'═'*50}")
    print(f"  Target roles : {', '.join(cfg.TARGET_ROLES)}")
    print(f"  Max jobs     : {cfg.JOBS_PER_DAY}")
    print(f"  Mode         : {'DRY RUN (no records written)' if args.dry_run else 'LIVE'}")
    print(f"{'═'*50}\n")

    if not args.dry_run:
        confirm = input("Press Enter to start, or Ctrl+C to abort: ")

    asyncio.run(run_daily_pipeline(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
