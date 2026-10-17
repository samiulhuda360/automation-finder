"""Turns an opportunity into an automation proposal.

The rule-based writer always runs and fills every field from the evidence. With a model available, the model
rewrites the proposal from the same facts (it sees masked examples only, never raw messages). Its answer is
checked against the schema, and two safety rules always hold: the risk level is never lower than the rules say,
and anything rated medium or high keeps a person approving before records are written.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from automation_finder.events import num, seq
from automation_finder.llm import CacheMiss, ChatClient, RateLimited
from automation_finder.opportunities import KIND_NAMES, Opportunity

TRIGGERS = ("email", "ticket", "app_event", "schedule")
RISKS = ("low", "medium", "high")


@dataclass
class Proposal:
    opportunity: str
    title: str
    today: str  # what happens now, in plain words
    trigger_type: str
    trigger: str
    steps: list[str]
    ai_help: list[str]
    human_approval: list[str]
    needs_approval: bool
    risk: str
    risk_reason: str
    systems: list[str]
    hours_saved_per_month: float
    source: str = "rules"  # rules | model
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _name(key: str) -> str:
    return key.capitalize()


def _hour(h: float) -> str:
    whole = int(h)
    minutes = int(round((h - whole) * 60 / 15) * 15) % 60
    return f"{whole:02d}:{minutes:02d}"


def _quote(text: str) -> str:
    return f"\u201c{text}\u201d"


def today_text(o: Opportunity) -> str:
    who = _name(o.actors[0]) if o.actors else "Someone"
    per_month = round(o.occurrences_per_month)
    ex = _quote(o.examples[0]) if o.examples else "the same item"
    if o.kind == "copy":
        source = {"email": "an email", "ticket": "a helpdesk ticket"}.get(o.trigger, f"an entry in {o.systems[0]}")
        return (
            f"{who} receives {source} like {ex} and then types it into {o.systems[-1]} "
            f"({o.target_action}) by hand, about {per_month} times a month."
        )
    if o.kind == "periodic":
        return (
            f"{who} does the same routine {o.anchor} around {_hour(num(o.evidence.get('hour'), 9))}: "
            f"{', '.join(_quote(e) for e in o.examples[:3])}. "
            + ("That is once a month." if per_month <= 1 else f"That is about {per_month} tasks a month.")
        )
    if o.kind == "handoff":
        return handoff_story(o) + f" This happens about {per_month} times a month."
    return (
        f"{who} answers the same kind of request again and again, such as {ex}: "
        f"about {per_month} a month, worded differently each time."
    )


def _step_words(step: str) -> str:
    """'jobs:complete job' -> 'complete job in jobs'; 'email' -> 'send an email'."""
    if ":" in step:
        system, action = step.split(":", 1)
        return f"{action} in {system}"
    return {"email": "send an email", "helpdesk": "update the ticket"}.get(step, step)


def _people(entry: dict[str, Any]) -> str:
    people = [_name(p) for p in entry.get("people", [])]
    count = int(entry.get("count", len(people)))
    if count > 2:
        return f"one of {count} people ({', '.join(people[:2])} and others)"
    return " or ".join(people)


def handoff_story(o: Opportunity) -> str:
    route = seq(o.evidence.get("route"))
    parts = []
    for r in route:
        if str(r["step"]) == "email" and r.get("example"):
            parts.append(f"{_people(r)} emails {_quote(str(r['example']))}")
        else:
            parts.append(f"{_people(r)} does '{_step_words(str(r['step']))}'")
    if not parts:
        return "Work passes between people before it is recorded."
    return "First " + "; then ".join(parts) + "."


def rules_proposal(o: Opportunity) -> Proposal:
    who = _name(o.actors[0]) if o.actors else "the team"
    target = o.systems[-1]
    ex = _quote(o.examples[0]) if o.examples else ""
    approval = o.risk in ("medium", "high")
    if o.kind == "copy":
        thing = {"email": "email", "ticket": "ticket"}.get(o.trigger, "record")
        title = f"Create the {target} record from each {thing} automatically"
        trigger = {
            "email": f"A new email like {ex} arrives",
            "ticket": f"A new helpdesk ticket like {ex} is created",
        }.get(o.trigger, f"{o.systems[0]} records a new {ex}")
        steps = [
            f"Pick out only the {thing}s that match this pattern (sender and subject)",
            f"Extract the details {who} currently re-types for '{o.target_action}'",
            f"Create the '{o.target_action}' record in {target} through its API",
            f"Link the new record back to the original {thing} and log it",
        ]
        ai = [
            f"Read the {thing} and extract the fields, with a confidence score",
            "Send anything unclear or unusual to a person instead of guessing",
        ]
        if approval:
            steps.insert(2, f"Show {who} the drafted record to approve (one click) before it is saved")
    elif o.kind == "periodic":
        hour = _hour(num(o.evidence.get("hour"), 9))
        title = f"Run {who}'s {o.period} routine automatically"
        trigger = f"A schedule: {o.anchor} at {hour}"
        steps = [
            f"Start {o.anchor} at {hour}",
            f"Collect what the routine needs from {', '.join(o.systems)}",
            f"Do the repeated part automatically: {'; '.join(_quote(e) for e in o.examples[:3])}",
            f"Send {who} a short summary of what was done and anything that needs a person",
        ]
        ai = ["Write the message or report text from the collected data"]
    elif o.kind == "handoff":
        route = seq(o.evidence.get("route"))
        first = _step_words(str(route[0]["step"])) if route else o.systems[0]
        last = route[-1] if route else {"step": target, "people": []}
        last_person = _name(last["people"][0]) if last.get("people") else "the person"
        ref = str(o.evidence.get("ref_type", ""))
        if o.approval_seen:
            title = f"Route each {ref} request through approval and into {target} automatically"
        else:
            title = f"Create the {target} record as soon as someone does '{first}'"
        trigger = {
            "email": "A request email arrives (the first step today)",
            "ticket": "A helpdesk ticket is created",
        }.get(o.trigger, f"{o.systems[0]} reports '{first}' (a webhook)")
        steps = [
            "Capture the item and its reference number",
            "Check the details are complete (reference, amounts, customer) and fill in what is missing",
        ]
        if o.approval_seen:
            steps.append("Send the approver a message with Approve / Decline, then wait for the answer")
        steps += [
            f"Create the record in {target} automatically "
            f"(today {last_person} does '{_step_words(str(last['step']))}' by hand)",
            "Tell the person who started it what happened",
        ]
        ai = ["Pre-fill the details from the message or job notes", "Flag anything that breaks the usual pattern"]
    else:
        title = "Recognise these requests and draft the response"
        trigger = {"email": f"A new email like {ex} arrives"}.get(o.trigger, f"A new helpdesk ticket like {ex}")
        steps = [
            "Recognise the request, however it is worded",
            "Look up the related booking or record",
            "Draft the reply and the change for a person to approve",
            "Apply the change and send the reply once approved",
        ]
        ai = ["Classify requests that are worded differently", "Draft the reply in the business's tone"]
        approval = True
    if o.kind == "handoff" and o.approval_seen:
        human = ["The approver still decides Approve or Decline, as today; nothing is ordered without it"]
    elif o.kind == "handoff":
        human = [f"{last_person} checks each drafted record before it is saved"] if approval else []
    else:
        human = [f"{who} approves each item before anything is saved or sent"] if approval else []
    return Proposal(
        opportunity=o.id,
        title=title,
        today=today_text(o),
        trigger_type=o.trigger,
        trigger=trigger,
        steps=steps,
        ai_help=ai,
        human_approval=human,
        needs_approval=approval,
        risk=o.risk,
        risk_reason=o.risk_reason,
        systems=o.systems,
        hours_saved_per_month=o.hours_saved_per_month,
    )


SYSTEM_PROMPT = """You design small, safe workflow automations for a small business owner.
You get the facts about one piece of repeated manual work, found in the business's activity data.
Answer with one JSON object with exactly these keys:
  title (short), trigger_type (one of: email, ticket, app_event, schedule), trigger (one sentence),
  steps (3 to 6 short imperative steps), ai_help (where an AI model helps; may be empty),
  human_approval (where a person must approve; may be empty), needs_approval (true/false),
  risk (low, medium or high: what goes wrong if the automation makes a mistake), risk_reason (one sentence),
  systems (the business systems the workflow reads or writes, lower-case names as given).
