# job_agent

An AI-assisted job application automation tool with human-in-the-loop review. Discovers job postings from multiple job boards, uses Google Gemini to tailor your resume and generate a cover letter for each job, lets you review everything before applying, then tracks your applications in a local database.

## How it works

```
Discovery → [CP1: approve job list] → Per-job tailoring + cover letter
         → [CP2: review & edit per job] → PDF generation → apply → record
```

- **Discovery**: Scrapes LinkedIn, Indeed, and ZipRecruiter via [python-jobspy](https://github.com/Bunsly/JobSpy), with optional Handshake and fallback scrapers for additional boards (Wellfound, Greenhouse, Lever, Workday).
- **Checkpoint 1**: Textual TUI to approve/skip jobs before any LLM calls.
- **Tailoring**: Gemini rewrites your resume bullets and cover letter for each approved job (no fabrication — only restructures what you already have).
- **Checkpoint 2**: Inline TUI editor to review and adjust the tailored resume and cover letter before generating PDFs.
- **PDF generation**: Renders via Jinja2 + Playwright/Chromium.
- **Tracking**: SQLite database + CSV export tracks every application through the full lifecycle.

## Prerequisites

- Python 3.11+
- [Playwright browsers](https://playwright.dev/python/docs/intro): `playwright install chromium`
- A [Google Gemini API key](https://aistudio.google.com/app/apikey) (free tier works)

## Setup

```bash
git clone <repo-url>
cd job_agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

**Configure your environment:**

```bash
cp .env.example .env
# Edit .env — fill in your GEMINI_API_KEY and personal info
```

**Set up your master resume:**

```bash
cp data/master_resume.example.json data/master_resume.json
# Edit data/master_resume.json — fill in your actual experience, projects, and skills
# (personal info like name/email/phone is injected from .env at runtime, not stored here)
```

## Usage

```bash
# Run the full daily pipeline
python main.py

# Discover + tailor + review only — no applications recorded
python main.py --dry-run

# Process at most 5 jobs this session
python main.py --limit 5

# Override the target roles for this run
python main.py --roles "Data Analyst, Business Analyst"

# Tailor and apply for a specific job URL you found manually
python main.py --apply-url https://jobs.example.com/posting/123

# Show all tracked applications
python main.py --status

# Update post-application status
python main.py --update <job_id_prefix> interview "Called back after 2 days"

# Export applications to CSV
python main.py --export
```

**Post-application statuses:** `phone`, `interview`, `offer`, `rejected`, `ghosted`, `withdrawn`

## Project structure

```
job_agent/
├── agents/               # Pipeline agents (discovery, tailoring, cover letter, orchestrator)
├── core/                 # Business logic (LLM client, DB, PDF builder, models)
├── scrapers/             # Job board scrapers (jobspy, Handshake, fallback)
├── review/               # Textual TUI for review checkpoints
├── tests/                # Unit tests
├── data/
│   └── master_resume.example.json   # Template — copy to master_resume.json
├── config.py             # Search parameters and model config
├── main.py               # CLI entry point
├── .env.example          # Template for secrets and personal info
└── requirements.txt
```

## Configuration

Edit `config.py` to change:
- `TARGET_ROLES` — job titles to search for
- `LOCATION` / `REMOTE_ONLY` — geographic filter
- `JOBS_PER_DAY` / `RESULTS_PER_ROLE` — scrape volume
- `SCRAPE_SITES` — which job boards to hit
- `GEMINI_MODEL_TAILORING` / `GEMINI_MODEL_EXTRACTION` — Gemini model selection

Set `USE_HANDSHAKE=true` in `.env` to enable the Handshake scraper (requires interactive SSO login on first run; session is cached for subsequent runs).

## Data privacy

All personal information (name, email, phone, LinkedIn, GitHub, location) is stored only in your local `.env` file and is never committed to version control. Your master resume (`data/master_resume.json`), application database, generated PDFs, and application history are all gitignored.
