from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# --- Paths ---
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = DATA_DIR / "outputs"
MASTER_RESUME_PATH = DATA_DIR / "master_resume.json"
DB_PATH = DATA_DIR / "job_agent.db"
RESUME_TEMPLATE_PATH = BASE_DIR / "core" / "resume_template.html"
COVER_LETTER_TEMPLATE_PATH = BASE_DIR / "core" / "cover_letter_template.html"

# --- API Keys ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROXY_URL = os.getenv("PROXY_URL")  # Optional

# --- Personal Info (loaded from .env so master_resume.json stays PII-free) ---
PERSONAL_NAME = os.getenv("PERSONAL_NAME", "")
PERSONAL_EMAIL = os.getenv("PERSONAL_EMAIL", "")
PERSONAL_PHONE = os.getenv("PERSONAL_PHONE", "")
PERSONAL_LINKEDIN = os.getenv("PERSONAL_LINKEDIN", "")
PERSONAL_GITHUB = os.getenv("PERSONAL_GITHUB", "")
PERSONAL_LOCATION = os.getenv("PERSONAL_LOCATION", "")
PERSONAL_CITIZENSHIP = os.getenv("PERSONAL_CITIZENSHIP", "")

# --- Search Parameters ---
TARGET_ROLES = [
    "analyst",
    "data scientist",
    "data engineer",
    "machine learning engineer",
    "AI engineer",
    "software engineer",
    "solutions engineer",
    "customer success",
    "implementation specialist",
    "technical support engineer",
    "developer advocate",
]
JOBS_PER_DAY = 20
HOURS_OLD = 24          # Only fetch jobs posted in the last 24 hours (run once per day)
MAX_HOURS_OLD = 168     # Cap lookback at 1 week even after a long gap — older postings are stale
RESULTS_PER_ROLE = 15   # Per role per scrape run (deduped down to JOBS_PER_DAY total)
LOCATION = "United States"
REMOTE_ONLY = False     # Set True to filter to remote-only jobs

# --- Job Sources ---
SCRAPE_SITES = ["linkedin", "indeed"]
USE_HANDSHAKE = os.getenv("USE_HANDSHAKE", "false").lower() == "true"

# --- Gemini Models ---
# Pro for resume tailoring: higher stakes, strict no-fabrication constraint,
# benefits from Pro's stronger instruction-following and reasoning.
# 27s latency is acceptable — tailoring runs in background during the review loop.
GEMINI_MODEL_TAILORING = "gemini-2.5-flash"
GEMINI_MODEL_EXTRACTION = "gemini-2.5-flash-lite"

GEMINI_MAX_TOKENS = 8192