Use plain words a business owner understands. Do not invent systems that are not in the facts unless a step
clearly needs one (for example reading tomorrow's bookings from the jobs system). Money and customer-facing changes
need a person to approve."""


def facts_for_model(o: Opportunity) -> dict[str, Any]:
    return {
        "pattern_type": KIND_NAMES[o.kind],
        "what_happens_today": today_text(o),
        "people": [_name(a) for a in o.actors[:3]],
        "systems_seen": o.systems,
        "examples_with_ids_hidden": o.examples[:4],
        "times_per_month": o.occurrences_per_month,
        "when": f"{o.period} {o.anchor}".strip() if o.period else "",
        "approval_seen_in_data": o.approval_seen,
        "target_action": o.target_action,
    }


LIST_FIELDS = ("steps", "ai_help", "human_approval", "systems")


def normalise_model_answer(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Accepts a single sentence where a list was asked for (a common model habit); records each fix."""
    fixed = dict(data)
    notes = []
    for key in LIST_FIELDS:
        if isinstance(fixed.get(key), str):
            text = fixed[key].strip()
            fixed[key] = [text] if text else []
            notes.append(f"{key} given as text, read as a list")
    return fixed, notes


def validate_model_answer(data: dict[str, Any]) -> list[str]:
    problems = []
    for key, kind in (
        ("title", str),
        ("trigger_type", str),
        ("trigger", str),
        ("steps", list),
        ("ai_help", list),
        ("human_approval", list),
        ("needs_approval", bool),
        ("risk", str),
        ("risk_reason", str),
        ("systems", list),
    ):
        if not isinstance(data.get(key), kind):
            problems.append(f"{key} missing or not a {kind.__name__}")
    if data.get("trigger_type") not in TRIGGERS:
        problems.append("trigger_type not allowed")
    if data.get("risk") not in RISKS:
        problems.append("risk not allowed")
    if isinstance(data.get("steps"), list) and not 2 <= len(data["steps"]) <= 8:
        problems.append("steps must have 2-8 items")
    return problems


def model_proposal(o: Opportunity, client: ChatClient, guard: bool = True) -> Proposal:
    """The model's proposal; falls back to the rules on a missing answer or a malformed one."""
    base = rules_proposal(o)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(facts_for_model(o), indent=1)},
    ]
    try:
        data = client.json_chat(messages)
    except (CacheMiss, RateLimited) as exc:
        base.notes.append(f"model not used: {exc}")
        return base
    data, fixes = normalise_model_answer(data) if isinstance(data, dict) else ({}, [])
    problems = validate_model_answer(data)
    if problems:
        base.notes.append("model answer rejected: " + "; ".join(problems))
        return base
    p = Proposal(
        opportunity=o.id,
        title=str(data["title"]),
        today=base.today,
        trigger_type=str(data["trigger_type"]),
        trigger=str(data["trigger"]),
        steps=[str(s) for s in data["steps"]],
        ai_help=[str(s) for s in data["ai_help"]],
        human_approval=[str(s) for s in data["human_approval"]],
        needs_approval=bool(data["needs_approval"]),
        risk=str(data["risk"]),
        risk_reason=str(data["risk_reason"]),
        systems=[str(s).lower() for s in data["systems"]],
        hours_saved_per_month=o.hours_saved_per_month,
        source="model",
        notes=fixes,
    )
    if guard:
        apply_guard(p, base)
    return p


def apply_guard(p: Proposal, base: Proposal) -> None:
    if RISKS.index(p.risk) < RISKS.index(base.risk):
        p.notes.append(f"risk raised from {p.risk} to {base.risk} by the safety rules")
        p.risk, p.risk_reason = base.risk, base.risk_reason
    if p.risk != "low" and not p.needs_approval:
        p.notes.append("a person approval step was added by the safety rules")
        p.needs_approval = True
        p.human_approval = (
            p.human_approval or base.human_approval or ["A person approves each item before it is saved"]
        )


def propose_all(opps: list[Opportunity], client: ChatClient | None = None, top: int = 5) -> list[Proposal]:
    out = []
    for i, o in enumerate(opps):
        if client is not None and i < top:
            out.append(model_proposal(o, client))
        else:
            out.append(rules_proposal(o))
    return out
