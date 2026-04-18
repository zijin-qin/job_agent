"""
Textual TUI for human review checkpoints.

Checkpoint 1 — Job List Approval
Checkpoint 2 — Per-Job Resume + Cover Letter Review
"""
from __future__ import annotations

import webbrowser
from typing import Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label,
    Static, TabbedContent, TabPane, TextArea,
)

from core.models import JobPost


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint 1 — Job List Approval
# ─────────────────────────────────────────────────────────────────────────────

class JobListScreen(Screen):
    """Discovered job list. User toggles which jobs to process."""

    BINDINGS = [
        Binding("a", "approve", "Approve Selected"),
        Binding("space", "toggle_row", "Toggle"),
        Binding("o", "open_url", "Open in Browser"),
        Binding("q", "quit_all", "Quit"),
    ]

    CSS = """
    JobListScreen { layout: vertical; }
    #title {
        height: 3; content-align: center middle;
        background: $boost; color: $text; text-style: bold;
    }
    #stats { height: 2; content-align: center middle; color: $text-muted; }
    DataTable { height: 1fr; }
    #controls { height: 5; layout: horizontal; align: center middle; padding: 1; }
    Button { margin: 0 2; }
    """

    def __init__(self, jobs: list[JobPost]):
        super().__init__()
        self.jobs = jobs
        self.selected: set[int] = set(range(len(jobs)))

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"[bold]Checkpoint 1 — Job List Review[/bold]  |  {len(self.jobs)} jobs discovered",
            id="title",
        )
        yield Static("Space = toggle  |  A = approve selected  |  O = open in browser  |  Q = quit", id="stats")
        yield DataTable(id="job_table", cursor_type="row")
        yield Horizontal(
            Button("✓ Approve Selected", variant="success", id="btn_approve"),
            Button("✗ Quit", variant="error", id="btn_quit"),
            id="controls",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("✓", key="check")
        table.add_column("Title")
        table.add_column("Company")
        table.add_column("Location")
        table.add_column("Remote")
        table.add_column("Source")
        table.add_column("Date Posted")
        table.add_column("URL")
        for i, job in enumerate(self.jobs):
            check = "✓" if i in self.selected else " "
            table.add_row(
                check,
                job.title[:45],
                job.company[:30],
                (job.location or "")[:25],
                "✓" if job.is_remote else "",
                job.source,
                (job.date_posted or "")[:10],
                job.job_url or "",
                key=str(i),
            )

    def action_toggle_row(self) -> None:
        idx = self.query_one(DataTable).cursor_row
        self.selected.discard(idx) if idx in self.selected else self.selected.add(idx)
        self._refresh_check(idx)

    def _refresh_check(self, idx: int) -> None:
        self.query_one(DataTable).update_cell(str(idx), "check", "✓" if idx in self.selected else " ")

    def action_open_url(self) -> None:
        table = self.query_one(DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self.jobs):
            url = self.jobs[idx].job_url or self.jobs[idx].application_url
            if url:
                webbrowser.open(url)

    def action_approve(self) -> None:
        self.app.exit(("approved", [self.jobs[i] for i in sorted(self.selected)]))

    def action_quit_all(self) -> None:
        self.app.exit(("quit", []))

    @on(Button.Pressed, "#btn_approve")
    def on_approve(self): self.action_approve()

    @on(Button.Pressed, "#btn_quit")
    def on_quit(self): self.action_quit_all()

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        self.selected.discard(idx) if idx in self.selected else self.selected.add(idx)
        self._refresh_check(idx)


class JobListApp(App):
    def __init__(self, jobs: list[JobPost]):
        super().__init__()
        self._jobs = jobs

    def on_mount(self) -> None:
        self.push_screen(JobListScreen(self._jobs))


async def checkpoint_1_job_list(jobs: list[JobPost]) -> list[JobPost]:
    """Shows the job list TUI, returns the user-approved subset."""
    result = await JobListApp(jobs).run_async()
    if result and result[0] == "approved":
        return result[1]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint 2 — Per-Job Resume + Cover Letter Review
# ─────────────────────────────────────────────────────────────────────────────

class JobReviewScreen(Screen):
    """Tabbed review: Tab 1 = tailored resume + changes summary, Tab 2 = cover letter editor."""

    BINDINGS = [
        Binding("a", "approve", "Approve"),
        Binding("s", "skip", "Skip"),
        Binding("r", "retailor", "Re-tailor"),
        Binding("q", "quit_all", "Quit All"),
    ]

    CSS = """
    JobReviewScreen { layout: vertical; }
    #header_bar {
        height: 3; background: $boost; content-align: center middle;
        text-style: bold; color: $text;
    }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1; }
    .changes_box {
        background: $surface; color: $warning; padding: 1;
        border: solid $warning; margin-bottom: 1; height: auto;
    }
    .resume_text { height: auto; }
    #controls { height: 5; layout: horizontal; align: center middle; padding: 1; }
    Button { margin: 0 1; }
    .cl_label { color: $text-muted; margin-top: 1; margin-bottom: 1; text-style: italic; }
    TextArea { height: 10; margin-bottom: 1; }
    """

    def __init__(self, job: JobPost, tailored_resume: dict, cover_letter: dict):
        super().__init__()
        self.job = job
        self.tailored_resume = tailored_resume
        self.cover_letter = cover_letter

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"[bold]Checkpoint 2:[/bold]  {self.job.title} @ {self.job.company}",
            id="header_bar",
        )
        meta = self.tailored_resume.get("_tailoring_metadata", {})
        changes = meta.get("changes_summary", "No changes summary.")
        paragraphs = self.cover_letter.get("paragraphs", [])

        with TabbedContent("Resume & Changes", "Cover Letter"):
            with TabPane("Resume & Changes"):
                with ScrollableContainer():
                    yield Static(
                        f"[bold yellow]What changed:[/bold yellow]\n{changes}",
                        classes="changes_box",
                    )
                    yield Static(self._format_resume(), classes="resume_text", markup=False)

            with TabPane("Cover Letter"):
                with ScrollableContainer():
                    if not paragraphs:
                        yield Static(
                            "[dim]Cover letter generation failed — you can write one manually.[/dim]"
                        )
                        yield TextArea("", id="cl_para_0")
                    else:
                        yield Static(
                            "[dim]Edit any paragraph below, then Approve.[/dim]",
                            classes="cl_label",
                        )
                        for i, para in enumerate(paragraphs):
                            yield Label(f"Paragraph {i + 1}:", classes="cl_label")
                            yield TextArea(para, id=f"cl_para_{i}")

        yield Horizontal(
            Button("✓ Approve", variant="success", id="btn_approve"),
            Button("↻ Re-tailor", variant="warning", id="btn_retailor"),
            Button("→ Skip", variant="default", id="btn_skip"),
            Button("✗ Quit All", variant="error", id="btn_quit"),
            id="controls",
        )
        yield Footer()

    def _format_resume(self) -> str:
        r = self.tailored_resume
        lines = []
        personal = r.get("personal", {})
        lines.append(personal.get("name", ""))
        lines.append(
            f"{personal.get('email', '')}  |  "
            f"{personal.get('phone', '')}  |  "
            f"{personal.get('location', '')}"
        )
        lines.append("")

        if r.get("summary"):
            lines += ["SUMMARY", r["summary"], ""]

        if r.get("education"):
            lines.append("EDUCATION")
            for edu in r["education"]:
                lines.append(
                    f"  {edu.get('institution', '')} — "
                    f"{edu.get('degree', '')} ({edu.get('graduation_year', '')})"
                )
            lines.append("")

        if r.get("experience"):
            lines.append("EXPERIENCE")
            for exp in r["experience"]:
                lines.append(
                    f"  {exp.get('title', '')} @ {exp.get('company', '')} "
                    f"({exp.get('start_date', '')} – {exp.get('end_date', 'Present')})"
                )
                for b in exp.get("bullets", []):
                    lines.append(f"    • {b}")
            lines.append("")

        if r.get("projects"):
            lines.append("PROJECTS")
            for proj in r["projects"]:
                lines.append(
                    f"  {proj.get('name', '')}  [{', '.join(proj.get('tech_stack', []))}]"
                )
                for b in proj.get("bullets", []):
                    lines.append(f"    • {b}")
            lines.append("")

        skills = r.get("skills", {})
        if skills:
            lines.append("SKILLS")
            for category, items in skills.items():
                if isinstance(items, list):
                    lines.append(f"  {category}: {', '.join(items)}")

        return "\n".join(lines)

    def _collect_cover_letter_edits(self) -> list[str]:
        """Return the current text of all cover letter paragraph TextAreas."""
        paragraphs = self.cover_letter.get("paragraphs", [])
        count = max(len(paragraphs), 1)
        result = []
        for i in range(count):
            try:
                text = self.query_one(f"#cl_para_{i}", TextArea).text
                if text.strip():
                    result.append(text.strip())
            except Exception:
                pass
        return result

    def action_approve(self) -> None:
        edited = self._collect_cover_letter_edits()
        self.app.exit(("approved", edited))

    def action_skip(self) -> None:
        self.app.exit(("skip", []))

    def action_retailor(self) -> None:
        self.app.exit(("retailor", []))

    def action_quit_all(self) -> None:
        self.app.exit(("quit", []))

    @on(Button.Pressed, "#btn_approve")
    def on_approve(self): self.action_approve()

    @on(Button.Pressed, "#btn_skip")
    def on_skip(self): self.action_skip()

    @on(Button.Pressed, "#btn_retailor")
    def on_retailor(self): self.action_retailor()

    @on(Button.Pressed, "#btn_quit")
    def on_quit(self): self.action_quit_all()


class JobReviewApp(App):
    def __init__(self, job: JobPost, tailored_resume: dict, cover_letter: dict):
        super().__init__()
        self._job = job
        self._tailored = tailored_resume
        self._cover_letter = cover_letter

    def on_mount(self) -> None:
        self.push_screen(JobReviewScreen(self._job, self._tailored, self._cover_letter))


async def checkpoint_2_per_job(
    job: JobPost,
    tailored_resume: dict,
    cover_letter: dict,
) -> tuple[str, list[str]]:
    """
    Per-job review TUI.
    Returns (action, edited_cover_letter_paragraphs).
    action: "approved" | "skip" | "retailor" | "quit"
    """
    result = await JobReviewApp(job, tailored_resume, cover_letter).run_async()
    if result:
        return result[0], result[1]
    return "skip", []
