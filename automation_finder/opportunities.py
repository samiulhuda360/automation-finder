"""Merges detector output into opportunities and puts an hours figure, a risk level and a rank on each one.

The hours are an estimate, and the page says so: occurrences per month (counted from the data) times minutes
per task (an assumption from TimeModel, editable per opportunity in the web page).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from automation_finder.events import Event, display_mask, num, seq, span_months
from automation_finder.patterns import Pattern

KIND_PRIORITY = ["copy", "handoff", "periodic", "near_duplicate"]
KIND_NAMES = {
    "copy": "copying between systems",
    "handoff": "hand-off between people",
    "periodic": "repeating routine",
    "near_duplicate": "repeated request",
}
MONEY_SYSTEMS = {"accounts", "payroll", "finance", "billing", "xero", "quickbooks", "myob"}
CUSTOMER_SYSTEMS = {"jobs", "crm", "helpdesk", "bookings", "booking", "scheduling", "calendar"}
WRITE_WORDS = re.compile(r"\b(create|enter|post|pay|record|add|raise|issue)\b")
CHANGE_WORDS = re.compile(r"\b(update|change|reschedul\w*|move|cancel|delete|amend|edit)\b")


@dataclass
class TimeModel:
    """Minutes one occurrence takes a person, by pattern kind. A stated assumption, not a measurement."""

    copy: float = 5.0  # read the source, re-type the record
    request: float = 6.0  # read a request, act on it, answer it
    handoff_step: float = 3.0  # each person's step in a hand-off (read, forward, approve, record)
    routine: float = 4.0  # one routine action (a reminder, an export); calendar blocks use their own length

    @classmethod
    def from_dict(cls, data: dict[str, float] | None) -> TimeModel:
        model = cls()
        for k, v in (data or {}).items():
            if hasattr(model, k):
                setattr(model, k, float(v))
        return model


AUTOMATION_SHARE = {"copy": 0.8, "periodic": 0.8, "near_duplicate": 0.6, "handoff": 0.6}
EASE = {"copy": 3, "periodic": 3, "near_duplicate": 2, "handoff": 2}


@dataclass
class Opportunity:
    id: str
    kind: str  # the primary kind, which decides the trigger and the workflow shape
    kinds: list[str]
    actors: list[str]
    systems: list[str]
    events: list[str]
    occurrences_per_month: float
    minutes_per_task: float
    default_minutes_per_task: float
    hours_per_month: float
    automation_share: float
    hours_saved_per_month: float
    ease: int
    risk: str
    risk_reason: str
    trigger: str  # email | ticket | app_event | schedule
    score: float
    evidence: dict[str, object] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    target_action: str = ""
    period: str = ""
    anchor: str = ""
    approval_seen: bool = False

    def to_dict(self) -> dict[str, object]:
        out = asdict(self)
        out.pop("events")
        out["event_count"] = len(self.events)
        return out


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)

    def groups(self) -> list[list[int]]:
        out: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            out.setdefault(self.find(i), []).append(i)
        return list(out.values())


def _same_routine(a: Pattern, b: Pattern) -> bool:
    """Two halves of one job: the same person's routine at the same time, or copies into the same place."""
    if a.kind == b.kind == "periodic":
        return (
            a.actors == b.actors
            and a.detail["period"] == b.detail["period"]
            and a.detail["anchor"] == b.detail["anchor"]
            and abs(num(a.detail["hour"]) - num(b.detail["hour"])) <= 1.5
        )
    if a.kind == b.kind == "copy":
        return a.actors == b.actors and a.keys[1] == b.keys[1] and a.systems[0] == b.systems[0]
    return False


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(1, min(len(a), len(b)))


def pattern_minutes(p: Pattern, by_id: dict[str, Event], tm: TimeModel) -> float:
    if p.kind == "copy":
        return p.occurrences * tm.copy
    if p.kind == "near_duplicate":
        return p.occurrences * tm.request
    if p.kind == "handoff":
        return p.occurrences * num(p.detail["steps_per_chain"]) * tm.handoff_step
    return p.occurrences * tm.routine


