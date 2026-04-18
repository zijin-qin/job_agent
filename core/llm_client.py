"""Thin wrapper around the Google Gemini SDK. All LLM calls go through here."""
import json
import asyncio
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL_TAILORING, GEMINI_MODEL_EXTRACTION, GEMINI_MAX_TOKENS


_client = genai.Client(api_key=GEMINI_API_KEY)

COVER_LETTER_SYSTEM = """\
You are a professional cover letter writer. Write a concise, compelling cover letter based on \
the candidate's tailored resume and the job description.

RULES:
1. Write exactly 3-4 paragraphs (no summary header, no salutation — just the body paragraphs).
2. Opening paragraph: Express genuine, specific interest in the role and company. Reference \
   something concrete about the company/role — not generic enthusiasm.
3. Middle 1-2 paragraphs: Highlight 2-3 specific experiences from the resume that directly \
   match the job requirements. Reference actual project names, technologies, or measurable outcomes.
4. Closing paragraph: Short call to action expressing enthusiasm to discuss further.
5. DO NOT use hollow filler phrases ("I am excited to apply", "I believe I am a great fit", \
   "passionate about", "leverage my skills").
6. Keep total length to 280-340 words across all paragraphs.
7. Output ONLY valid JSON — no markdown fences."""

JOB_EXTRACTION_SYSTEM = """\
You are an expert at extracting structured job posting information from web page content.
Given the text content of a job posting page, extract the key details.
Return valid JSON with EXACTLY these fields:
{
  "title": "<job title string>",
  "company": "<company name string>",
  "location": "<location string or null>",
  "is_remote": <true|false>,
  "description": "<full job description text — preserve as much detail as possible>",
  "application_url": "<direct application URL if different from page URL, or null>"
}
If you cannot determine a field confidently, use null."""

# ── System prompts ──────────────────────────────────────────────────────────

TAILORING_SYSTEM = """\
You are a professional resume tailoring assistant. Your ONLY job is to help a job seeker \
present their existing experience in the best possible light for a specific role.

ABSOLUTE RULES — violating any of these is unacceptable:
1. You MUST NOT invent, fabricate, or imply any experience, skill, tool, credential, \
   metric, or accomplishment that is not explicitly present in the master resume provided.
2. You MAY reorder sections, bullet points, or skills to emphasize what is most relevant \
   to the job description.
3. You MAY rephrase existing bullets to use terminology from the job description, \
   as long as the underlying claim remains factually identical.
4. You MUST select the 4 most relevant projects for the role and omit the rest. \
   Each project must have at most 2 bullets. Keep bullets punchy and specific — \
   do NOT truncate technical details, action verbs, or context. Never add anything new.
5. You MUST leave the summary field as an empty string (""). Never write a summary. \
   The resume must fit on one page and a summary wastes critical space.
6. You MUST output valid JSON matching the exact schema of the input master resume, \
   plus a _tailoring_metadata field.

If the job requires skills or experience the candidate genuinely does not have, \
do NOT compensate by inflating what they do have. Simply emphasize the closest \
real match and note the gap in changes_summary."""



# ── Core call ────────────────────────────────────────────────────────────────

def _generate_json(system: str, user: str, model: str, retries: int = 3) -> dict:
    """
    Single synchronous Gemini call with enforced JSON output mode.
    Retries on 429 rate limit errors with the suggested delay.
    """
    for attempt in range(retries):
        try:
            response = _client.models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=GEMINI_MAX_TOKENS,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                if attempt < retries - 1:
                    wait = 30 * (attempt + 1)
                    print(f"[llm] Gemini unavailable — retrying in {wait}s...")
                    time.sleep(wait)
                    continue
            raise


# ── Public API ────────────────────────────────────────────────────────────────

def tailor_resume(master_resume: dict, job_description: str, job_title: str, company: str, job_id: str) -> dict:
    """
    Call Gemini to tailor the master resume for a specific job.
    Returns the tailored resume as a dict (same schema as master + _tailoring_metadata).
    Runs synchronously — wrap in asyncio.to_thread if calling from async code.
    """
    prompt = f"""\
Job Title: {job_title}
Company: {company}
Job Description:
{job_description}

Master Resume (JSON):
{json.dumps(master_resume, indent=2)}

Tailor the resume for this specific role. Return ONLY valid JSON with:
- All fields from the master resume (reordered/rephrased as appropriate)
- A _tailoring_metadata object with:
  - job_id: "{job_id}"
  - job_title: the job title above
  - company: the company above
  - changes_summary: a brief plain-English summary of what was changed and why
  - tailored_at: current UTC ISO8601 timestamp

Remember: do NOT add anything that is not in the master resume."""

    return _generate_json(TAILORING_SYSTEM, prompt, GEMINI_MODEL_TAILORING)


async def tailor_resume_async(
    master_resume: dict, job_description: str, job_title: str, company: str, job_id: str
) -> dict:
    return await asyncio.to_thread(
        tailor_resume, master_resume, job_description, job_title, company, job_id
    )


def generate_cover_letter(
    tailored_resume: dict,
    personal: dict,
    job_description: str,
    job_title: str,
    company: str,
    job_id: str,
) -> dict:
    """Call Gemini to generate a cover letter. Returns dict with 'paragraphs' list."""
    resume_clean = {k: v for k, v in tailored_resume.items() if not k.startswith("_")}
    prompt = f"""\
Job Title: {job_title}
Company: {company}
Job Description:
{job_description}

Candidate:
Name: {personal.get('name', '')}
Location: {personal.get('location', '')}
Email: {personal.get('email', '')}
LinkedIn: {personal.get('linkedin', '')}
GitHub: {personal.get('github', '')}

Tailored Resume (JSON — use specific projects/experiences from here):
{json.dumps(resume_clean, indent=2)}

Write the cover letter body paragraphs. Return ONLY valid JSON:
{{
  "paragraphs": ["<paragraph 1>", "<paragraph 2>", "<paragraph 3 or 4 if needed>"],
  "_cover_letter_metadata": {{
    "job_id": "{job_id}",
    "job_title": "{job_title}",
    "company": "{company}",
    "generated_at": "<UTC ISO8601 timestamp>"
  }}
}}"""
    return _generate_json(COVER_LETTER_SYSTEM, prompt, GEMINI_MODEL_TAILORING)


def extract_job_info_from_html(page_text: str, url: str) -> dict:
    """Call Gemini to extract structured job info from raw page text."""
    prompt = f"""\
Page URL: {url}

Page text content:
{page_text[:15000]}

Extract the job posting details from this page and return valid JSON."""
    return _generate_json(JOB_EXTRACTION_SYSTEM, prompt, GEMINI_MODEL_EXTRACTION)


async def generate_cover_letter_async(
    tailored_resume: dict,
    personal: dict,
    job_description: str,
    job_title: str,
    company: str,
    job_id: str,
) -> dict:
    return await asyncio.to_thread(
        generate_cover_letter,
        tailored_resume, personal, job_description, job_title, company, job_id,
    )


async def extract_job_info_from_html_async(page_text: str, url: str) -> dict:
    return await asyncio.to_thread(extract_job_info_from_html, page_text, url)
