"""The plain-language report for the business owner, as HTML (prints cleanly to PDF) and Markdown."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from automation_finder.opportunities import Opportunity
from automation_finder.pipeline import Analysis
from automation_finder.propose import Proposal

TEMPLATES = Path(__file__).parent / "templates"
EASE_WORDS = {3: "easy to set up", 2: "moderate to set up", 1: "harder to set up"}
SOURCE_NAMES = {
    "email": "email records",
    "ticket": "helpdesk tickets",
    "calendar": "calendar entries",
    "activity": "activity log entries",
}


def _context(analysis: Analysis, proposals: list[Proposal], business: str, top_n: int) -> dict[str, object]:
    by_id = {p.opportunity: p for p in proposals}
    pairs: list[tuple[Opportunity, Proposal]] = [(o, by_id[o.id]) for o in analysis.opportunities if o.id in by_id]
    top, rest = pairs[:top_n], pairs[top_n:]
    counts = Counter(e.source for e in analysis.events)
    sources = ", ".join(f"{n} {SOURCE_NAMES.get(s, s)}" for s, n in counts.most_common())
    return {
        "business": business,
        "summary": analysis.summary(),
        "sources": sources,
        "opps": analysis.opportunities,
        "top": top,
        "rest": rest,
        "top_hours": sum(o.hours_per_month for o, _ in top),
        "top_saved": sum(o.hours_saved_per_month for o, _ in top),
        "ease_words": EASE_WORDS,
    }


def render_html(
    analysis: Analysis, proposals: list[Proposal], business: str = "your business", top_n: int = 5
) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("report.html").render(**_context(analysis, proposals, business, top_n))


def render_markdown(
    analysis: Analysis, proposals: list[Proposal], business: str = "your business", top_n: int = 5
) -> str:
    c = _context(analysis, proposals, business, top_n)
    s = analysis.summary()
    top: list[tuple[Opportunity, Proposal]] = c["top"]  # type: ignore[assignment]
    rest: list[tuple[Opportunity, Proposal]] = c["rest"]  # type: ignore[assignment]
    top_hours, top_saved = float(c["top_hours"]), float(c["top_saved"])  # type: ignore[arg-type]
    months = float(s["months"])  # type: ignore[arg-type]
    lines = [
        f"# Where {business} loses time",
        "",
        f"Based on {s['events']:,} records from {s['first']} to {s['last']} ({months:.1f} months): {c['sources']}.",
        "",
        f"- **{len(analysis.opportunities)}** repeated tasks found",
        f"- **{top_hours:.0f} hours a month** spent on the top {len(top)}",
        f"- **{top_saved:.0f} hours a month** that automation could give back",
        "",
        "> These hours are estimates: how often it happens (counted from your records) times minutes per task",
        "> (an assumption you can change). The minutes used are listed with each item.",
        "",
        f"## The top {len(top)} opportunities",
    ]
    for i, (o, p) in enumerate(top, 1):
        lines += [
            "",
            f"### {i}. {p.title}",
            "",
            f"**About {o.hours_per_month:.0f} h a month now, saves about {o.hours_saved_per_month:.1f} h a month** "
            f"| {EASE_WORDS[o.ease]} | {p.risk} risk",
            "",
            f"**What happens today:** {p.today}",
            "",
            f"**What starts it:** {p.trigger}",
            "",
            "**Steps the automation takes:**",
            *[f"{n}. {step}" for n, step in enumerate(p.steps, 1)],
            "",
            "**Where AI helps:** " + ("; ".join(p.ai_help) if p.ai_help else "not needed, simple rules are enough"),
            "",
            "**Where a person still decides:** "
            + ("; ".join(p.human_approval) if p.human_approval else "nothing to approve; the person gets a summary"),
            "",
            f"**Why this risk level:** {p.risk_reason.rstrip('.')}.",
            "",
            f"**How the hours were worked out:** {o.occurrences_per_month:.0f} times a month x "
            f"{o.minutes_per_task:.0f} minutes = {o.hours_per_month:.1f} hours; an automation like this usually "
            f"removes about {o.automation_share * 100:.0f}% of that work.",
        ]
    if rest:
        lines += [
            "",
            "## Other repeated work we found",
            "",
            "| What | Who | Times a month | Hours a month |",
            "|---|---|---:|---:|",
        ]
        for o, p in rest:
            who = ", ".join(a.capitalize() for a in o.actors[:2])
            lines.append(f"| {p.today} | {who} | {o.occurrences_per_month:.0f} | {o.hours_per_month:.1f} |")
    lines.append("")
    return "\n".join(lines)