def _routine_minutes(parts: list[Pattern], by_id: dict[str, Event], tm: TimeModel) -> float:
    """A routine with a calendar block is costed at the block's length; the actions inside it are part of it."""
    blocks = [by_id[e] for p in parts for e in p.events if by_id[e].source == "calendar"]
    if blocks:
        return sum(b.duration_min or 0 for b in blocks)
    return sum(pattern_minutes(p, by_id, tm) for p in parts)


def assess_risk(writes: list[tuple[str, str]], approval: bool) -> tuple[str, str]:
    """What goes wrong if the automation gets one wrong: money spent, money or customer records wrong, or little.

    writes: (system, action) for every record the automated version would create or change.
    """
    if approval:
        return "high", "it commits money: a person approves each one today and must keep approving"
    for system, action in writes:
        if system in MONEY_SYSTEMS and WRITE_WORDS.search(action):
            return "medium", f"it writes financial records in {system}; a wrong entry costs money"
    for system, action in writes:
        if system in CUSTOMER_SYSTEMS and CHANGE_WORDS.search(action):
            return "medium", f"it changes {system} records that customers rely on"
    return "low", "a mistake is easy to spot and undo (a reminder, a report or a new internal record)"


def _trigger(primary: Pattern, by_id: dict[str, Event]) -> str:
    if primary.kind == "periodic":
        return "schedule"
    first = by_id[primary.events[0]]
    return {"email": "email", "ticket": "ticket"}.get(first.source, "app_event")


def build_opportunities(
    patterns: list[Pattern],
    events: list[Event],
    key_labels: dict[str, str],
    tm: TimeModel | None = None,
    minutes_override: dict[str, float] | None = None,
) -> list[Opportunity]:
    tm = tm or TimeModel()
    by_id = {e.id: e for e in events}
    months = span_months(events)

    # Stage 1: parts of one routine are added together.
    uf = _UnionFind(len(patterns))
    for i in range(len(patterns)):
        for j in range(i + 1, len(patterns)):
            if _same_routine(patterns[i], patterns[j]):
                uf.union(i, j)
    merged: list[tuple[list[Pattern], float]] = []
    counts: list[int] = []
    for group in uf.groups():
        parts = [patterns[i] for i in group]
        if parts[0].kind == "periodic":
            minutes = _routine_minutes(parts, by_id, tm)
            blocks = sum(by_id[e].source == "calendar" for p in parts for e in p.events)
            counts.append(blocks or sum(p.occurrences for p in parts))
        else:
            minutes = sum(pattern_minutes(p, by_id, tm) for p in parts)
            counts.append(sum(p.occurrences for p in parts))
        merged.append((parts, minutes))

    # Stage 2: the same work seen by two detectors is one opportunity; keep the fuller estimate, not the sum.
    uf2 = _UnionFind(len(merged))
    sets = [{e for p in parts for e in p.events} for parts, _ in merged]
    for i in range(len(merged)):
        for j in range(i + 1, len(merged)):
            if _overlap(sets[i], sets[j]) >= 0.3:
                uf2.union(i, j)

    out: list[Opportunity] = []
    for group in uf2.groups():
        parts = [p for i in group for p in merged[i][0]]
        minutes = max(merged[i][1] for i in group)
        event_ids = sorted({e for p in parts for e in p.events}, key=lambda x: by_id[x].when)
        kinds = sorted({p.kind for p in parts}, key=KIND_PRIORITY.index)
        primary = max((p for p in parts if p.kind == kinds[0]), key=lambda p: p.occurrences)
        occurrences = max([counts[i] for i in group if merged[i][0][0].kind == kinds[0]] or [1])
        per_month = occurrences / months
        hours = minutes / 60 / months
        default_minutes = minutes / occurrences
        actors = [a for a, _ in Counter(by_id[e].actor for e in event_ids).most_common()]
        systems = _flow_systems(primary, parts, by_id)
        target_action = str(primary.detail.get("target_action", ""))
        approval = any(bool(p.detail.get("approval")) for p in parts)
        examples = _examples(primary, by_id, key_labels)
        evidence = {k: v for p in parts for k, v in p.detail.items()}
        if primary.kind == "periodic":  # every part of the routine, in the order it is done
            routine = sorted((p for p in parts if p.kind == "periodic"), key=lambda p: num(p.detail["hour"]))
            evidence["hour"] = num(routine[0].detail["hour"])
            examples = list(dict.fromkeys(key_labels.get(p.keys[0], p.keys[0]) for p in routine))[:4]
        writes = sorted(
            {
                (by_id[e].system, by_id[e].action)
                for p in parts
                for e in p.events
                if by_id[e].source == "activity" and (p.kind != "copy" or by_id[e].key == p.keys[1])
            }
        )
        risk, reason = assess_risk(writes, approval)
        opp = Opportunity(
            id="",
            kind=primary.kind,
            kinds=kinds,
            actors=actors[:4],
            systems=systems,
            events=event_ids,
            occurrences_per_month=round(per_month, 1),
            minutes_per_task=round(default_minutes, 1),
            default_minutes_per_task=round(default_minutes, 1),
            hours_per_month=0.0,
            automation_share=AUTOMATION_SHARE[primary.kind],
            hours_saved_per_month=0.0,
            ease=max(1, EASE[primary.kind] - (risk == "high")),
            risk=risk,
            risk_reason=reason,
            trigger=_trigger(primary, by_id),
            score=0.0,
            evidence=evidence,
            examples=examples,
            target_action=target_action,
            period=str(primary.detail.get("period", "")),
            anchor=str(primary.detail.get("anchor", "")),
            approval_seen=approval,
        )
        opp.hours_per_month = round(hours, 2)
        out.append(opp)
    rank(out, minutes_override)
    return out


def _flow_systems(primary: Pattern, parts: list[Pattern], by_id: dict[str, Event]) -> list[str]:
    """Systems in the order work flows through them; the last one is where records get written."""
    if primary.kind == "handoff":
        route = [str(k) for k in seq(primary.detail.get("common_route"))]
        ordered = [k.split(":")[0] for k in route]
    else:
        ordered = list(primary.systems)
    for p in parts:
        ordered += p.systems
    return [s for s in dict.fromkeys(ordered) if s != "calendar"] or ["calendar"]


def _examples(primary: Pattern, by_id: dict[str, Event], key_labels: dict[str, str]) -> list[str]:
    if primary.kind == "handoff":  # one real route, step by step, with ids hidden
        ref = by_id[primary.events[0]].primary_ref
        route = [by_id[e] for e in primary.events if by_id[e].primary_ref == ref]
        return [f"{e.actor}: {display_mask(e.text)}" for e in route][:5]
    seen: list[str] = []
    for key in primary.keys:
        label = key_labels.get(key, key)
        if label not in seen:
            seen.append(label)
    return seen[:4]


def rank(opps: list[Opportunity], minutes_override: dict[str, float] | None = None) -> None:
    """Applies any edited minutes, recomputes hours, and orders by hours saved weighted by ease."""
    for o in opps:
        o.hours_per_month = round(o.occurrences_per_month * o.minutes_per_task / 60, 2)
    overrides = minutes_override or {}
    for o in opps:
        if o.id in overrides:
            o.minutes_per_task = float(overrides[o.id])
        o.hours_per_month = round(o.occurrences_per_month * o.minutes_per_task / 60, 2)
        o.hours_saved_per_month = round(o.hours_per_month * o.automation_share, 2)
        o.score = round(o.hours_saved_per_month * {3: 1.0, 2: 0.8, 1: 0.6}[o.ease], 2)
    opps.sort(key=lambda o: (-o.score, o.id))
    for i, o in enumerate(opps, 1):  # ids follow the first ranking and then stay fixed while minutes are edited
        o.id = o.id or f"O{i}"
